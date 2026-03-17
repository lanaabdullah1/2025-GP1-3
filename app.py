import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.security import generate_password_hash

app = Flask(__name__)
app.secret_key = "eyecept-secret-key"


def get_db_connection():
    conn = sqlite3.connect("users.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            shift_type TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


@app.route("/", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        shift_type = request.form.get("shiftType", "").strip()

        if not username or not email or not password or not shift_type:
            flash("Please fill in all fields.")
            return redirect(url_for("register"))

        password_hash = generate_password_hash(password)

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO users (username, email, password_hash, shift_type)
                VALUES (?, ?, ?, ?)
            """, (username, email, password_hash, shift_type))

            conn.commit()
            conn.close()

            flash("User registered successfully.")
            return redirect(url_for("register"))

        except sqlite3.IntegrityError:
            flash("Username or email already exists.")
            return redirect(url_for("register"))

    return render_template("Register.html")


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


if __name__ == "__main__":
    init_db()
    app.run(debug=True)