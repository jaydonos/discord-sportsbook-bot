# main.py
import os
import re
import discord
from discord.ext import commands
from dotenv import load_dotenv

import db
import bet_service
import odds_provider

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN in environment.")

# Your bot rules/settings
STARTING_BALANCE_CENTS = 1000 * 100   # you had 1000 before (dollars). convert to cents
GIVE_DEFAULT_CENTS = 500 * 100        # default amount for !give if no $amount provided

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ----------------------------
# Parsing helpers
# ----------------------------

def parse_spread_command(content: str):
    """
    !spread{league}{TeamName} e.g. !spreadNbaWarriors
    """
    m = re.match(r"^!spread(nba|nfl|nhl)(.+)$", content, flags=re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lower(), m.group(2).strip()


def parse_bet_command(content: str):
    """
    !bet{teamname}${amount} e.g. !betWarriors$50 or !betKnicks$12.50
    """
    m = re.match(r"^!bet(.+)\$(\d+(?:\.\d{1,2})?)$", content, flags=re.IGNORECASE)
    if not m:
        return None
    nickname = m.group(1).strip()
    amount_str = m.group(2).strip()
    return nickname, amount_str


def parse_give_command(content: str):
    """
    Supports:
      !give @User
      !give @User $123
      !give @User $12.50
    Returns: (amount_str_or_none)
    """
    m = re.search(r"\$(\d+(?:\.\d{1,2})?)$", content)
    return m.group(1) if m else None


def user_is_manager(member: discord.Member) -> bool:
    return any(r.name.lower() == "manager" for r in member.roles)


# ----------------------------
# Discord events
# ----------------------------

@bot.event
async def on_ready():
    # Create tables in MySQL (from db.py)
    db.initialize_db()
    print(f"Logged in as {bot.user}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content.strip()

# ----------------------------------
# !help
# ----------------------------------
    if content.lower() == "!help":
        help_text = (
            "**Available Commands:**\n\n"
            "📅 **Game Lists**\n"
            "`!nba` – List today's NBA games\n"
            "`!nfl` – List today's NFL games\n"
            "`!nhl` – List today's NHL games\n\n"
            "📊 **Spreads**\n"
            "`!spreadNbaTeamName` – Get today's spread (ex: `!spreadNbaKnicks`)\n\n"
            "💰 **Betting**\n"
            "`!betTeamName$amount` – Place bet (ex: `!betKnicks$10`)\n"
            "`!balance` – View your balance\n"
            "`!leaderboard` – Top balances\n\n"
            "👑 **Manager Only**\n"
            "`!give @User $amount` – Give money to a user"
        )

        await message.channel.send(help_text)
        return

    # ----------------------------------
    # !nba / !nfl / !nhl
    # ----------------------------------
    if content.lower() in ("!nba", "!nfl", "!nhl"):
        league = content.lower().lstrip("!")
        try:
            games = odds_provider.get_todays_games(league)
        except Exception as e:
            return False, f"Error getting today's games: `{type(e).__name__}: {e}`"

        if not games:
            await message.channel.send(f"No {league.upper()} games today.")
            return

        lines = [f"**{league.upper()} games today:**"]
        for e in games:
            lines.append(
                f"• **{e['away_team']} @ {e['home_team']}** — {odds_provider.format_game_time(e['commence_time'])}"
            )
        await message.channel.send("\n".join(lines))
        return
    

    # ----------------------------------
    # !spread{league}{TeamName}
    # Example: !spreadNbaKnicks
    # ----------------------------------
    spread_parsed = parse_spread_command(content)
    if spread_parsed:
        league, nickname = spread_parsed

        ok, msg = bet_service.handle_spread(
            channel_id=str(message.channel.id),
            league=league,
            nickname=nickname,
            requester_user_id=str(message.author.id),
        )

        await message.channel.send(msg)
        return

    # ----------------------------------
    # !bet{TeamName}$amount
    # Example: !betKnicks$5
    # ----------------------------------
    bet_parsed = parse_bet_command(content)
    if bet_parsed:
        nickname, amount = bet_parsed

        ok, msg = bet_service.handle_bet(
            channel_id=str(message.channel.id),
            user_id=str(message.author.id),
            username=message.author.name,
            nickname=nickname,
            amount=amount,
            starting_balance_cents=1000 * 100,
        )

        await message.channel.send(msg)
        return

    # ----------------------------------
    # !balance
    # ----------------------------------
    if content.lower() == "!balance":
        ok, msg = bet_service.handle_balance(
            user_id=str(message.author.id),
            username=message.author.name,
            starting_balance_cents=1000 * 100,
        )
        await message.channel.send(msg)
        return

    # ----------------------------------
    # !leaderboard
    # ----------------------------------
    if content.lower() == "!leaderboard":
        ok, msg = bet_service.handle_leaderboard()
        await message.channel.send(msg)
        return

    await bot.process_commands(message)


bot.run(TOKEN)