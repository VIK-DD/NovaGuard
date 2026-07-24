"""🎉 Fun category — games, chance, vibes and a little bit of love."""

import asyncio
import hashlib
import html
import random
from datetime import UTC, datetime

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from core.theme import Palette, brand_footer, make_embed, progress_bar
from core.utils import defer_interaction, respond, truncate

POSITIVE_ANSWERS = [
    "It is certain.",
    "Without a doubt.",
    "Yes — definitely.",
    "You may rely on it.",
    "As I see it, yes.",
    "Most likely.",
    "Outlook good.",
    "Signs point to yes.",
]
NEUTRAL_ANSWERS = [
    "Reply hazy, try again.",
    "Ask again later.",
    "Better not tell you now.",
    "Cannot predict now.",
    "Concentrate and ask again.",
]
NEGATIVE_ANSWERS = [
    "Don't count on it.",
    "My reply is no.",
    "My sources say no.",
    "Outlook not so good.",
    "Very doubtful.",
]
JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "There are only 10 types of people: those who understand binary and those who don't.",
    "A SQL query walks into a bar, goes up to two tables and asks: 'Can I join you?'",
    "Why do Java developers wear glasses? Because they can't C#.",
    "I told my computer I needed a break, and it said 'no problem — I'll go to sleep.'",
    "Debugging: being the detective in a crime movie where you are also the murderer.",
    "99 little bugs in the code, 99 little bugs… take one down, patch it around, 127 little bugs in the code.",
    "Why did the developer go broke? Because he used up all his cache.",
    "It works on my machine. — Ancient developer proverb",
    "The best thing about a boolean is that even if you are wrong, you are only off by a bit.",
    "A programmer's wife says: 'Go to the store and buy milk. If they have eggs, buy 12.' He returns with 12 milks.",
    "Git happens.",
]
RPS_EMOJIS = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
RPS_BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
SHIP_TIERS = [
    (90, "Soulmates detected 💞", Palette.FUN),
    (70, "Serious spark 💖", Palette.FUN),
    (50, "There's potential 💘", Palette.PURPLE),
    (30, "Friendship vibes 🫂", Palette.INFO),
    (0, "Awkward silence 🥶", Palette.DARK),
]
VIBE_TIERS = [
    (90, "IMMACULATE VIBES ✨", Palette.GOLD),
    (70, "Great energy today 🌞", Palette.SUCCESS),
    (50, "Perfectly balanced ⚖️", Palette.INFO),
    (30, "Slightly cursed 🌧️", Palette.ORANGE),
    (0, "Vibe emergency 🚨", Palette.DANGER),
]


def stable_percent(seed_text):
    digest = hashlib.md5(seed_text.encode("utf-8")).hexdigest()
    return int(digest, 16) % 101


def pick_tier(score, tiers):
    for threshold, label, color in tiers:
        if score >= threshold:
            return label, color
    return tiers[-1][1], tiers[-1][2]


class RPSButton(discord.ui.Button):
    def __init__(self, choice):
        super().__init__(label=choice.title(), emoji=RPS_EMOJIS[choice], style=discord.ButtonStyle.primary)
        self.choice = choice

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        bot_choice = random.choice(list(RPS_EMOJIS))

        if self.choice == bot_choice:
            title, color = "🤝 It's a tie!", Palette.WARNING
        elif RPS_BEATS[self.choice] == bot_choice:
            title, color = "🎉 You win!", Palette.SUCCESS
        else:
            title, color = "🤖 I win!", Palette.DANGER

        embed = make_embed(
            title,
            f"You picked {RPS_EMOJIS[self.choice]} **{self.choice.title()}** — "
            f"I picked {RPS_EMOJIS[bot_choice]} **{bot_choice.title()}**.",
            color=color,
        )
        brand_footer(embed, "Rock Paper Scissors")
        for child in view.children:
            child.disabled = True
        view.stop()
        await interaction.response.edit_message(embed=embed, view=view)


class RPSView(discord.ui.View):
    def __init__(self, player_id):
        super().__init__(timeout=60)
        self.player_id = player_id
        for choice in RPS_EMOJIS:
            self.add_item(RPSButton(choice))

    async def interaction_check(self, interaction):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("This duel is not yours — start your own with `/rps`!", ephemeral=True)
            return False
        return True


class TriviaButton(discord.ui.Button):
    def __init__(self, answer, is_correct):
        super().__init__(label=truncate(answer, 75), style=discord.ButtonStyle.secondary)
        self.answer = answer
        self.is_correct = is_correct

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        for child in view.children:
            child.disabled = True
            if getattr(child, "is_correct", False):
                child.style = discord.ButtonStyle.success
        view.stop()

        if self.is_correct:
            embed = make_embed(
                "🧠 Correct!",
                f"**Q:** {view.question}\n**A:** {view.correct_answer}\n\nBig brain energy!",
                color=Palette.SUCCESS,
            )
        else:
            self.style = discord.ButtonStyle.danger
            embed = make_embed(
                "😅 Not quite",
                f"**Q:** {view.question}\n**A:** {view.correct_answer}",
                color=Palette.DANGER,
            )
        brand_footer(embed, "Trivia")
        await interaction.response.edit_message(embed=embed, view=view)


class TriviaView(discord.ui.View):
    def __init__(self, player_id, question, correct_answer, answers):
        super().__init__(timeout=30)
        self.player_id = player_id
        self.question = question
        self.correct_answer = correct_answer
        self.message = None
        for answer in answers:
            self.add_item(TriviaButton(answer, answer == correct_answer))

    async def interaction_check(self, interaction):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("This question belongs to someone else — try `/trivia`!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class Fun(commands.Cog):
    """Games, chance and good vibes."""

    EMOJI = "🎉"
    COLOR = Palette.FUN
    DESCRIPTION = "8-ball, trivia, rock-paper-scissors, ships, vibes and more."

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="8ball", description="Ask the magic 8-ball anything")
    @app_commands.describe(question="Your burning question")
    async def eight_ball(self, interaction: discord.Interaction, question: str):
        bucket = random.choice((POSITIVE_ANSWERS, NEUTRAL_ANSWERS, NEGATIVE_ANSWERS))
        answer = random.choice(bucket)
        color = Palette.SUCCESS if bucket is POSITIVE_ANSWERS else Palette.WARNING if bucket is NEUTRAL_ANSWERS else Palette.DANGER

        embed = make_embed("🎱 The Magic 8-Ball", f"**Q:** {question}\n\n**A:** {answer}", color=color)
        brand_footer(embed, "Fate consulted")
        await respond(interaction, embed)

    @app_commands.command(name="coinflip", description="Flip a coin")
    async def coinflip(self, interaction: discord.Interaction):
        result = random.choice(("Heads", "Tails"))
        embed = make_embed("🪙 Coin flip", f"The coin lands on… **{result}**!", color=Palette.GOLD)
        brand_footer(embed, "50/50, no take-backs")
        await respond(interaction, embed)

    @app_commands.command(name="dice", description="Roll some dice")
    @app_commands.describe(sides="Sides per die (2-1000)", count="How many dice (1-10)")
    async def dice(
        self,
        interaction: discord.Interaction,
        sides: app_commands.Range[int, 2, 1000] = 6,
        count: app_commands.Range[int, 1, 10] = 1,
    ):
        rolls = [random.randint(1, sides) for _ in range(count)]
        rolls_text = " ".join(f"`{roll}`" for roll in rolls)
        description = f"Rolling {count}d{sides}…\n\n🎲 {rolls_text}"
        if count > 1:
            description += f"\n\n**Total:** `{sum(rolls)}`"

        embed = make_embed("🎲 Dice roll", description, color=Palette.PURPLE)
        brand_footer(embed, "May luck be with you")
        await respond(interaction, embed)

    @app_commands.command(name="rps", description="Rock, paper, scissors against the bot")
    async def rps(self, interaction: discord.Interaction):
        embed = make_embed(
            "🪨📄✂️ Rock Paper Scissors",
            f"{interaction.user.mention}, pick your weapon!",
            color=Palette.FUN,
        )
        brand_footer(embed, "Choose wisely")
        await respond(interaction, embed, view=RPSView(interaction.user.id))

    @app_commands.command(name="trivia", description="Answer a trivia question against the clock")
    @app_commands.describe(difficulty="How spicy should it be?")
    @app_commands.choices(
        difficulty=[
            app_commands.Choice(name="Easy", value="easy"),
            app_commands.Choice(name="Medium", value="medium"),
            app_commands.Choice(name="Hard", value="hard"),
        ]
    )
    @app_commands.checks.cooldown(1, 10.0)
    async def trivia(self, interaction: discord.Interaction, difficulty: app_commands.Choice[str] | None = None):
        await defer_interaction(interaction)

        params = {"amount": 1, "type": "multiple"}
        if difficulty:
            params["difficulty"] = difficulty.value

        data = None
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get("https://opentdb.com/api.php", params=params) as response:
                    if response.status == 200:
                        data = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            data = None

        results = (data or {}).get("results") or []
        if not results:
            embed = make_embed(
                "🌐 Trivia is napping",
                "Could not reach the trivia service. Try again in a bit.",
                color=Palette.WARNING,
            )
            brand_footer(embed)
            return await respond(interaction, embed)

        result = results[0]
        question = html.unescape(result["question"])
        correct = html.unescape(result["correct_answer"])
        answers = [correct] + [html.unescape(item) for item in result["incorrect_answers"]]
        random.shuffle(answers)

        embed = make_embed(
            f"🧠 Trivia • {html.unescape(result.get('category', 'General'))}",
            f"**{question}**\n\nDifficulty: `{result.get('difficulty', 'any').title()}` • 30 seconds on the clock!",
            color=Palette.PURPLE,
        )
        brand_footer(embed, "Trivia")
        view = TriviaView(interaction.user.id, question, correct, answers)
        await respond(interaction, embed, view=view)
        view.message = await interaction.original_response()

    @app_commands.command(name="joke", description="A programming joke, guaranteed* funny")
    async def joke(self, interaction: discord.Interaction):
        embed = make_embed("😂 Here you go", random.choice(JOKES), color=Palette.FUN)
        brand_footer(embed, "*guarantee not legally binding")
        await respond(interaction, embed)

    @app_commands.command(name="ship", description="Love compatibility between two people")
    @app_commands.describe(user1="First person", user2="Second person (defaults to you)")
    async def ship(self, interaction: discord.Interaction, user1: discord.User, user2: discord.User | None = None):
        partner = user2 or interaction.user
        low, high = sorted((user1.id, partner.id))
        score = 100 if user1.id == partner.id else stable_percent(f"{low}-{high}")
        label, color = pick_tier(score, SHIP_TIERS)

        name_a = user1.display_name
        name_b = partner.display_name
        ship_name = name_a[: max(len(name_a) // 2, 1)] + name_b[len(name_b) // 2:]
        bar = progress_bar(score, 100, slots=10, filled="❤️", empty="🖤")

        embed = make_embed(
            f"💘 {name_a} × {name_b}",
            f"Ship name: **{ship_name}**\n\n{bar}\n\n# {score}%\n**{label}**",
            color=color,
        )
        brand_footer(embed, "Love calculator")
        await respond(interaction, embed)

    @app_commands.command(name="vibecheck", description="Daily vibe reading for a member")
    @app_commands.describe(user="Whose vibe? (defaults to you)")
    async def vibecheck(self, interaction: discord.Interaction, user: discord.User | None = None):
        target = user or interaction.user
        today = datetime.now(UTC).date().isoformat()
        score = stable_percent(f"{target.id}-{today}")
        label, color = pick_tier(score, VIBE_TIERS)
        bar = progress_bar(score, 100, slots=10)

        embed = make_embed(
            f"🔮 Vibe check • {target.display_name}",
            f"{bar}\n\n# {score}/100\n**{label}**",
            color=color,
        )
        brand_footer(embed, "Recalibrates daily")
        await respond(interaction, embed)


async def setup(bot):
    await bot.add_cog(Fun(bot))
