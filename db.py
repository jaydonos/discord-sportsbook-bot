# db.py
from __future__ import annotations

import os
import uuid
import mysql.connector
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
load_dotenv()


# ----------------------------
# Connection
# ----------------------------

def get_conn():
    db_name = os.getenv("DB_NAME")
    if not db_name:
        raise ValueError("DB_NAME env var is required (ex: DB_NAME=sportsbook).")

    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),   # prefer TCP
        user=os.getenv("DB_USER", "botuser"),
        password=os.getenv("DB_PASSWORD", ""),
        database=db_name,
        autocommit=False,
    )


# ----------------------------
# Schema
# ----------------------------

def initialize_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    # users
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id VARCHAR(50) PRIMARY KEY,
        username VARCHAR(50),
        balance_cents INT NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB;
    """)

    # events
    cur.execute("""
    CREATE TABLE IF NOT EXISTS events (
        event_id VARCHAR(50) PRIMARY KEY,
        league VARCHAR(10) NOT NULL,
        home_team VARCHAR(80) NOT NULL,
        away_team VARCHAR(80) NOT NULL,
        commence_time DATETIME NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
        home_score INT NULL,
        away_score INT NULL
    ) ENGINE=InnoDB;
    """)

    # lines
    cur.execute("""
CREATE TABLE IF NOT EXISTS `lines` (
    `line_id` VARCHAR(50) PRIMARY KEY,
    `event_id` VARCHAR(50) NOT NULL,
    `bookmaker` VARCHAR(50) NOT NULL,
    `spread_home` DECIMAL(4,1) NULL,
    `spread_away` DECIMAL(4,1) NULL,
    `total_points` DECIMAL(5,1) NULL,
    `fetched_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY `idx_lines_event` (`event_id`),
    CONSTRAINT `fk_lines_event`
        FOREIGN KEY (`event_id`) REFERENCES `events`(`event_id`)
        ON DELETE CASCADE
) ENGINE=InnoDB;
""")

    # spread_requests (NO guild_id)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS spread_requests (
        request_id VARCHAR(50) PRIMARY KEY,
        channel_id VARCHAR(50) NOT NULL,
        team_key VARCHAR(50) NOT NULL,
        event_id VARCHAR(50) NOT NULL,
        line_id VARCHAR(50) NOT NULL,
        expires_at DATETIME NOT NULL,
        INDEX (channel_id),
        INDEX (team_key),
        CONSTRAINT fk_sr_event
            FOREIGN KEY (event_id) REFERENCES `events`(`event_id`)
            ON DELETE CASCADE,
        CONSTRAINT fk_sr_line
            FOREIGN KEY (line_id) REFERENCES `lines`(`line_id`)
            ON DELETE CASCADE
    ) ENGINE=InnoDB;
    """)

    # bets (NO guild_id)
    cur.execute("""
CREATE TABLE IF NOT EXISTS `bets` (
    `bet_id` VARCHAR(50) PRIMARY KEY,
    `user_id` VARCHAR(50) NOT NULL,
    `event_id` VARCHAR(50) NOT NULL,
    `team_key` VARCHAR(50) NOT NULL,
    `line_id` VARCHAR(50) NOT NULL,
    `wager_cents` INT NOT NULL,
    `status` VARCHAR(20) NOT NULL DEFAULT 'pending',
    `payout_cents` INT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    KEY `idx_bets_user` (`user_id`),
    KEY `idx_bets_event` (`event_id`),

    CONSTRAINT `fk_bets_user`
        FOREIGN KEY (`user_id`) REFERENCES `users`(`user_id`)
        ON DELETE CASCADE,

    CONSTRAINT `fk_bets_event`
        FOREIGN KEY (`event_id`) REFERENCES `events`(`event_id`)
        ON DELETE CASCADE,

    CONSTRAINT `fk_bets_line`
        FOREIGN KEY (`line_id`) REFERENCES `lines`(`line_id`)
        ON DELETE RESTRICT
) ENGINE=InnoDB;
""")

    conn.commit()
    cur.close()
    conn.close()


# ----------------------------
# Users / balances
# ----------------------------

def get_or_create_user(user_id: str, username: str, starting_balance_cents: int = 0) -> Dict[str, Any]:
    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        INSERT INTO users (user_id, username, balance_cents)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            username = VALUES(username)
    """, (user_id, username, starting_balance_cents))

    conn.commit()

    cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()

    cur.close()
    conn.close()
    return user


def get_balance(user_id: str) -> int:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT balance_cents
        FROM users
        WHERE user_id = %s
    """, (user_id,))

    row = cur.fetchone()
    cur.close()
    conn.close()

    return int(row[0]) if row else 0


def add_balance(user_id: str, delta_cents: int) -> bool:
    """
    Adds delta_cents. Prevents negative balance.
    Returns True if updated, False if insufficient funds or missing user.
    """
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET balance_cents = balance_cents + %s
        WHERE user_id = %s
          AND balance_cents + %s >= 0
    """, (delta_cents, user_id, delta_cents))

    conn.commit()
    ok = (cur.rowcount == 1)

    cur.close()
    conn.close()
    return ok


def set_balance(user_id: str, new_balance_cents: int) -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET balance_cents = %s
        WHERE user_id = %s
    """, (new_balance_cents, user_id))

    conn.commit()
    cur.close()
    conn.close()


def top_balances(limit: int = 3) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT user_id, username, balance_cents
        FROM users
        ORDER BY balance_cents DESC, created_at ASC
        LIMIT %s
    """, (limit,))

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


# ----------------------------
# Odds/event helpers
# ----------------------------

def parse_iso_z(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def normalize_league(sport_key: str) -> str:
    sport_key = (sport_key or "").lower()
    if "nba" in sport_key:
        return "nba"
    if "nfl" in sport_key:
        return "nfl"
    if "nhl" in sport_key:
        return "nhl"
    return sport_key


def insert_event_if_missing(event_data: Dict[str, Any]) -> str:
    conn = get_conn()
    cur = conn.cursor()

    event_id = event_data["id"]
    league = normalize_league(event_data.get("sport_key", ""))
    home_team = event_data["home_team"]
    away_team = event_data["away_team"]
    commence_time = parse_iso_z(event_data["commence_time"])

    cur.execute("""
        INSERT INTO events (
            event_id, league, home_team, away_team, commence_time, status
        )
        VALUES (%s, %s, %s, %s, %s, 'scheduled')
        ON DUPLICATE KEY UPDATE
            league = VALUES(league),
            home_team = VALUES(home_team),
            away_team = VALUES(away_team),
            commence_time = VALUES(commence_time)
    """, (event_id, league, home_team, away_team, commence_time))

    conn.commit()
    cur.close()
    conn.close()
    return event_id


def insert_line(event_id: str, line_data: Dict[str, Any]) -> str:
    conn = get_conn()
    cur = conn.cursor()

    line_id = line_data.get("line_id") or uuid.uuid4().hex
    bookmaker = line_data["bookmaker"]
    spread_home = line_data.get("spread_home")
    spread_away = line_data.get("spread_away")
    total_points = line_data.get("total")

    cur.execute("""
    INSERT INTO `lines` (`line_id`, `event_id`, `bookmaker`, `spread_home`, `spread_away`, `total_points`)
    VALUES (%s, %s, %s, %s, %s, %s)
""", (line_id, event_id, bookmaker, spread_home, spread_away, total_points))

    conn.commit()
    cur.close()
    conn.close()
    return line_id


# ----------------------------
# Spread requests
# ----------------------------

def create_spread_request(
    channel_id: str,
    team_key: str,
    event_id: str,
    line_id: str,
    expires_at: datetime,
) -> str:
    conn = get_conn()
    cur = conn.cursor()

    request_id = uuid.uuid4().hex

    cur.execute("""
        INSERT INTO spread_requests
            (request_id, channel_id, team_key, event_id, line_id, expires_at)
        VALUES
            (%s, %s, %s, %s, %s, %s)
    """, (request_id, channel_id, team_key, event_id, line_id, expires_at))

    conn.commit()
    cur.close()
    conn.close()
    return request_id


def get_valid_spread_request(channel_id: str, team_key: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT
            request_id, channel_id, team_key, event_id, line_id, expires_at
        FROM spread_requests
        WHERE channel_id = %s
          AND team_key = %s
          AND expires_at > UTC_TIMESTAMP()
        ORDER BY expires_at DESC
        LIMIT 1
    """, (channel_id, team_key))

    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


# ----------------------------
# Bets
# ----------------------------

def insert_bet(
    user_id: str,
    event_id: str,
    team_key: str,
    line_id: str,
    wager_cents: int,
) -> str:
    conn = get_conn()
    cur = conn.cursor()

    bet_id = uuid.uuid4().hex

    cur.execute("""
        INSERT INTO bets
            (bet_id, user_id, event_id, team_key, line_id, wager_cents, status)
        VALUES
            (%s, %s, %s, %s, %s, %s, 'pending')
    """, (bet_id, user_id, event_id, team_key, line_id, wager_cents))

    conn.commit()
    cur.close()
    conn.close()
    return bet_id


def get_unsettled_event_ids() -> List[str]:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT b.event_id
        FROM bets b
        JOIN events e ON e.event_id = b.event_id
        WHERE b.status = 'pending'
          AND e.status = 'finished'
    """)

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [r[0] for r in rows]


def get_open_bets_for_event(event_id: str) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT *
        FROM bets
        WHERE event_id = %s
          AND status = 'pending'
        ORDER BY created_at ASC
    """, (event_id,))

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows