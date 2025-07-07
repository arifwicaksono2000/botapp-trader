import os
from dotenv import load_dotenv, find_dotenv
from ctrader_open_api import EndPoints

# Locate the actual .env path
dotenv_path = find_dotenv()

# Print which file is being loaded
# print("[DEBUG] Loading .env from:", dotenv_path)

# Load it explicitly
load_dotenv(dotenv_path=dotenv_path)

HOST = EndPoints.PROTOBUF_DEMO_HOST
PORT = EndPoints.PROTOBUF_PORT

DB_HOST: str | None = os.getenv("DB_HOST")
DB_USER: str | None = os.getenv("DB_USER")
DB_PASS: str | None = os.getenv("DB_PASS")
DB_NAME: str | None = os.getenv("DB_NAME")


CLIENT_ID: str | None = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET: str | None = os.getenv("CTRADER_CLIENT_SECRET")
ACCOUNT_ID: int = int(os.getenv("CTRADER_ACCOUNT", 0))
SYMBOL_ID: int = int(os.getenv("CTRADER_SYMBOL_ID", 1))  # EUR/USD default

MYSQL_URL: str | None = os.getenv("MYSQL_URL")
MYSQL_SYNC_URL = MYSQL_URL.replace("mysql+aiomysql", "mysql+pymysql")