from flask import Flask
from website.routes import register_routes
from website.session import *

app = Flask(
    __name__, template_folder="website", static_folder="website", static_url_path=""
)

app.secret_key = "super-secret-key"


@app.context_processor
def inject_user():
    return dict(
        is_login=is_login(),
        user_id=get_user_id(),
        user_name=get_user_name(),
        role=get_role(),
        is_admin=is_admin(),
        is_operator=is_operator(),
        is_field=is_field(),
    )


register_routes(app)


if __name__ == "__main__":
    app.run(debug=True)
