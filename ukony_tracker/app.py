from flask import Flask, jsonify
import config
import db


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "ukony-tracker-local"  # local single-user app; only used for flash messages

    app.teardown_appcontext(db.close_db)

    @app.before_request
    def _auto_backup():
        from flask import request
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            db.backup_db()  # throttled; protects every create/edit/delete before it runs

    @app.context_processor
    def _nav_context():
        from repositories import firmy_repo, typy_repo
        conn = db.get_db()
        return {
            "nav_firmy": firmy_repo.list_all(conn, only_active=True),
            "nav_typy": typy_repo.list_active(conn),
        }

    from routes.dashboard import bp as dashboard_bp
    app.register_blueprint(dashboard_bp)

    from routes.ukony import bp as ukony_bp
    app.register_blueprint(ukony_bp)

    from routes.firmy import bp as firmy_bp
    app.register_blueprint(firmy_bp)

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=config.PORT, debug=True)
