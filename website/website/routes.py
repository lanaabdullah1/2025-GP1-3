from flask import render_template, request, redirect, url_for
from website.session import *
from model.query import *
import cv2
from flask import flash
from flask import send_file
import os

def register_routes(app):

    @app.route("/")
    def index():
        if not is_login():
            return redirect(url_for("choose_user"))

        if is_admin():
            return redirect(url_for("users_list"))

        if is_operator():
            return redirect(url_for("operator_monitoring"))

        if is_field():
            return redirect(url_for("field_alerts"))

        return redirect(url_for("choose_user"))

    @app.route("/choose_user")
    def choose_user():
        return render_template("choose_user.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if is_login():
            return redirect(url_for("index"))

        role = request.args.get("role", "")

        if request.method == "GET":
            return render_template("login.html", role=role)

        email = request.form.get("email")
        password = request.form.get("password")

        user = verify_user(email, password,role)

        if not user:
            return render_template(
                "login.html", error="Wrong email or password", role=role, email=email
            )

        set_login(True)
        set_user_id(user[0])
        set_user_name(user[1])
        set_role(user[4])

        return redirect(url_for("index"))

    @app.route("/logout")
    def logout_route():
        logout()
        return redirect(url_for("choose_user"))

    # =========================
    # ADMIN
    # =========================

    @app.route("/users_list")
    def users_list():
        if not is_login() or not is_admin():
            return redirect(url_for("login"))

        users = get_all_users()
        return render_template("users_list.html", users=users)

    @app.route("/user_add", methods=["GET", "POST"])
    def user_add():

        if not is_login() or not is_admin():
            return redirect(url_for("login"))

        if request.method == "GET":
            return render_template("user_add.html")

        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")
        re_password = request.form.get("re_password")
        role = request.form.get("role")
        phone = request.form.get("phone") or None

        if password != re_password:
            return render_template(
                "user_add.html",
                error="Password not match",
                name=name,
                email=email,
                role=role,
                phone=phone,
            )

        success = create_user(name, email, password, role, phone)

        if not success:
            return render_template(
                "user_add.html",
                error="Email already exists",
                name=name,
                email=email,
                role=role,
                phone=phone,
            )

        return render_template("user_add.html", success="User added successfully")


    @app.route("/user_update/<int:user_id>", methods=["GET", "POST"])
    def user_update(user_id):

        if not is_login() or not is_admin():
            return redirect(url_for("login"))

        user = get_user_by_id(user_id)

        if not user:
            return redirect(url_for("users_list"))

        if request.method == "GET":
            return render_template("user_update.html", user=user)

        name = request.form.get("name")
        email = request.form.get("email")
        phone = request.form.get("phone") or None
        password = request.form.get("password")

        # optional: check if email already belongs to another user
        existing_user = get_user_by_email(email)
        if existing_user and existing_user[0] != user_id:
            return render_template(
                "user_update.html",
                user=user,
                error="Email already exists"
            )

        update_user(user_id, name, email, phone)

        if password and password.strip():
            update_password(user_id, password)

        return render_template(
            "user_update.html",
            user=get_user_by_id(user_id),
            success="User updated successfully"
        )




    @app.route("/user_delete/<int:user_id>")
    def user_delete(user_id):
        if not is_login() or not is_admin():
            return redirect(url_for("login"))

        delete_user(user_id)
        return redirect(url_for("users_list"))
    
    
    @app.route("/update_password", methods=["GET", "POST"])
    def update_password_route():

        if not is_login():
            return redirect(url_for("login"))

        if request.method == "GET":
            return render_template("update_password.html")

        password = request.form.get("password")
        re_password = request.form.get("re_password")

        if password != re_password:
            return render_template(
                "update_password.html",
                error="Password not match"
            )

        user_id = get_user_id()

        update_password(user_id, password)

        return render_template(
            "update_password.html",
            success="Password updated successfully"
        )

    @app.route("/update_profile", methods=["GET", "POST"])
    def update_profile_route():

        if not is_login():
            return redirect(url_for("login"))

        user_id = get_user_id()
        user = get_user_by_id(user_id)

        if request.method == "GET":
            return render_template("update_profile.html", user=user)

        data = {}

        if request.form.get("name"):
            data["name"] = request.form.get("name")

        if request.form.get("email"):
            data["email"] = request.form.get("email")

        if request.form.get("phone"):
            data["phone"] = request.form.get("phone")

        if data:
            update_profile(user_id, data)

        return render_template(
            "update_profile.html",
            user=get_user_by_id(user_id),
            success="Profile updated successfully"
        )

    @app.route("/forgot_password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "GET":
            return render_template("forgot_password.html")

        email = request.form.get("email")
        user = get_user_by_email(email)

        if not user:
            return render_template("forgot_password.html", error="Email not found")

        phone = user[5]

        code = create_reset_code(user[0])

        send_email(email, code)
        if phone:
          phone = normalize_saudi_number(phone)   
          #send_sms(phone, code)

        return render_template(
        "verify_code.html",
        user_id=user[0],
        success="Code sent to your email"
        )
    
    def normalize_saudi_number(phone: str) -> str:
        phone = phone.strip()

        if phone.startswith("+966"):
            return phone

        if phone.startswith("0"):
            return "+966" + phone[1:]

        # fallback (assume missing +)
        if phone.startswith("966"):
            return "+" + phone

        return phone
    @app.route("/verify_code/<int:user_id>", methods=["GET", "POST"])
    def verify_code(user_id):
        if request.method == "GET":
            return render_template("verify_code.html")

        code = request.form.get("code")

        data = get_reset_code(user_id, code)

        if not data:
            return render_template("verify_code.html", error="Invalid code")

        if float(data[3]) < datetime.utcnow().timestamp():
            return render_template("verify_code.html", error="Code expired")

        return redirect(url_for("new_password", user_id=user_id))

    @app.route("/new_password/<int:user_id>", methods=["GET", "POST"])
    def new_password(user_id):
        if request.method == "GET":
            return render_template("new_password.html")
        password = request.form.get("password")
        re_password = request.form.get("re_password")
        if password != re_password:
            return render_template("new_password.html", error="Password not match")
        update_password(user_id, password)
        delete_user_tokens(user_id)
        flash("Password changed successfully", "success")
        return redirect(url_for("choose_user"))
    # =========================
    # OPERATOR
    # =========================

    @app.route("/operator_monitoring")
    def operator_monitoring():
        if not is_login() or not is_operator():
            return redirect(url_for("login"))

        alerts = get_alerts()
        return render_template("operator_monitoring.html", alerts=alerts)
    
    @app.route("/operator_alerts")
    def operator_alerts():
        if not is_login() or not is_operator():
            return redirect(url_for("login"))

        alerts = get_alerts()

        return render_template("operator_alerts.html", alerts=alerts)

    # =========================
    # FIELD
    # =========================

    @app.route("/field_alerts")
    def field_alerts():
        if not is_login() or not is_field():
            return redirect(url_for("login"))

        return render_template("field_alerts.html")

    # =========================
    # PASSWORD RESET
    # =========================

    @app.route("/reset_password", methods=["GET", "POST"])
    def reset_password():
        if request.method == "GET":
            return render_template("reset_password.html")

        token = generate_reset_token(request.form.get("email"))
        return render_template("reset_password.html", token=token)

    @app.route("/set_new_password/<token>", methods=["GET", "POST"])
    def set_new_password(token):
        if request.method == "GET":
            return render_template("set_new_password.html", token=token)

        reset_password(token, request.form.get("password"))
        return redirect(url_for("login"))
        
    from camera import generate_frames, set_roi
    from flask import render_template, request, redirect, url_for, Response, jsonify
    @app.route("/set_camera", methods=["POST"])
    def set_camera_route():
        data = request.json
        cam_type = data.get("type")
        
        if cam_type == "usb":
            index = int(data.get("index"))

            if index == 0:
                return {"error": "Laptop camera disabled"}

            source = index

        else:
            ip = data.get("ip")

            if not ip.startswith("http"):
                ip = "http://" + ip

            source = ip + "/video"

        set_camera(source)

        return {"status": "ok"}


    @app.route("/video_feed")
    def video_feed():
        source = get_camera()

        if not source:
            return "No camera selected"

        return Response(
            generate_frames(source),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )


    @app.route("/camera_status")
    def camera_status():
        source = get_camera()

        cap = cv2.VideoCapture(source)
        ok, _ = cap.read()
        cap.release()

        return {"status": "ok" if ok else "fail"}
    
    @app.route("/set_roi", methods=["POST"])
    def set_roi_route():
        data = request.json
        set_roi(data["x1"], data["y1"], data["x2"], data["y2"])
        return {"status": "ok"}

    import camera
    @app.route("/reset_roi", methods=["POST"])
    def reset_roi_route():
        camera.reset_roi()
        return {"status": "ok"}

    @app.route("/snapshot/<path:filename>")
    def get_snapshot(filename):
        path = os.path.join("snapshots", filename)
        return send_file(path)
    
    @app.route("/clear_alerts", methods=["POST"])
    def clear_alerts():
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM sms_logs")
        cursor.execute("DELETE FROM alerts")
        

        conn.commit()
        conn.close()

        folder = "snapshots"

        if os.path.exists(folder):
            for f in os.listdir(folder):
                try:
                    os.remove(os.path.join(folder, f))
                except:
                    pass

        return {"status": "cleared"}
    
    @app.route("/false_positive", methods=["POST"])
    def false_positive():
        data = request.json
        alert_id = data.get("alert_id")

        alert = get_alert(alert_id)

        if not alert:
            return {"error": "not found"}

        image_path = alert[2]
        users = get_security_fields()

        for user_id, phone in users:
            if phone:
                #send_sms(phone, "⚠ False alarm")
                log_sms(alert_id, user_id, "False alarm")

        delete_alert(alert_id)
        if image_path and os.path.exists(image_path):
         os.remove(image_path)

        return {"status": "ok"}