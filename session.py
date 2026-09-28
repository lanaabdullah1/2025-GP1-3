from flask import session


def set_login(is_login: bool):
    session["login"] = is_login


def is_login():
    return session.get("login", False)


def set_user_id(user_id):
    session["user_id"] = user_id


def get_user_id():
    return session.get("user_id", "")


def set_user_name(name):
    session["user_name"] = name


def get_user_name():
    return session.get("user_name", "")


def set_role(role):
    session["role"] = role


def get_role():
    return session.get("role", "")


def is_admin():
    return get_role() == "Admin"


def is_operator():
    return get_role() == "Security Operator"


def is_field():
    return get_role() == "Security Field"


def logout():
    session.clear()


def set_camera(source):
    session['camera_source'] = source


def get_camera():
    return session.get('camera_source', 0)