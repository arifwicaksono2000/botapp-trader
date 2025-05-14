from dotenv import load_dotenv
import requests
import mysql.connector
from datetime import datetime, timedelta
import os

load_dotenv()

# Config
CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
TOKEN_URL = "https://openapi.ctrader.com/apps/token"

# 1. Fetch the latest refresh token from your database
db = mysql.connector.connect(
    host=os.getenv("DB_HOST"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASS"),
    database=os.getenv("DB_NAME")
)
cursor = db.cursor(dictionary=True)
cursor.execute("SELECT refresh_token FROM botcore_token WHERE is_used = TRUE ORDER BY created_at DESC LIMIT 1")
row = cursor.fetchone()

if not row:
    print("No refresh token found.")
    exit()

refresh_token_val = row["refresh_token"]
print("🔄 Using refresh token:", refresh_token_val)

# 2. Request new access token
resp = requests.post(TOKEN_URL, data={
    "grant_type": "refresh_token",
    "refresh_token": refresh_token_val,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET
})

if resp.status_code != 200:
    print(f"❌ Failed to refresh token: {resp.status_code} {resp.text}")
    exit()

data = resp.json()
if data.get("errorCode"):
    print(f"❌ Error: {data['errorCode']} - {data.get('description')}")
    exit()

new_access_token = data["accessToken"]
new_refresh_token = data["refreshToken"]
print("✅ Token refreshed successfully!")
print("Access token:", new_access_token)
print("Refresh token:", new_refresh_token)
# print("Below are the whole thing:")
# print(data)
expires_at = datetime.now() + timedelta(seconds=data["expires_in"])

# 3. Store the new tokens
cursor.execute("UPDATE botcore_token SET is_used = FALSE WHERE is_used = TRUE")
cursor.execute("""
    INSERT INTO botcore_token (access_token, refresh_token, is_used, expires_at, created_at, user_id)
    VALUES (%s, %s, TRUE, %s, %s, 1)
""", (new_access_token, new_refresh_token, expires_at, datetime.now()))
db.commit()
cursor.close()
db.close()

print("📦 New tokens saved to database.")
