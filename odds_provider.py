from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

import os
import requests
from dotenv import load_dotenv

# ----------------------------
# Initialization
# ----------------------------

load_dotenv()
API_KEY = os.getenv("ODDS_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing ODDS_API_KEY in environment (.env).")

BASE_URL = "https://api.the-odds-api.com/v4"

# Your bot supports these leagues (internal keys)
SUPPORTED_LEAGUES = {
    "nba": "basketball_nba",
    "nfl": "americanfootball_nfl",
    "nhl": "icehockey_nhl",
}

DEFAULT_REGIONS = "us"
DEFAULT_MARKETS = "spreads,totals"
DEFAULT_ODDS_FORMAT = "american"
DEFAULT_DATE_FORMAT = "iso"
DEFAULT_BOOKMAKERS = "draftkings"  # odds api expects lowercase keys often

LOCAL_TZ = ZoneInfo("America/Edmonton")
UTC_TZ = ZoneInfo("UTC")

# Reuse HTTP session (faster, cleaner)
_session = requests.Session()


# ----------------------------
# Data containers
# ----------------------------

@dataclass(frozen=True)
class TimeWindowUTC:
    start_utc: str
    end_utc: str


# ----------------------------
# Helper utilities
# ----------------------------

def _today_window_utc(local_tz: ZoneInfo = LOCAL_TZ) -> TimeWindowUTC:
    """
    Returns today's window in UTC, based on local midnight in Edmonton:
      [today 00:00 local, tomorrow 00:00 local)
    """
    now_local = datetime.now(local_tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)

    start_utc = start_local.astimezone(UTC_TZ).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_utc = end_local.astimezone(UTC_TZ).strftime("%Y-%m-%dT%H:%M:%SZ")
    return TimeWindowUTC(start_utc=start_utc, end_utc=end_utc)


def format_game_time(utc_string: str, local_tz: ZoneInfo = LOCAL_TZ) -> str:
    """
    Convert ISO UTC string (e.g. '2026-03-01T03:00:00Z') to local time string.
    """
    utc_dt = datetime.fromisoformat(utc_string.replace("Z", "+00:00"))
    local_dt = utc_dt.astimezone(local_tz)
    return local_dt.strftime("%I:%M %p")


def _league_to_sport_key(league: str) -> str:
    league = league.lower()
    if league not in SUPPORTED_LEAGUES:
        raise ValueError(
            f"Unsupported league '{league}'. Supported: {list(SUPPORTED_LEAGUES.keys())}"
        )
    return SUPPORTED_LEAGUES[league]


def _normalize_team_key(team_name: str) -> str:
    """
    Converts 'New York Knicks' -> 'knicks'
    Converts 'San Antonio Spurs' -> 'spurs'
    Your command expects nickname-only matching, so we use the last word.
    """
    if not team_name:
        return ""
    parts = team_name.strip().lower().split()
    return parts[-1] if parts else ""


# ----------------------------
# Core API functions
# ----------------------------

def fetch_odds(
    league: str,
    *,
    regions: str = DEFAULT_REGIONS,
    markets: str = DEFAULT_MARKETS,
    odds_format: str = DEFAULT_ODDS_FORMAT,
    date_format: str = DEFAULT_DATE_FORMAT,
    bookmakers: Optional[str] = DEFAULT_BOOKMAKERS,
    commence_from_utc: Optional[str] = None,
    commence_to_utc: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch odds for a league from The Odds API.
    Returns the parsed JSON list of events (games).
    """
    sport_key = _league_to_sport_key(league)

    if commence_from_utc is None or commence_to_utc is None:
        window = _today_window_utc()
        commence_from_utc = window.start_utc
        commence_to_utc = window.end_utc

    url = f"{BASE_URL}/sports/{sport_key}/odds"
    params: Dict[str, Any] = {
        "apiKey": API_KEY,
        "regions": regions,
        "markets": markets,
        "oddsFormat": odds_format,
        "dateFormat": date_format,
        "commenceTimeFrom": commence_from_utc,
        "commenceTimeTo": commence_to_utc,
    }
    if bookmakers:
        params["bookmakers"] = bookmakers

    resp = _session.get(url, params=params, timeout=15)

    if resp.status_code != 200:
        # include response body because Odds API returns helpful error messages
        raise RuntimeError(
            f"Odds API failed ({resp.status_code}): {resp.text}"
        )

    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError("Unexpected Odds API response format (expected list).")
    return data


def get_todays_games(league: str) -> List[Dict[str, Any]]:
    """
    Returns today's games (events) for the given league.
    """
    window = _today_window_utc()
    return fetch_odds(
        league,
        commence_from_utc=window.start_utc,
        commence_to_utc=window.end_utc,
    )


def find_game_for_team_today(league: str, team_key: str) -> Optional[Dict[str, Any]]:
    """
    Finds the event dict for the game that team is playing TODAY.
    team_key is nickname-based (e.g. 'warriors', 'knicks', 'spurs').
    """
    team_key_norm = (team_key or "").strip().lower()
    if not team_key_norm:
        return None

    events = get_todays_games(league)
    for event in events:
        home = _normalize_team_key(event.get("home_team", ""))
        away = _normalize_team_key(event.get("away_team", ""))

        if team_key_norm == home or team_key_norm == away:
            return event

    return None

def list_todays_games(league: str) -> list[dict]:
    """
    Returns a list like:
    [{"event_id": "...", "home_team": "...", "away_team": "...", "commence_time": "..."}]
    """
    events = get_todays_games(league)  # raw events from API
    out = []
    for e in events:
        out.append({
            "event_id": e.get("id"),
            "home_team": e.get("home_team"),
            "away_team": e.get("away_team"),
            "commence_time": e.get("commence_time"),
        })
    return out
# ----------------------------
# Parsing / normalization
# ----------------------------

def extract_spread_and_total(event: Dict[str, Any], bookmaker_key: str = "draftkings") -> Dict[str, Any]:
    """
    Returns a dict like:
    {
      "bookmaker": "draftkings",
      "spread_home": 4.5,
      "spread_away": -4.5,
      "spread_home_price": -115,
      "spread_away_price": -115,
      "total": 211.5,
      "over_price": -120,
      "under_price": -110
    }

    If something is missing, the relevant fields will be None.
    """
    home_team = event.get("home_team")
    away_team = event.get("away_team")

    result = {
        "bookmaker": bookmaker_key,
        "spread_home": None,
        "spread_away": None,
        "spread_home_price": None,
        "spread_away_price": None,
        "total": None,
        "over_price": None,
        "under_price": None,
    }

    bookmakers = event.get("bookmakers", [])
    if not bookmakers:
        return result

    book = next((b for b in bookmakers if b.get("key") == bookmaker_key), None)
    if not book:
        return result

    markets = book.get("markets", [])
    if not markets:
        return result

    spreads_market = next((m for m in markets if m.get("key") == "spreads"), None)
    totals_market = next((m for m in markets if m.get("key") == "totals"), None)

    if spreads_market:
        outcomes = spreads_market.get("outcomes", [])
        home_out = next((o for o in outcomes if o.get("name") == home_team), None)
        away_out = next((o for o in outcomes if o.get("name") == away_team), None)

        if home_out:
            result["spread_home"] = home_out.get("point")
            result["spread_home_price"] = home_out.get("price")
        if away_out:
            result["spread_away"] = away_out.get("point")
            result["spread_away_price"] = away_out.get("price")

    if totals_market:
        outcomes = totals_market.get("outcomes", [])
        over_out = next((o for o in outcomes if str(o.get("name", "")).lower() == "over"), None)
        under_out = next((o for o in outcomes if str(o.get("name", "")).lower() == "under"), None)

        total_point = None
        if over_out and over_out.get("point") is not None:
            total_point = over_out.get("point")
        elif under_out and under_out.get("point") is not None:
            total_point = under_out.get("point")

        result["total"] = total_point
        if over_out:
            result["over_price"] = over_out.get("price")
        if under_out:
            result["under_price"] = under_out.get("price")

    return result


def build_line_data_for_db(event: Dict[str, Any], bookmaker_key: str = DEFAULT_BOOKMAKERS) -> Dict[str, Any]:
    """
    Convert an Odds API event dict -> a compact line_data dict for insert_line(...).

    Returns something like:
    {
      "bookmaker": "draftkings",
      "spread_home": 4.5,
      "spread_away": -4.5,
      "total": 211.5
    }
    """
    extracted = extract_spread_and_total(event, bookmaker_key=bookmaker_key)
    return {
        "bookmaker": extracted.get("bookmaker"),
        "spread_home": extracted.get("spread_home"),
        "spread_away": extracted.get("spread_away"),
        "total": extracted.get("total"),
        # If you later decide to store prices too, add them here.
    }


def build_event_data_for_db(event: Dict[str, Any], league: str) -> Dict[str, Any]:
    """
    Convert an Odds API event dict -> event_data for insert_event_if_missing(...).

    Returns:
    {
      "id": <event_id>,
      "sport_key": <Odds API sport_key>,
      "home_team": ...,
      "away_team": ...,
      "commence_time": ... (ISO string)
    }
    """
    return {
        "id": event["id"],
        "sport_key": event.get("sport_key") or _league_to_sport_key(league),
        "home_team": event["home_team"],
        "away_team": event["away_team"],
        "commence_time": event["commence_time"],
    }

