from flask import Flask, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
import config
import db


def create_app():
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config["SECRET_KEY"] = config.SECRET_KEY
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # always revalidate static (no stale CSS/JS)

    app.teardown_appcontext(db.close_db)

    @app.before_request
    def _require_login():
        from flask import request, session, redirect, url_for
        if not config.ADMIN_PASSWORD:
            return  # gate disabled (local/dev — no password configured)
        if request.path in ("/healthz", "/health", "/login") or request.endpoint == "static":
            return
        if request.path.startswith("/api/"):
            return  # server-to-server: key auth (_require_api_key), not the session gate
        if not session.get("authed"):
            return redirect(url_for("auth.login", next=request.path))

    @app.before_request
    def _require_api_key():
        from flask import request, jsonify
        if not request.path.startswith("/api/"):
            return
        if not config.INTEGRATION_API_KEY:
            return  # no key configured → open (local/dev; keeps keyless API tests green)
        if request.headers.get("X-Api-Key") != config.INTEGRATION_API_KEY:
            return jsonify(error="unauthorized"), 401

    @app.before_request
    def _auto_backup():
        from flask import request
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            db.backup_db()

    @app.context_processor
    def _nav_context():
        from flask import session
        from repositories import firmy_repo, typy_repo, prichozi_repo
        conn = db.get_db()
        authed = (not config.ADMIN_PASSWORD) or bool(session.get("authed"))
        return {
            "nav_firmy": firmy_repo.list_all(conn, only_active=True),
            "nav_typy": typy_repo.list_active(conn),
            "authed": authed,
            "nav_prichozi_count": prichozi_repo.count_pending(conn) if authed else 0,
            "profily": config.PROFILY,
        }

    from routes.dashboard import bp as dashboard_bp
    app.register_blueprint(dashboard_bp)
    from routes.ukony import bp as ukony_bp
    app.register_blueprint(ukony_bp)
    from routes.firmy import bp as firmy_bp
    app.register_blueprint(firmy_bp)
    from routes.nastaveni import bp as nastaveni_bp
    app.register_blueprint(nastaveni_bp)
    from routes.export import bp as export_bp
    app.register_blueprint(export_bp)
    from routes.api import bp as api_bp
    app.register_blueprint(api_bp)
    from routes.prichozi import bp as prichozi_bp
    app.register_blueprint(prichozi_bp)
    from routes.auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.get("/healthz")
    def healthz():
        return "ok", 200

    return app


# WSGI entrypoint for gunicorn (`gunicorn app:application`).
application = create_app()

if __name__ == "__main__":
    application.run(host="127.0.0.1", port=config.PORT, debug=True)
