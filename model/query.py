import sqlite3
from datetime import datetime
from db import get_connection
import hashlib
import uuid


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('Admin', 'Security Operator', 'Security Field')),
        phone TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cameras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        status TEXT DEFAULT 'online',
        last_seen TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        level INTEGER NOT NULL,
        snapshot_path TEXT,
        clip_path TEXT,
        reason TEXT,
        camera_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (camera_id) REFERENCES cameras(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sms_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_id INTEGER,
        user_id INTEGER,
        message TEXT,
        sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (alert_id) REFERENCES alerts(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reset_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        token TEXT,
        expires_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    conn.commit()
    conn.close()


def init_defaults():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE role = 'Admin'")
    admin = cursor.fetchone()

    if not admin:
        cursor.execute(
            """
        INSERT INTO users (name, email, password, role)
        VALUES (?, ?, ?, ?)
        """,
            ("Eyecept Admin", "admin@eyecept.com", hash_password("12345678"), "Admin"),
        )

    cursor.execute("SELECT * FROM cameras")
    cam = cursor.fetchone()

    if not cam:
        cursor.execute(
            """
        INSERT INTO cameras (name, status)
        VALUES (?, ?)
        """,
            ("Main Camera", "online"),
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_tables()
    init_defaults()
    print("DB Ready")
