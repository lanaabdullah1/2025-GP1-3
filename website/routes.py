from flask import render_template, request, redirect, url_for
from website.session import *
from model.query import *
import cv2
from flask import flash
from flask import send_file
import os
import re
import socket


def is_valid_camera_source(source, camera_type):

    source = source.strip()

    if camera_type == "ip":

        pattern = r"^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}:(\d{2,5})$"

        return re.match(pattern, source) is not None

    if camera_type == "usb":

        return source.isdigit()

    return False



def register_routes(app):

    @app.route("/")
    def index():
        if not is_login():
            return redirect(url_for("choose_user"))

        if is_admin():
            return redirect(url_for("users_list"))

        if is_operator():
            return redirect(url_for("operator_monitoring_default"))

        if is_field():
            return redirect(url_for("field_alerts"))

        return redirect(url_for("choose_user"))

    @app.route("/choose_user")
    def choose_user():
        return render_template("choose_user.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        role = request.args.get("role", "")

        if request.method == "GET":
            return render_template("login.html", role=role)

        email = request.form.get("email")
        email_pattern = r"^(?!.*\.\.)[A-Za-z0-9]+(?:[._%+-][A-Za-z0-9]+)*\.eyecept@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$"

        if not re.fullmatch(email_pattern, email):
            return redirect(url_for("login", role=role))
            


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

        email_pattern = r"^(?!.*\.\.)[A-Za-z0-9]+(?:[._%+-][A-Za-z0-9]+)*\.eyecept@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$"

        if not re.fullmatch(email_pattern, email):
            return redirect(url_for("user_add"))



        password = request.form.get("password")
        re_password = request.form.get("re_password")
        role = request.form.get("role")
        phone = request.form.get("phone") or None

        if role == "Security Field":
            password = "FIELD_OFFICER_NO_LOGIN_123!"
            re_password = password

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
                error="Email or phone number already exists",
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
        email_pattern = r"^(?!.*\.\.)[A-Za-z0-9]+(?:[._%+-][A-Za-z0-9]+)*\.eyecept@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$"
        if not re.fullmatch(email_pattern, email):
            return redirect(url_for("user_update", user_id=user_id))
                



        phone = request.form.get("phone") or None
        password = request.form.get("password")

        if user[4] == "Security Field":
            role = request.form.get("role")
        else:
            role = user[4]

        existing_user = get_user_by_email(email)
        if existing_user and existing_user[0] != user_id:
            return render_template(
                "user_update.html",
                user=user,
                error="Email already exists"
            )

        update_user(user_id, name, email, phone, role)
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

        old_password = request.form.get("old_password")

        password = request.form.get("password")

        re_password = request.form.get("re_password")

        user_id = get_user_id()

        user = get_user_by_id(user_id)

        if user[3] != hash_password(old_password):

            return render_template(
                "update_password.html",
                error="Current password is incorrect"
            )

        if password != re_password:

            return render_template(
                "update_password.html",
                error="Password not match"
            )

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

        if is_operator():
            phone = request.form.get("phone")
            update_profile(user_id, {"phone": phone})
            return render_template(
                "update_profile.html",
                user=get_user_by_id(user_id),
                success="Profile updated successfully"
            )
        name = request.form.get("name")
        if name is not None:
            data["name"] = name.strip()

        email = request.form.get("email")
        if email is not None:
            email = email.strip()

            email_pattern = r"^(?!.*\.\.)[A-Za-z0-9]+(?:[._%+-][A-Za-z0-9]+)*\.eyecept@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$"

            if not re.fullmatch(email_pattern, email):
                return render_template(
                    "update_profile.html",
                    user=user,
                    error="Email must contain _eyecept before @ like: ali_eyecept@gmail.com"
                )

            existing_user = get_user_by_email(email)
            if existing_user and existing_user[0] != user_id:
                return render_template(
                    "update_profile.html",
                    user=user,
                    error="Email already exists"
                )

            data["email"] = email

        
        phone = request.form.get("phone")
        if phone is not None:
            phone = phone.strip()
            data["phone"] = phone if phone else None

        try:
            if data:
                update_profile(user_id, data)

            updated_user = get_user_by_id(user_id)

            set_user_name(updated_user[1])
            set_role(updated_user[4])

            return render_template(
                "update_profile.html",
                user=updated_user,
                success="Profile updated successfully"
            )

        except Exception as e:
            print(type(e).__name__, e)
            return render_template(
                "update_profile.html",
                user=user,
                error="Phone number or email already exists"
            )






    @app.route("/forgot_password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "GET":
            return render_template("forgot_password.html")

        email = request.form.get("email")

        email_pattern = email_pattern = r"^(?!.*\.\.)[A-Za-z0-9]+(?:[._%+-][A-Za-z0-9]+)*\.eyecept@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$"

        if not re.fullmatch(email_pattern, email):
            return redirect(url_for("forgot_password"))
            

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
    def operator_monitoring_default():

        if not is_login() or not is_operator():
            return redirect(url_for("login"))

        cameras = get_all_active_cameras()

        if not cameras:
            return render_template(
                "operator_monitoring.html",
                cameras=[],
                camera=None
            )

        return redirect(url_for(
            "operator_monitoring",
            camera_id=cameras[0][0]
        ))
        
    @app.route("/operator_monitoring/<int:camera_id>")
    def operator_monitoring(camera_id):

        if not is_login() or not is_operator():
            return redirect(url_for("login"))

        cameras = get_all_active_cameras()

        camera = get_camera_by_id(camera_id)

        if not camera:
            return redirect(url_for(
                "operator_monitoring",
                camera_id=cameras[0][0]
            ))

        return render_template(
            "operator_monitoring.html",
            cameras=cameras,
            camera=camera
        )        
        
    @app.route("/video_feed/<int:camera_id>")
    def video_feed(camera_id):

        camera = get_camera_by_id(camera_id)

        if not camera:
            return "Camera not found"

        source = camera[2]
        camera_type = camera[3]

        if camera_type == "ip":
            if not source.startswith("http"):
                source = "http://" + source

            source += "/video"

        else:
            source = int(source)

        return Response(
            generate_frames(source, camera_id),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )        

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
                
        folder = "clips"

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

        mark_false_positive(alert_id)
        if image_path and os.path.exists(image_path):
         os.remove(image_path)

        return {"status": "ok"}
    
    @app.route("/cameras_list")
    def cameras_list():

        if not is_login() or not is_admin():
            return redirect(url_for("login"))

        cameras = get_all_cameras()

        return render_template(
            "cameras_list.html",
            cameras=cameras
        )    
        
    @app.route("/camera_add", methods=["GET", "POST"])
    def camera_add():

        if not is_login() or not is_admin():
            return redirect(url_for("login"))

        if request.method == "GET":
            return render_template("camera_add.html")

        name = request.form.get("name")
        source = request.form.get("source")
        camera_type = request.form.get("camera_type")


        if not is_valid_camera_source(source, camera_type):
            return render_template(
                "camera_add.html",
                error="Invalid source. IP cameras must be in this format: 192.168.1.5:8080. USB cameras must be a number."
            )

        create_camera(
            name,
            source,
            camera_type
        )

        return render_template(
            "camera_add.html",
            success="Camera added successfully"
        )        
        
    @app.route("/camera_update/<int:camera_id>", methods=["GET", "POST"])
    def camera_update(camera_id):

        if not is_login() or not is_admin():
            return redirect(url_for("login"))

        camera = get_camera_by_id(camera_id)

        if not camera:
            return redirect(url_for("cameras_list"))

        if request.method == "GET":
            return render_template(
                "camera_update.html",
                camera=camera
            )

        name = request.form.get("name")
        source = request.form.get("source")
        camera_type = request.form.get("camera_type")
        status = request.form.get("status")
        is_active = request.form.get("is_active")

        if not is_valid_camera_source(source, camera_type):
            return render_template(
                "camera_update.html",
                camera=camera,
                error="Invalid source. IP cameras must be in this format: 192.168.1.5:8080. USB cameras must be a number."
            )

        update_camera(
            camera_id,
            name,
            source,
            camera_type,
            status,
            is_active
        )

        return render_template(
            "camera_update.html",
            camera=get_camera_by_id(camera_id),
            success="Camera updated successfully"
        )        
        
        
    @app.route("/camera_delete/<int:camera_id>")
    def camera_delete(camera_id):

        if not is_login() or not is_admin():
            return redirect(url_for("login"))

        delete_camera(camera_id)

        return redirect(url_for("cameras_list"))        
    
   
    @app.route("/camera_status/<int:camera_id>")
    def camera_status(camera_id):

        camera = get_camera_by_id(camera_id)

        if not camera:
            return {"status": "fail"}

        source = camera[2]
        camera_type = camera[3]
        is_active = camera[5]

        if is_active == 0:
            return {"status": "disabled"}

        try:
            if camera_type == "ip":

                ip, port = source.split(":")
                port = int(port)

                # Fast check: is the phone camera app reachable?
                try:
                    socket.create_connection((ip, port), timeout=1).close()
                except:
                    return {"status": "fail"}

                video_source = "http://" + source + "/video"

            else:
                video_source = int(source)

            cap = cv2.VideoCapture(video_source)
            ok, frame = cap.read()
            cap.release()

            if ok and frame is not None:
                return {"status": "ok"}

            return {"status": "fail"}

        except:
            return {"status": "fail"}



    @app.route("/latest_alert")
    def latest_alert():

        if not is_login():
            return {"status": "fail"}

        alert = get_latest_alert()

        if not alert:
            return {"status": "empty"}

        return {
            "status": "ok",
            "id": alert[0],
            "level": alert[1],
            "threat_level": alert[2],
            "snapshot": alert[5],
            "reason": alert[7]
        }        
        
    @app.route("/clips/<path:filename>")
    def get_clip(filename):

        path = os.path.join(
            "clips",
            filename
        )

        return send_file(
            path,
            mimetype="video/x-msvideo"
        )