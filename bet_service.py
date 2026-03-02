from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Tuple, List

import odds_provider
import db
import re

def normalize_team_key(nickname: str) -> str:
    return re.sub(r"[^a-z0-9]", "", nickname.lower().strip())

LOCAL_TZ = ZoneInfo("America/Edmonton")


# ----------------------------
# Helpers
# ----------------------------



def money_to_cents(amount: float | int | str) -> int:
    """
    Convert user input like 50 or "50" or 50.25 into cents.
    (You can simplify later if you only allow integers.)
    """
    if isinstance(amount, str):
        amount = amount.strip().replace("$", "")
    dollars = float(amount)
    if dollars < 0:
        raise ValueError("Amount must be positive.")
    return int(round(dollars * 100))


def cents_to_money_str(cents: int) -> str:
    return f"${cents/100:.2f}"


@dataclass(frozen=True)
class SpreadResult:
    team_key: str
    event_id: str
    line_id: str
    home_team: str
    away_team: str
    commence_time_iso: str
    bookmaker: str
    spread_home: float | None
    spread_away: float | None
    total: float | None
    expires_at: datetime


# ----------------------------
# Core flows
# ----------------------------

def handle_spread(
    channel_id: str,
    league: str,
    nickname: str,
    requester_user_id: str,
    *,
    expiry_minutes: int = 10,
    bookmaker_key: str = odds_provider.DEFAULT_BOOKMAKERS,
) -> Tuple[bool, str]:
    """
    Flow:
      normalize nickname -> team_key
      find today's event for that team
      if None -> not playing today
      else:
        upsert event
        insert line -> line_id
        create spread_request with expiry
        return formatted message
    """
    team_key = normalize_team_key(nickname)
    if not team_key:
        return False, "Please provide a team nickname (ex: Warriors)."

    # 1) Find today's game for that team
    event = odds_provider.find_game_for_team_today(league, team_key)
    if event is None:
        return False, f"{nickname} is not playing today."

    # 2) Build DB payloads
    event_data = odds_provider.build_event_data_for_db(event, league=league)
    line_data = odds_provider.build_line_data_for_db(event, bookmaker_key=bookmaker_key)

    # 3) Upsert event + insert line
    event_id = db.insert_event_if_missing(event_data)
    line_id = db.insert_line(event_id, line_data)

    # 4) Create spread request (valid for expiry_minutes)
    expires_at = (
    datetime.now(timezone.utc)
    + timedelta(minutes=10)
    ).replace(tzinfo=None)
    db.create_spread_request(
        channel_id=channel_id,
        team_key=team_key,
        event_id=event_id,
        line_id=line_id,
        expires_at=expires_at,
    )

    # 5) Format response
    home = event.get("home_team", "HOME")
    away = event.get("away_team", "AWAY")
    local_time = odds_provider.format_game_time(event["commence_time"])

    spread_bits: List[str] = []
    if line_data.get("spread_home") is not None:
        spread_bits.append(f"{home}: {line_data['spread_home']}")
    if line_data.get("spread_away") is not None:
        spread_bits.append(f"{away}: {line_data['spread_away']}")
    spread_str = " | ".join(spread_bits) if spread_bits else "Spread: N/A"

    total_str = f"Total: {line_data['total']}" if line_data.get("total") is not None else "Total: N/A"
    book_str = f"Book: {line_data.get('bookmaker', bookmaker_key)}"

    msg = (
        f"**{away} @ {home}** ({local_time})\n"
        f"{book_str}\n"
        f"{spread_str}\n"
        f"{total_str}\n"
        f"Spread locked for **{expiry_minutes} min**. You can now bet with `!bet{nickname}$amount`."
    )
    return True, msg


def handle_bet(
    channel_id: str,
    user_id: str,
    username: str,
    nickname: str,
    amount: float | int | str,
    *,
    starting_balance_cents: int = 0,
) -> Tuple[bool, str]:
    """
    Flow:
      normalize nickname -> team_key
      validate spread_request exists and not expired
      check balance
      deduct wager
      insert bet row (event_id + line_id)
      return confirmation message
    """
    team_key = normalize_team_key(nickname)
    if not team_key:
        return False, "Please provide a team nickname (ex: Warriors)."
    req = db.get_valid_spread_request(channel_id, team_key)

    wager_cents = money_to_cents(amount)
    if wager_cents <= 0:
        return False, "Bet amount must be greater than $0."

    # Ensure user exists
    db.get_or_create_user(user_id, username, starting_balance_cents)

    # 1) Must have a valid spread request (your rule)
    req = db.get_valid_spread_request(channel_id=channel_id, team_key=team_key)
    if not req:
        return False, f"No active spread found for **{nickname}** in this channel. Run `!spreadNba{nickname}` (or `!spreadNfl...` / `!spreadNhl...`) first."

    event_id = req["event_id"]
    line_id = req["line_id"]

    # 2) Deduct balance safely (prevents negative)
    ok = db.add_balance(user_id, -wager_cents)
    if not ok:
        bal = db.get_balance(user_id)
        return False, f"Insufficient funds. Your balance is {cents_to_money_str(bal)}."

    # 3) Insert bet
    bet_id = db.insert_bet(
        user_id=user_id,
        event_id=event_id,
        team_key=team_key,
        line_id=line_id,
        wager_cents=wager_cents,
    )

    new_bal = db.get_balance(user_id)
    msg = (
        f"✅ Bet placed! **{username}** bet {cents_to_money_str(wager_cents)} on **{nickname}**.\n"
        f"Bet ID: `{bet_id}`\n"
        f"New balance: {cents_to_money_str(new_bal)}"
    )
    return True, msg


def handle_balance(user_id: str, username: str, *, starting_balance_cents: int = 0) -> Tuple[bool, str]:
    """
    Ensures user exists, then returns their balance.
    """
    db.get_or_create_user(user_id, username, starting_balance_cents)
    bal = db.get_balance(user_id)
    return True, f"Balance for **{username}**: {cents_to_money_str(bal)}"


def handle_leaderboard(limit: int = 3) -> Tuple[bool, str]:
    """
    Returns a simple leaderboard message.
    """
    rows = db.top_balances(limit=limit)
    if not rows:
        return True, "No users yet."

    lines = ["🏆 **Leaderboard**"]
    for i, r in enumerate(rows, start=1):
        name = r.get("username") or r.get("user_id")
        bal = r.get("balance_cents", 0)
        lines.append(f"{i}. {name} — {cents_to_money_str(bal)}")
    return True, "\n".join(lines)


def handle_give(
    target_user_id: str,
    target_username: str,
    amount: float | int | str,
    *,
    starting_balance_cents: int = 0,
) -> Tuple[bool, str]:
    """
    Manager/admin-only command in main.py (role check stays in main).
    This function only performs the DB operations.

    Adds amount to the target user's balance.
    """
    delta_cents = money_to_cents(amount)
    if delta_cents <= 0:
        return False, "Give amount must be greater than $0."

    db.get_or_create_user(target_user_id, target_username, starting_balance_cents)
    db.add_balance(target_user_id, delta_cents)

    new_bal = db.get_balance(target_user_id)
    return True, f"✅ Gave {cents_to_money_str(delta_cents)} to **{target_username}**. New balance: {cents_to_money_str(new_bal)}"
