from dotenv import load_dotenv
import os
from flask import Flask, request, redirect, session
import requests
import urllib.parse
from datetime import datetime, timedelta
import mysql.connector

# Load .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = "some_random_secret_for_session"

CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")

REDIRECT_URI = "http://127.0.0.1:5000/callback"
AUTH_BASE = "https://connect.spotware.com/apps/auth"
TOKEN_URL = "https://openapi.ctrader.com/apps/token"

@app.route("/")
def login():
    # Ideally store a random 'state' in the session and use it in the auth request
    # session['oauth_state'] = ...
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": "trading",
        "state": "xyz"
    }
    auth_url = AUTH_BASE + "?" + urllib.parse.urlencode(params)
    return redirect(auth_url)

@app.route("/callback")
def callback():
    error = request.args.get("error")
    if error:
        return f"Error from cTrader: {error}", 400

    code = request.args.get("code")
    if not code:
        return "No code provided", 400

    token_resp = requests.get(TOKEN_URL, params={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    })

    if token_resp.status_code != 200:
        return f"Token exchange request failed with status {token_resp.status_code}", 400

    data = token_resp.json()
    if data.get("errorCode"):
        return f"Token exchange failed: {data['errorCode']} - {data.get('description')}", 400

    access_token = data["accessToken"]
    refresh_token = data["refreshToken"]
    expires_at = datetime.now() + timedelta(seconds=data["expires_in"])

    # Insert tokens directly into your database
    try:
        db = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            database=os.getenv("DB_NAME")
        )
        cursor = db.cursor()

        # Set all existing tokens to is_used = False
        cursor.execute("UPDATE botcore_token SET is_used = FALSE WHERE is_used = TRUE")

        # Insert the new token as is_used=True
        cursor.execute("""
            INSERT INTO botcore_token (access_token, refresh_token, is_used, expires_at, created_at, user_id)
            VALUES (%s, %s, TRUE, %s, %s, 1)
        """, (access_token, refresh_token, expires_at, datetime.now()))

        db.commit()
        cursor.close()
        db.close()

    except Exception as e:
        return f"Database error: {e}", 500

    return f"""
    <b>Access token stored successfully!</b><br><br>
    <b>Access token:</b> {access_token}<br><br>
    <b>Refresh token:</b> {refresh_token}
    """

if __name__ == "__main__":
    print("🔓 Opening browser to authorize your app...")
    # webbrowser.open("http://127.0.0.1:5000")
    app.run(port=5000, debug=True)
