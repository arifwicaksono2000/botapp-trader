import os
import requests
import mysql.connector
from datetime import datetime, timedelta
from ..settings import *
from .event_handlers import on_connected
from twisted.internet import reactor

def handle_token_refresh(bot):
    
    # Prevent infinite refresh loops
    if bot.is_refreshing_token:
        print("[!!!] FATAL: Already attempting to refresh token. Shutting down to prevent loop.")
        if reactor.running: reactor.stop()
        return

    bot.is_refreshing_token = True
    token_url = "https://openapi.ctrader.com/apps/token"
    
    db = None # Initialize db connection to None
    try:
        # 1. Fetch the latest refresh token from your database
        db = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME
        )
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT refresh_token FROM botcore_token WHERE is_used = TRUE ORDER BY created_at DESC LIMIT 1")
        row = cursor.fetchone()

        if not row:
            raise RuntimeError("No active refresh token found in the database.")

        refresh_token_val = row["refresh_token"]
        print(f"🔄 Using refresh token: ...{refresh_token_val[-6:]}")

        # 2. Request new access token
        resp = requests.post(token_url, data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token_val,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }, timeout=15) # Add a timeout for safety

        resp.raise_for_status() # Raises an exception for bad status codes (4xx or 5xx)

        data = resp.json()
        if data.get("errorCode"):
            raise RuntimeError(f"cTrader API Error: {data['errorCode']} - {data.get('description')}")

        new_access_token = data["accessToken"]
        new_refresh_token = data["refreshToken"]
        expires_at = datetime.now() + timedelta(seconds=data["expires_in"])
        
        print("✅ Token refreshed successfully!")

        # 3. Store the new tokens
        cursor.execute("UPDATE botcore_token SET is_used = FALSE WHERE is_used = TRUE")
        cursor.execute("""
            INSERT INTO botcore_token (access_token, refresh_token, is_used, expires_at, created_at, user_id)
            VALUES (%s, %s, TRUE, %s, %s, 1)
        """, (new_access_token, new_refresh_token, expires_at, datetime.now()))
        db.commit()
        
        print("📦 New tokens saved to database.")

        bot.access_token = new_access_token
        print("[SUCCESS] New access token fetched and updated in bot's memory.")
        
        # Reset the flag and restart the authentication process
        bot.is_refreshing_token = False
        on_connected(bot)

    except Exception as e:
        print(f"[!!!] FATAL: An unexpected error occurred during token refresh: {e}")
        if reactor.running:
            reactor.stop()
    # finally:
    #     if db and db.is_connected():
    #         cursor.close()
    #         db.close()
            
    #     if reactor.running:
    #         reactor.stop()