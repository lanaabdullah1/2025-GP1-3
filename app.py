from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
app.secret_key = "eyecept-secret-key"

DAYS_OPTIONS = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday"
]

DB_HOST = "db.axskxtxwktcgcrnghgmf.supabase.co"
DB_PORT = "5432"
DB_NAME = "postgres"
DB_USER = "postgres"
DB_PASSWORD = "eyeCEPT!27ksu"


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        cursor_factory=RealDictCursor
    )


def format_role(role):
    return role.replace("_", " ").title()


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not email or not password:
            return render_template('log.html', error="Please enter email and password.")

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT id, email, password_hash, role, first_name, last_name
                        FROM users
                        WHERE email = %s
                        LIMIT 1
                    """, (email,))
                    user = cursor.fetchone()

            if user and user["password_hash"] and check_password_hash(user["password_hash"], password):
                session['user'] = user["email"]
                session['user_id'] = user["id"]
                session['role'] = user["role"]
                session['name'] = f'{user["first_name"]} {user["last_name"]}'
                return redirect(url_for('dashboard'))

            return render_template('log.html', error="Wrong login")

        except psycopg2.Error:
            return render_template('log.html', error="Database error. Please try again.")

    return render_template('log.html')


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


@app.route("/update-shift/<int:user_id>", methods=["GET", "POST"])
def update_shift(user_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT id, first_name, last_name, shift_days, start_time, end_time, role
                    FROM users
                    WHERE id = %s
                """, (user_id,))
                user = cursor.fetchone()

        if not user:
            flash("User not found.")
            return redirect(url_for("manage_users"))

        if request.method == "POST":
            shift_days = request.form.getlist("shift_days")
            start_time = request.form.get("start_time", "").strip()
            end_time = request.form.get("end_time", "").strip()

            if not shift_days:
                flash("Please select at least one shift day.")
                return redirect(url_for("update_shift", user_id=user_id))

            if not start_time or not end_time:
                flash("Please select both start time and end time.")
                return redirect(url_for("update_shift", user_id=user_id))

            shift_days_text = ",".join(shift_days)

            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE users
                        SET shift_days = %s, start_time = %s, end_time = %s
                        WHERE id = %s
                    """, (shift_days_text, start_time, end_time, user_id))
                conn.commit()

            flash("Shift updated successfully.")
            return redirect(url_for("manage_users"))

        selected_days = user["shift_days"].split(",") if user["shift_days"] else []

        return render_template(
            "UpdateShift.html",
            user=user,
            selected_days=selected_days,
            days_options=DAYS_OPTIONS,
            formatted_role=format_role(user["role"])
        )

    except psycopg2.Error as e:
        flash(f"Error updating shift: {e}")
        return redirect(url_for("manage_users"))


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
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO users (
                            first_name, last_name, email, password_hash,
                            phone_number, shift_days, start_time, end_time, role
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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

        except psycopg2.IntegrityError:
            flash("Email already exists.")
            return redirect(url_for("register", role=role))

        except psycopg2.Error as e:
            flash(f"Database error: {e}")
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
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO users (
                            first_name, last_name, email, password_hash,
                            phone_number, shift_days, start_time, end_time, role
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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

        except psycopg2.Error as e:
            flash(f"Error: {e}")
            return redirect(url_for("register_fields"))

    return render_template("RegisterFeild.html")


@app.route("/api/users", methods=["GET"])
def get_users():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
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

    except psycopg2.Error as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/delete-users", methods=["POST"])
def delete_users():
    data = request.get_json()
    user_ids = data.get("user_ids", [])

    if not user_ids:
        return jsonify({"success": False, "message": "No users selected."}), 400

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM users WHERE id = ANY(%s)", (user_ids,))
            conn.commit()

        return jsonify({"success": True, "message": "Selected users deleted successfully."})

    except psycopg2.Error as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/dashboard")
def dashboard():
    snapshots = [
        {"id": 1, "img": "...", "level": "Low", "date": "...", "time": "..."},
        {"id": 2, "img": "...", "level": "High", "date": "...", "time": "..."}
    ]
    return render_template("dashboard.html", snapshots=snapshots)


@app.route("/details/<int:id>")
def details(id):
    if 'user' not in session:
        return redirect(url_for('login'))

    snapshots = [
        {"id": 1, "img": "...", "level": "Low", "date": "...", "time": "..."},
        {"id": 2, "img": "...", "level": "High", "date": "...", "time": "..."}
    ]

    snapshot = next((s for s in snapshots if s["id"] == id), None)
    return render_template("details.html", data=snapshot)


@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('user_id', None)
    session.pop('role', None)
    session.pop('name', None)
    return redirect(url_for('home'))


@app.route('/account')
def account():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT first_name, last_name, email, role
                    FROM users
                    WHERE id = %s
                    LIMIT 1
                """, (session['user_id'],))
                user = cursor.fetchone()

        if not user:
            session.clear()
            return redirect(url_for('login'))

        formatted_role = format_role(user["role"]) if user["role"] else "-"

        return render_template(
            'account.html',
            user=user,
            formatted_role=formatted_role
        )

    except psycopg2.Error:
        return redirect(url_for('login'))



if __name__ == "__main__":
    app.run(debug=True)
