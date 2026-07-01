from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import config

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not config.ADMIN_PASSWORD:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        if request.form.get("heslo") == config.ADMIN_PASSWORD:
            session["authed"] = True
            session.permanent = True
            return redirect(request.args.get("next") or url_for("dashboard.index"))
        flash("Špatné heslo.", "error")
    return render_template("login.html")


@bp.route("/kdo", methods=["GET", "POST"])
def choose_profil():
    """After login, pick who is working. The choice is kept in the session and
    auto-attributed to everything added, so no per-form picker is needed."""
    if request.method == "POST":
        p = (request.form.get("profil") or "").strip()
        if p in config.PROFILY:
            session["profil"] = p
            session.permanent = True
            return redirect(request.args.get("next") or url_for("dashboard.index"))
        flash("Vyber profil.", "error")
    return render_template("kdo.html", next=request.args.get("next", ""))


@bp.post("/logout")
def logout():
    session.pop("authed", None)
    session.pop("profil", None)
    return redirect(url_for("auth.login"))
