"""🧠 AI category — ask Claude anything, right inside Discord."""

import os
import time
from collections import deque

import discord
from discord import app_commands
from discord.ext import commands

from core.ai_settings import resolve_ai
from core.config import github_config
from core.storage import get_guild_settings
from core.theme import Palette, brand_footer, make_embed
from core.utils import defer_interaction, respond, truncate

# Cost guards: cap input size, plus a global sliding-window + daily ceiling so a
# flood of users (or one abuser) cannot run up the Anthropic bill. Per-user
# spacing is handled separately by the 15s command cooldown below.
MAX_QUESTION_CHARS = 2000
GLOBAL_RATE = (30, 60)  # at most 30 /ask calls per 60s across the whole bot
DAILY_CAP = 500         # rough daily ceiling on AI calls
# The same ceilings, per server.
#
# Without these the caps above are a shared pool with nothing dividing it: the
# per-user cooldown is 15 seconds, so thirty members of one busy server reach
# the global minute limit without any of them doing anything wrong, and /ask
# is then unavailable everywhere else the bot is. One server's ordinary
# Saturday should not be an outage for the rest.
GUILD_RATE = (10, 60)
GUILD_DAILY_CAP = 100

try:
    import anthropic
    from anthropic import AsyncAnthropic
except ImportError:  # SDK not installed — /ask explains how to enable it
    anthropic = None
    AsyncAnthropic = None

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
SYSTEM_PROMPT = (
    f"You are the resident AI of a Discord server, running inside the {github_config.brand_name} bot. "
    "Be helpful, friendly and a little playful. Keep answers under 300 words unless the question "
    "truly needs more. Use Discord markdown (bold, bullet lists, code blocks) when it helps readability."
)


def clamp_text(text, limit=4000):
    return text if len(text) <= limit else text[: limit - 1] + "…"


class AI(commands.Cog):
    """Claude, live in your server."""

    EMOJI = "🧠"
    COLOR = Palette.PURPLE
    DESCRIPTION = "Ask Claude anything with /ask — AI answers right in the chat."

    def __init__(self, bot):
        self.bot = bot
        api_key = os.getenv("ANTHROPIC_API_KEY")
        self.client = AsyncAnthropic(api_key=api_key) if (AsyncAnthropic and api_key) else None
        self._recent = deque()  # timestamps for the global sliding window
        self._day = 0           # current day ordinal
        self._day_count = 0     # calls made today
        self._guild_recent: dict[int, deque] = {}   # guild -> sliding window
        self._guild_day_count: dict[int, int] = {}  # guild -> calls today

    async def cog_unload(self):
        if self.client:
            await self.client.close()

    def _refresh_budget_window(self, now):
        rate, window = GLOBAL_RATE
        while self._recent and now - self._recent[0] > window:
            self._recent.popleft()
        today = int(now // 86400)
        if today != self._day:
            self._day = today
            self._day_count = 0
            self._guild_day_count.clear()
            self._guild_recent.clear()
        return rate

    def _refresh_guild_window(self, guild_id, now):
        _, window = GUILD_RATE
        recent = self._guild_recent.setdefault(guild_id, deque())
        while recent and now - recent[0] > window:
            recent.popleft()
        # Servers that asked once and stopped should not sit in memory forever.
        if len(self._guild_recent) > 500:
            for stale in [g for g, r in self._guild_recent.items() if not r and g != guild_id]:
                self._guild_recent.pop(stale, None)
        return recent

    def status_payload(self, guild=None):
        """Operational AI state for the dashboard; never includes the API key.

        With a guild, the numbers are that server's own budget - which is what
        somebody looking at their own dashboard is actually asking about.
        Without one, the instance-wide totals.
        """
        now = time.time()
        rate = self._refresh_budget_window(now)
        guild_id = getattr(guild, "id", None)
        if guild_id is None:
            minute_calls, minute_cap = len(self._recent), rate
            daily_calls, daily_cap = self._day_count, DAILY_CAP
        else:
            minute_calls = len(self._refresh_guild_window(guild_id, now))
            minute_cap = GUILD_RATE[0]
            daily_calls = self._guild_day_count.get(guild_id, 0)
            daily_cap = GUILD_DAILY_CAP
        return {
            "available": self.client is not None,
            "model": ANTHROPIC_MODEL if self.client is not None else None,
            "minute_calls": minute_calls,
            "minute_cap": minute_cap,
            "daily_calls": daily_calls,
            "daily_cap": daily_cap,
        }

    def _within_budget(self, guild_id):
        """Cost guard: bound /ask calls per minute and per day, twice.

        Globally, because the bill is one bill. And per server, because the
        global ceiling on its own is a shared pool that the busiest server
        empties for everybody else.
        """
        now = time.time()
        rate = self._refresh_budget_window(now)
        if len(self._recent) >= rate or self._day_count >= DAILY_CAP:
            return False

        guild_recent = self._refresh_guild_window(guild_id, now)
        if (
            len(guild_recent) >= GUILD_RATE[0]
            or self._guild_day_count.get(guild_id, 0) >= GUILD_DAILY_CAP
        ):
            return False

        self._recent.append(now)
        self._day_count += 1
        guild_recent.append(now)
        self._guild_day_count[guild_id] = self._guild_day_count.get(guild_id, 0) + 1
        return True

    def _refund_budget(self, guild_id):
        """Give the reservation back when the call never happened.

        The budget is spent before the request, which is right - two people
        asking at once must not both pass a check that only one of them fits
        through. But an upstream error means nothing was generated and nothing
        was billed, and charging the day's quota for Anthropic being down
        turns their outage into ours.
        """
        if self._recent:
            self._recent.pop()
        self._day_count = max(0, self._day_count - 1)
        guild_recent = self._guild_recent.get(guild_id)
        if guild_recent:
            guild_recent.pop()
        self._guild_day_count[guild_id] = max(0, self._guild_day_count.get(guild_id, 1) - 1)

    @app_commands.command(name="ask", description="Send a question to Anthropic's Claude AI")
    @app_commands.describe(question="Question to send to Anthropic (maximum 2,000 characters)")
    @app_commands.checks.cooldown(1, 15.0)
    @app_commands.guild_only()
    async def ask(self, interaction: discord.Interaction, question: str):
        settings = resolve_ai(get_guild_settings(interaction.guild_id))
        if not settings["enabled"]:
            embed = make_embed(
                "🧠 AI disabled here",
                "A server manager has disabled `/ask` for this server.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "AI system")
            return await respond(interaction, embed, ephemeral=True)

        allowed_channel_id = settings["channel_id"]
        if allowed_channel_id and str(interaction.channel_id) != allowed_channel_id:
            channel = interaction.guild.get_channel(int(allowed_channel_id))
            destination = channel.mention if channel else "the configured AI channel"
            embed = make_embed(
                "🧭 Use the AI channel",
                f"`/ask` is available in {destination} on this server.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "AI system")
            return await respond(interaction, embed, ephemeral=True)

        if self.client is None:
            embed = make_embed(
                "🔌 AI not configured",
                (
                    "To enable `/ask`:\n"
                    "1. `pip3 install anthropic`\n"
                    "2. Set `ANTHROPIC_API_KEY` in `.env` (get one at console.anthropic.com)\n"
                    "3. Restart the bot"
                ),
                color=Palette.WARNING,
            )
            brand_footer(embed, "AI system")
            return await respond(interaction, embed, ephemeral=True)

        question = question.strip()
        if not question:
            embed = make_embed("✍️ Empty question", "Ask me something first!", color=Palette.WARNING)
            brand_footer(embed, "AI system")
            return await respond(interaction, embed, ephemeral=True)
        question_limit = min(settings["max_question_chars"], MAX_QUESTION_CHARS)
        if len(question) > question_limit:
            embed = make_embed(
                "✂️ Question too long",
                f"Keep this server's AI questions under `{question_limit}` characters.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "AI system")
            return await respond(interaction, embed, ephemeral=True)

        if not self._within_budget(interaction.guild_id):
            embed = make_embed(
                "🧊 AI is taking a breather",
                "The assistant is handling a lot of requests right now. Please try again shortly.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "AI system")
            return await respond(interaction, embed, ephemeral=True)

        private_answer = settings["answer_mode"] == "private"
        await defer_interaction(interaction, ephemeral=private_answer)

        try:
            response = await self.client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": question}],
            )
        except anthropic.AuthenticationError:
            self._refund_budget(interaction.guild_id)
            embed = make_embed(
                "🔑 AI authentication unavailable",
                "The assistant is not available right now. Please try again later.",
                color=Palette.DANGER,
            )
            brand_footer(embed, "AI system")
            return await respond(interaction, embed, ephemeral=private_answer)
        except anthropic.RateLimitError:
            self._refund_budget(interaction.guild_id)
            embed = make_embed("🧊 AI is rate limited", "Too many requests — try again in a minute.", color=Palette.WARNING)
            brand_footer(embed, "AI system")
            return await respond(interaction, embed, ephemeral=private_answer)
        except anthropic.APIStatusError as error:
            self._refund_budget(interaction.guild_id)
            embed = make_embed("💥 AI service error", f"The API returned `{error.status_code}`. Try again soon.", color=Palette.DANGER)
            brand_footer(embed, "AI system")
            return await respond(interaction, embed, ephemeral=private_answer)
        except anthropic.APIConnectionError:
            self._refund_budget(interaction.guild_id)
            embed = make_embed("🌐 Network hiccup", "Could not reach the AI service. Try again.", color=Palette.WARNING)
            brand_footer(embed, "AI system")
            return await respond(interaction, embed, ephemeral=private_answer)

        if response.stop_reason == "refusal":
            embed = make_embed("🙅 Declined", "Claude preferred not to answer that one.", color=Palette.WARNING)
            brand_footer(embed, "AI system")
            return await respond(interaction, embed, ephemeral=private_answer)

        answer = "".join(block.text for block in response.content if block.type == "text").strip()
        if not answer:
            answer = "*Claude stayed silent… try rephrasing.*"

        embed = make_embed(f"🧠 {truncate(question, 230)}", clamp_text(answer), color=Palette.PURPLE)
        brand_footer(embed, f"{ANTHROPIC_MODEL} • asked by {interaction.user.display_name}")
        await respond(interaction, embed, ephemeral=private_answer)


async def setup(bot):
    await bot.add_cog(AI(bot))
