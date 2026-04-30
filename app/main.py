import logging
import os
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

    # Versão do app — usa hash do commit Git (injetado pelo Render)
    # Fallback para "dev" em ambiente local
    commit = os.environ.get("RENDER_GIT_COMMIT", "")
    app.config["APP_VERSION"] = commit[:7] if commit else "dev"

    init_db()
    app.register_blueprint(bp)

    # Injeta versão em todos os templates
    @app.context_processor
    def inject_version():
        return {"app_version": app.config["APP_VERSION"]}

    return app
