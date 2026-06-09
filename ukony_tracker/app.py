from flask import Flask, jsonify

def create_app():
    app = Flask(__name__)
    @app.get("/health")
    def health():
        return jsonify(status="ok")
    return app

if __name__ == "__main__":
    import config
    create_app().run(host="127.0.0.1", port=config.PORT, debug=True)
