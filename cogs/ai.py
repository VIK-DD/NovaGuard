"""🧠 AI category — ask Claude anything, right inside Discord."""

import os
import time
from collections import deque

import discord
from discord import app_commands
from discord.ext import commands

from core.config import github_config
from core.theme import Palette, brand_footer, make_embed
from core.utils import respond, truncate

# Cost guards: cap input size, plus a global sliding-window + daily ceiling so a
# flood of users (or one abuser) cannot run up the Anthropic bill. Per-user
# spacing is handled separately by the 15s command cooldown below.
MAX_QUESTION_CHARS = 2000
GLOBAL_RATE = (30, 60)  # at most 30 /ask calls per 60s across the whole bot
DAILY_CAP = 500         # rough daily ceiling on AI calls

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

    async def cog_unload(self):
        if self.client:
            await self.client.close()

    def _within_budget(self):
        """Global cost guard: bound total /ask calls per minute and per day."""
        now = time.time()
        rate, window = GLOBAL_RATE
        while self._recent and now - self._recent[0] > window:
            self._recent.popleft()
        today = int(now // 86400)
        if today != self._day:
            self._day = today
            self._day_count = 0
        if len(self._recent) >= rate or self._day_count >= DAILY_CAP:
            return False
        self._recent.append(now)
        self._day_count += 1
        return True

    @app_commands.command(name="ask", description="Ask Claude AI anything")
    @app_commands.describe(question="What do you want to know?")
    @app_commands.checks.cooldown(1, 15.0)
    async def ask(self, interaction: discord.Interaction, question: str):
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

        question = question.strip()[:MAX_QUESTION_CHARS]
        if not question:
            embed = make_embed("✍️ Empty question", "Ask me something first!", color=Palette.WARNING)
            brand_footer(embed, "AI system")
            return await respond(interaction, embed, ephemeral=True)

        if not self._within_budget():
            embed = make_embed(
                "🧊 AI is taking a breather",
                "The assistant is handling a lot of requests right now. Please try again shortly.",
                color=Palette.WARNING,
            )
            brand_footer(embed, "AI system")
            return await respond(interaction, embed, ephemeral=True)

        await interaction.response.defer()

        try:
            response = await self.client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": question}],
            )
        except anthropic.AuthenticationError:
            embed = make_embed("🔑 Invalid API key", "Check `ANTHROPIC_API_KEY` in `.env`.", color=Palette.DANGER)
            brand_footer(embed, "AI system")
            return await respond(interaction, embed)
        except anthropic.RateLimitError:
            embed = make_embed("🧊 AI is rate limited", "Too many requests — try again in a minute.", color=Palette.WARNING)
            brand_footer(embed, "AI system")
            return await respond(interaction, embed)
        except anthropic.APIStatusError as error:
            embed = make_embed("💥 AI service error", f"The API returned `{error.status_code}`. Try again soon.", color=Palette.DANGER)
            brand_footer(embed, "AI system")
            return await respond(interaction, embed)
        except anthropic.APIConnectionError:
            embed = make_embed("🌐 Network hiccup", "Could not reach the AI service. Try again.", color=Palette.WARNING)
            brand_footer(embed, "AI system")
            return await respond(interaction, embed)

        if response.stop_reason == "refusal":
            embed = make_embed("🙅 Declined", "Claude preferred not to answer that one.", color=Palette.WARNING)
            brand_footer(embed, "AI system")
            return await respond(interaction, embed)

        answer = "".join(block.text for block in response.content if block.type == "text").strip()
        if not answer:
            answer = "*Claude stayed silent… try rephrasing.*"

        embed = make_embed(f"🧠 {truncate(question, 230)}", clamp_text(answer), color=Palette.PURPLE)
        brand_footer(embed, f"{ANTHROPIC_MODEL} • asked by {interaction.user.display_name}")
        await respond(interaction, embed)


async def setup(bot):
    await bot.add_cog(AI(bot))
