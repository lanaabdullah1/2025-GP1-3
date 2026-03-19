import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.security import generate_password_hash

app = Flask(__name__)
app.secret_key = "eyecept-secret-key"


def get_db_connection():
    conn = sqlite3.connect("users.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                email TEXT,
                password_hash TEXT,
                phone_number TEXT,
                shift_days TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                role TEXT NOT NULL
            )
        """)
        conn.commit()


@app.route("/")
def home():
    return redirect(url_for("manage_users"))


@app.route("/manage-users", methods=["GET", "POST"])
def manage_users():
    if request.method == "POST":
        selected_role = request.form.get("role")

        if not selected_role:
            flash("Please choose a user type first.")
            return redirect(url_for("manage_users"))

        if selected_role in ["admin", "security_operator"]:
            return redirect(url_for("register", role=selected_role))

        if selected_role == "field_officer":
            return redirect(url_for("register_fields"))

        flash("Invalid role selected.")
        return redirect(url_for("manage_users"))

    return render_template("ManageUsers.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    selected_role = request.args.get("role", "security_operator")

    if request.method == "POST":
        first_name = request.form.get("firstName", "").strip().title()
        last_name = request.form.get("lastName", "").strip().title()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        shift_days = request.form.getlist("shift_days")
        start_time = request.form.get("start_time", "").strip()
        end_time = request.form.get("end_time", "").strip()
        role = request.form.get("role", "security_operator").strip()

        if not first_name or not last_name or not email or not password:
            flash("Please fill in all required fields.")
            return redirect(url_for("register", role=role))

        if not shift_days:
            flash("Please select at least one shift day.")
            return redirect(url_for("register", role=role))

        if not start_time or not end_time:
            flash("Please select both start time and end time.")
            return redirect(url_for("register", role=role))

        if role not in ["admin", "security_operator"]:
            flash("Invalid role for this form.")
            return redirect(url_for("manage_users"))

        shift_days_text = ",".join(shift_days)
        password_hash = generate_password_hash(password)

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO users (
                        first_name, last_name, email, password_hash,
                        phone_number, shift_days, start_time, end_time, role
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    first_name,
                    last_name,
                    email,
                    password_hash,
                    None,
                    shift_days_text,
                    start_time,
                    end_time,
                    role
                ))
                conn.commit()

            
            if role == "admin":
                flash("Admin added successfully.")
            elif role == "security_operator":
                flash("Security Operator added successfully.")
            else:
                flash("User added successfully.")


            return redirect(url_for("manage_users"))

        except sqlite3.IntegrityError:
            flash("Email already exists.")
            return redirect(url_for("register", role=role))

    return render_template("Register.html", selected_role=selected_role)


@app.route("/register-fields", methods=["GET", "POST"])
def register_fields():
    if request.method == "POST":
        first_name = request.form.get("firstName", "").strip().title()
        last_name = request.form.get("lastName", "").strip().title()
        phone = request.form.get("phoneNumber", "").strip()
        shift_days = request.form.getlist("shift_days")
        start_time = request.form.get("start_time", "").strip()
        end_time = request.form.get("end_time", "").strip()

        if not first_name or not last_name or not phone:
            flash("Please fill all required fields.")
            return redirect(url_for("register_fields"))

        if not shift_days:
            flash("Please select at least one shift day.")
            return redirect(url_for("register_fields"))

        if not start_time or not end_time:
            flash("Please select shift time.")
            return redirect(url_for("register_fields"))

        shift_days_text = ",".join(shift_days)
        role = "field_officer"

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO users (
                        first_name, last_name, email, password_hash,
                        phone_number, shift_days, start_time, end_time, role
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    first_name,
                    last_name,
                    None,
                    None,
                    phone,
                    shift_days_text,
                    start_time,
                    end_time,
                    role
                ))
                conn.commit()

            flash("Field officer added successfully.")
            return redirect(url_for("manage_users"))

        except sqlite3.Error as e:
            flash(f"Error: {e}")
            return redirect(url_for("register_fields"))

    return render_template("RegisterFeild.html")


@app.route("/api/users", methods=["GET"])
def get_users():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, first_name, last_name, email, phone_number, role
            FROM users
            ORDER BY first_name ASC, last_name ASC
        """)
        users = cursor.fetchall()

    users_list = []
    for user in users:
        display_contact = user["email"] if user["email"] else user["phone_number"]
        users_list.append({
            "id": user["id"],
            "name": f'{user["first_name"]} {user["last_name"]}',
            "role": user["role"],
            "contact": display_contact or "-"
        })

    return jsonify(users_list)


@app.route("/api/delete-users", methods=["POST"])
def delete_users():
    data = request.get_json()
    user_ids = data.get("user_ids", [])

    if not user_ids:
        return jsonify({"success": False, "message": "No users selected."}), 400

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(user_ids))
            cursor.execute(f"DELETE FROM users WHERE id IN ({placeholders})", user_ids)
            conn.commit()

        return jsonify({"success": True, "message": "Selected users deleted successfully."})

    except sqlite3.Error as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


if __name__ == "__main__":
    init_db()
    app.run(debug=True)