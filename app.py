from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3
import os
from werkzeug.security import check_password_hash

import requests
import os
import time
import statistics
import math

from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = "super_secret_key"

DISCOGS_TOKEN = os.getenv("DISCOGS_TOKEN")
EXCHANGE_RATE = None
EXCHANGE_RATE_TIMESTAMP = 0

HEADERS = {
    "User-Agent": "VinylApp/1.0",
    "Authorization": f"Discogs token={DISCOGS_TOKEN}"
}

# 🔌 Database connection
def get_db():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(BASE_DIR, "database", "users.db")
    return sqlite3.connect(db_path)

@app.before_request
def require_login():
    allowed_routes = ["login", "static"]  # routes that DON'T require login

    if request.endpoint not in allowed_routes and "user" not in session:
        return redirect(url_for("login"))
    
# 🔐 Login route
@app.route("/", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for("dashboard"))

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

# -------------------------------
# 🔹 Exchange Rate
# -------------------------------
def get_exchange_rate():
    global EXCHANGE_RATE, EXCHANGE_RATE_TIMESTAMP

    if EXCHANGE_RATE and (time.time() - EXCHANGE_RATE_TIMESTAMP < 3600):
        return EXCHANGE_RATE

    try:
        url = "https://open.er-api.com/v6/latest/USD"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
       
        data = response.json()
        EXCHANGE_RATE = data["rates"]["ZAR"]

        EXCHANGE_RATE_TIMESTAMP = time.time()

    except Exception as e:
        print("Exchange rate error:", e)
        return EXCHANGE_RATE or 18  # fallback

    return EXCHANGE_RATE


# -------------------------------
# 🔹 Home Route
# -------------------------------
@app.route("/vinyl", methods=["GET", "POST"])
def index():
    results = []

    if request.method == "POST":
        query = request.form.get("search")

        url = "https://api.discogs.com/database/search"

        params = {
            "q": query,
            "type": "release",
            "token": DISCOGS_TOKEN
        }

        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=5)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print("Search error:", e)
            data = {}

        for item in data.get("results", []):
            if "Vinyl" not in item.get("format", []):
                continue

            results.append({
                "id": item.get("id"),
                "title": item.get("title"),
                "thumb": item.get("cover_image")
            })

            if len(results) >= 30:
                break

    return render_template("vinyl.html", results=results)


# -------------------------------
# 🔹 Release Detail Route
# -------------------------------
@app.route("/release/<int:release_id>")
def release_detail(release_id):

    params = {"token": DISCOGS_TOKEN}

    # -------------------------------
    # 🔹 Release Details
    # -------------------------------
    try:
        response = requests.get(
            f"https://api.discogs.com/releases/{release_id}",
            params=params,
            headers=HEADERS,
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print("Release error:", e)
        data = {}

    usd_to_zar = get_exchange_rate()
    lowest_price = data.get("lowest_price")

    # -------------------------------
    # 🔹 Price Suggestions + Marketplace
    # -------------------------------
    price_data = {}
    market_data = {}

    try:
        # 1️⃣ Try master_id first
        market_response = requests.get(
            "https://api.discogs.com/marketplace/search",
            params={"release": release_id},
            headers=HEADERS,
            timeout=10
        )
        if market_response.status_code == 404:
            # ✅ Treat as "no listings", NOT an error
            market_data = {"results": []}

        else:        
            market_response.raise_for_status()
            market_data = market_response.json()

    except requests.exceptions.RequestException:
        market_data = {"results": []}
        results = market_data.get("results", [])

        # 2️⃣ Fallback to release_id if empty
        if not results:
            print("No master listings — trying release_id")

            market_response = requests.get(
                "https://api.discogs.com/marketplace/search",
                params={"release_id": release_id},
                headers=HEADERS,
                timeout=5
            )
            market_response.raise_for_status()
            market_data = market_response.json()

            print(market_response.status_code)
            print(market_response.text[:200])

            print("Release fallback count:", len(market_data.get("results", [])))

    except Exception as e:
        print("Marketplace error:", e)

    # -------------------------------
    # 🔹 Process Price Suggestions
    # -------------------------------
    price_suggestions = [
        {
            "condition": condition,
            "usd": info.get("value"),
            "zar": round(info.get("value") * usd_to_zar, 2)
        }
        for condition, info in price_data.items()
        if info.get("value") is not None
    ]

    price_suggestions.sort(key=lambda x: x["usd"], reverse=True)

    # -------------------------------
    # 🔹 Process Marketplace Data
    # -------------------------------
    prices = [
        item.get("price", {}).get("value")
        for item in market_data.get("results", [])
        if item.get("price", {}).get("value") is not None
    ]

    filtered_prices = prices

    if len(prices) >= 5:
        median_val = statistics.median(prices)

        # Remove anything less than 50% of median
        filtered_prices = [
            p for p in prices if p >= (0.5 * median_val)
        ]
        
    market_low = min(filtered_prices) if filtered_prices else None
    market_high = max(filtered_prices) if filtered_prices else None

    market_median = statistics.median(filtered_prices) if filtered_prices else None

    if prices:
        sorted_prices = sorted(prices)
        market_median = sorted_prices[len(sorted_prices) // 2]

    market_low_count = sum(1 for p in prices if p == market_low) if market_low else 0

    # -------------------------------
    # 🔹 Fallback Valuation Logic
    # -------------------------------
    fallback_price = None
    fallback_source = None

    if market_median is not None:
        fallback_price = market_median
        fallback_source = "Marketplace Median"

    elif price_suggestions:
        preferred = next(
            (p for p in price_suggestions if "VG+" in p["condition"] or "NM" in p["condition"]),
            None
        )

        if preferred:
            fallback_price = preferred["usd"]
            fallback_source = f"Estimated ({preferred['condition']})"
        else:
            fallback_price = price_suggestions[0]["usd"]
            fallback_source = f"Estimated ({price_suggestions[0]['condition']})"

    elif lowest_price is not None:
        fallback_price = lowest_price
        fallback_source = "Discogs Lowest"

    fallback_price_zar = round(fallback_price * usd_to_zar, 2) if fallback_price else None

    recommended_value_zar = None
    recommended_price_zar = None

    if fallback_price_zar is not None:

        # 🔹 Round to nearest 10 (ZAR now)
        recommended_value_zar = math.floor((fallback_price_zar + 5) / 10) * 10

        # 🔹 Take 70%
        raw_price = recommended_value_zar * 0.7

        # 🔹 Round again (same rule)
        recommended_price_zar = math.floor((raw_price + 5) / 10) * 10
        
    # -------------------------------
    # 🔹 Image Handling
    # -------------------------------
    images = data.get("images") or []
    cover = images[0]["uri"] if images else None

    # -------------------------------
    # 🔹 Final Object
    # -------------------------------
    release = {
        # 🎵 Basic Info
        "title": data.get("title"),
        "artist": data.get("artists", [{}])[0].get("name"),
        "year": data.get("year"),
        "country": data.get("country"),

        # 🖼️ Images
        "cover": cover,
        "thumb": data.get("cover_image"),

        # 🎧 Metadata
        "genres": ", ".join(data.get("genres", [])),
        "styles": ", ".join(data.get("styles", [])),
        "formats": ", ".join(data.get("formats", [{}])[0].get("descriptions", [])),

        # 💿 Tracklist
        "tracklist": [
            f"{t.get('position')} - {t.get('title')} ({t.get('duration')})"
            for t in data.get("tracklist", [])
        ],

        # 🏷️ Label Info
        "label": data.get("labels", [{}])[0].get("name"),
        "catno": data.get("labels", [{}])[0].get("catno"),

        # 📊 Community
        "rating": data.get("community", {}).get("rating", {}).get("average"),
        "rating_count": data.get("community", {}).get("rating", {}).get("count"),
        "have": data.get("community", {}).get("have"),
        "want": data.get("community", {}).get("want"),

        # 💰 Pricing
        "lowest_price_usd": lowest_price,
        "lowest_price_zar": round(lowest_price * usd_to_zar, 2) if lowest_price else None,
        "exchange_rate": usd_to_zar,

        # 🌍 Marketplace Stats
        "num_for_sale": data.get("num_for_sale"),
        "market_low_zar": round(market_low * usd_to_zar, 2) if market_low else None,
        "market_median_zar": round(market_median * usd_to_zar, 2) if market_median else None,
        "market_high_zar": round(market_high * usd_to_zar, 2) if market_high else None,

        # 💡 Final Value
        "fallback_price_zar": fallback_price_zar,
        "fallback_source": fallback_source,

        # 🔗 Links
        "discogs_url": data.get("uri"),
        "video": data.get("videos", [{}])[0].get("uri") if data.get("videos") else None,

        "recommended_value_zar": recommended_value_zar,
        "recommended_price_zar": recommended_price_zar,

    }

    return render_template("detail.html", release=release)


if __name__ == "__main__":
    app.run(debug=True)

if __name__ == "__main__":
    app.run(debug=True)