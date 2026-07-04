import hmac

from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import config

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not config.ADMIN_PASSWORD:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        if hmac.compare_digest(request.form.get("heslo", ""), config.ADMIN_PASSWORD):
            session["authed"] = True
            session.permanent = True
            return redirect(request.args.get("next") or url_for("dashboard.index"))
        flash("Špatné heslo.", "error")
    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.pop("authed", None)
    return redirect(url_for("auth.login"))
