import sqlite3
import hashlib
import uuid
from datetime import datetime
from .db import get_connection
import os
from dotenv import load_dotenv

load_dotenv()


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


# =========================
# USERS
# =========================


def create_user(name, email, password, role, phone):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO users (name, email, password, role, phone)
            VALUES (?, ?, ?, ?, ?)
        """,
            (name, email, hash_password(password), role, phone),
        )

        conn.commit()
        return True

    except:
        return False

    finally:
        conn.close()


def get_user_by_email(email):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()

    conn.close()
    return user


def verify_user(email, password, role):
    user = get_user_by_email(email)

    if not user:
        return None

    if user[3] == hash_password(password) and user[4] == role:
        return user

    return None


def get_user_by_id(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM users WHERE id = ?
    """, (user_id,))

    user = cursor.fetchone()

    conn.close()
    return user



def update_user(user_id, name, email, phone):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE users
        SET name = ?, email = ?, phone = ?
        WHERE id = ? AND role != 'Admin'
    """,
        (name, email, phone, user_id),
    )

    conn.commit()
    conn.close()



def update_password(user_id, password):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE users SET password = ?
        WHERE id = ?
    """, (hash_password(password), user_id))

    conn.commit()
    conn.close()


def delete_user(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()

    if user and user[0] == "admin":
        conn.close()
        return False

    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    return True


def update_profile(user_id, data):
    conn = get_connection()
    cursor = conn.cursor()

    fields = []
    values = []

    for key, value in data.items():
        fields.append(f"{key} = ?")
        values.append(value)

    values.append(user_id)

    query = f"UPDATE users SET {', '.join(fields)} WHERE id = ?"

    cursor.execute(query, values)
    conn.commit()
    conn.close()


def get_all_users():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(" SELECT * FROM users WHERE role != 'Admin' ORDER BY id DESC")
    users = cursor.fetchall()

    conn.close()
    return users


# =========================
# PASSWORD RESET
# =========================

import random
from datetime import datetime, timedelta


def generate_otp():
    return str(random.randint(100000, 999999))


def create_reset_code(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    code = generate_otp()
    expires_at = (datetime.utcnow() + timedelta(minutes=10)).timestamp()

    cursor.execute("""
        INSERT INTO reset_tokens (user_id, token, expires_at)
        VALUES (?, ?, ?)
    """, (user_id, code, expires_at))

    conn.commit()
    conn.close()

    return code


def get_reset_code(user_id, code):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM reset_tokens
        WHERE user_id = ? AND token = ?
        ORDER BY id DESC LIMIT 1
    """, (user_id, code))

    data = cursor.fetchone()
    conn.close()
    return data


def delete_user_tokens(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM reset_tokens WHERE user_id = ?
    """, (user_id,))

    conn.commit()
    conn.close()


def reset_password(token, new_password):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM reset_tokens WHERE token = ?", (token,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return False

    expires = float(row[3])

    if datetime.utcnow().timestamp() > expires:
        conn.close()
        return False

    user_id = row[1]

    cursor.execute(
        """
        UPDATE users SET password = ? WHERE id = ?
    """,
        (hash_password(new_password), user_id),
    )

    cursor.execute("DELETE FROM reset_tokens WHERE token = ?", (token,))

    conn.commit()
    conn.close()

    return True


# =========================
# ALERTS
# =========================


def create_alert(level, snapshot_path, clip_path, reason, camera_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO alerts (level, snapshot_path, clip_path, reason, camera_id)
        VALUES (?, ?, ?, ?, ?)
    """,
        (level, snapshot_path, clip_path, reason, camera_id),
    )

    conn.commit()
    conn.close()


def get_alerts():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM alerts ORDER BY created_at DESC")
    data = cursor.fetchall()

    conn.close()
    return data


# =========================
# SMS LOGS
# =========================


def log_sms(alert_id, user_id, message):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO sms_logs (alert_id, user_id, message)
        VALUES (?, ?, ?)
    """,
        (alert_id, user_id, message),
    )


def create_alert(level, snapshot_path, reason, camera_id=1):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO alerts (level, snapshot_path, reason, camera_id)
        VALUES (?, ?, ?, ?)
    """, (level, snapshot_path, reason, camera_id))

    alert_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return alert_id


def get_security_fields():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, phone FROM users
        WHERE role = 'Security Field'
    """)

    data = cursor.fetchall()
    conn.close()

    return data


def log_sms(alert_id, user_id, message):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO sms_logs (alert_id, user_id, message)
        VALUES (?, ?, ?)
    """, (alert_id, user_id, message))

    conn.commit()
    conn.close()


def get_alerts():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM alerts
        ORDER BY id DESC
        LIMIT 20
    """)

    data = cursor.fetchall()
    conn.close()

    return data


def get_alert(alert_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM alerts WHERE id=?", (alert_id,))
    alert = cursor.fetchone()

    conn.close()
    return alert


def delete_alert(alert_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM sms_logs WHERE alert_id=?", (alert_id,))
    cursor.execute("DELETE FROM alerts WHERE id=?", (alert_id,))

    conn.commit()
    conn.close()


# =========================
# EMAIL 
# =========================

import smtplib
from email.mime.text import MIMEText


def send_email(to_email, code):
    body = f"""Hello,

We received a request to reset your Eyecept account password.

Your verification code is: {code}

If you did not request this, please ignore this email.

Eyecept Team
"""

    msg = MIMEText(body)
    msg['Subject'] = "Eyecept Password Reset Code"
    msg['From'] = "Eyecept <eyecept@gmail.com>"
    msg['To'] = to_email

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(
    os.getenv("EMAIL_USER"),
    os.getenv("EMAIL_PASS")
)
    server.send_message(msg)
    server.quit()


# =========================
# SMS
# =========================

from twilio.rest import Client

ACCOUNT_SID = "ACd523fc3578ce93d7ab905a3bcbee5bca"
AUTH_TOKEN = "5aa1d21acae10ee1c35e44a9e8474601"
FROM_PHONE = "+17625720950"


def send_sms(to_phone, code):
    client = Client(ACCOUNT_SID, AUTH_TOKEN)

    client.messages.create(
        body=f"Your verification code is: {code}",
        from_=FROM_PHONE,
        to=to_phone
    )