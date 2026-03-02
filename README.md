# 🏀 Discord Sportsbook Bot

A production-ready Discord bot that allows users to view live sports matchups, check spreads, place virtual bets, and track balances — powered by Python, MySQL, and AWS EC2.

Built with a focus on backend architecture, database design, and production deployment practices.

---

## 🚀 Live Architecture

- **Backend:** Python 3.12  
- **Database:** MySQL 8 (InnoDB, foreign keys enforced)  
- **Deployment:** AWS EC2 (Ubuntu)  
- **Process Management:** systemd (auto-restart & boot persistence)  
- **External API:** The Odds API  
- **Authentication:** Secure MySQL user management  

---

## ✨ Features

### 📅 Daily Game Listings

```
!nba
!nfl
!nhl
```

Displays all games scheduled for the day with formatted start times.

---

### 📊 Spread Retrieval

```
!spreadNbaKnicks
!spreadNflChiefs
!spreadNhlOilers
```

Returns:

- Matchup  
- Bookmaker  
- Spread (home/away)  
- Total points  
- 10-minute betting window  

Spreads are stored as snapshots in the database to ensure bet consistency.

---

### 💰 Betting System

```
!betKnicks$10
!betChiefs$25
```

- Requires active spread request  
- Validates balance before placing bet  
- Deducts wager securely  
- Stores bet with foreign key references  

Balances are stored in **cents (INT)** to avoid floating-point precision issues.

---

### 🏦 User Management

- `!balance` — View balance  
- `!leaderboard` — Top users by balance  

Users are automatically created on first interaction.

---

## 🧠 System Design Highlights

### Database Structure

#### Core Tables

- `users`
- `events`
- `lines`
- `spread_requests`
- `bets`

#### Design Principles

- InnoDB with foreign key constraints  
- Snapshot-based betting (line consistency)  
- Expiring spread requests  
- UTC time standardization  
- Indexed lookup columns for performance  

---

## 🖥 Deployment

The bot runs on an AWS EC2 Ubuntu instance using:

- Python virtual environment  
- Native MySQL installation  
- systemd service configuration  

### Service Management

```bash
sudo systemctl start sportsbook-bot
sudo systemctl stop sportsbook-bot
sudo systemctl restart sportsbook-bot
journalctl -u sportsbook-bot -f
```

The bot:

- Starts automatically on reboot  
- Restarts on crash  
- Logs via `journalctl`  

---

## 🔐 Security Practices

- Database not publicly exposed  
- Dedicated MySQL user with scoped privileges  
- Environment variables stored in `.env`  
- Port 3306 closed in security group  
- SSH restricted to specific IP  

---

## 📦 Local Development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

Initialize database:

```bash
python3 -c "import db; db.initialize_db(); print('DB Ready')"
```

---

## 🛠 Technical Challenges Solved

- MySQL authentication plugin conflicts (`caching_sha2_password`)  
- Host-specific MySQL users (`user@localhost` vs `user@127.0.0.1`)  
- UTC timestamp consistency across services  
- Background process management on EC2  
- Foreign key cascade behaviors  
- Expiring in-channel betting sessions  

---

## 📈 Future Improvements

- Automatic bet settlement engine  
- Admin command panel  
- REST API layer  
- Web dashboard  
- CI/CD deployment pipeline  
- Docker containerization  

---
