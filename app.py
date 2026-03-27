from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3
import os
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = "super_secret_key"


# 🔌 Database connection
def get_db():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(BASE_DIR, "database", "users.db")
    return sqlite3.connect(db_path)


# 🔐 Login route
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()
        c = conn.cursor()

        c.execute("SELECT password FROM users WHERE username=?", (username,))
        result = c.fetchone()

        conn.close()

        if result:
            stored_hash = result[0]

            if check_password_hash(stored_hash, password):
                session["user"] = username
                return redirect(url_for("dashboard"))
            else:
                return "❌ Invalid password"
        else:
            return "❌ User not found"

    return render_template("login.html")


# 📊 Dashboard
@app.route("/dashboard")
def dashboard():
    if "user" in session:
        return render_template("dashboard.html", user=session["user"])
    return redirect(url_for("login"))


# 🚪 Logout
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)