import mysql.connector

conn = mysql.connector.connect(
    host = "localhost",
    user = "botuser",
    password = "GoodPassword#1",
    database = "discord_bot"
)

cur.conn.cursor()

#Create table:
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
  user_id VARCHAR(50) PRIMARY KEY,
  balance INT NOT NULL
)
""")

#Insert 
cur.execute("""
INSERT INTO users (user_id, balance)
VALUES (%s, %s)
ON DUPLICATE KEY UPDATE balance = VALUES(balance)
""", ("test_user", 1000))

cur.execute("SELECT user_id, balance FROM users WHERE user_id = %s", ("test_user",))
row = cur.fetchone()

print("Fetched from DB:", row)

cur.close()
conn.close()