import logging
from flask import Flask
from app.database import init_db
from app.routes import bp


def create_app():
    # Configura logging para aparecer no terminal
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["JSON_ENSURE_ASCII"] = False

    init_db()
    app.register_blueprint(bp)

    return app
