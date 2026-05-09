import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(
    BASE_DIR,
    "eyecept.db"
)

def get_connection():

    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False
    )

    conn.execute(
        "PRAGMA journal_mode=WAL;"
    )

    conn.execute(
        "PRAGMA busy_timeout = 30000;"
    )

    return conn