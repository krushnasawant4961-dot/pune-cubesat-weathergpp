
import os
import sqlite3
from datetime import datetime, timezone
from threading import Lock

import requests
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)

# ---------- CONFIGURATION ----------
DEVICE_TOKEN = os.getenv("CUBESAT_DEVICE_KEY", "")
DB_PATH = os.getenv("DATABASE_PATH", "weather.db")

PUNE_LAT = 18.5204
PUNE_LON = 73.8567

db_lock = Lock()

# ---------- DATABASE ----------
def init_db():
    with sqlite3.connect(DB_PATH, timeout=15) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                temperature REAL,
                humidity REAL,
                pressure_hpa REAL,
                bmp_temperature REAL,
                latitude REAL,
                longitude REAL,
                gps_valid INTEGER,
                extra TEXT
            )
        """)
        conn.commit()


def get_latest():
    with sqlite3.connect(DB_PATH, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("""
            SELECT * FROM telemetry
            ORDER BY id DESC LIMIT 1
        """).fetchone()
        return dict(row) if row else None


# ---------- AUTHENTICATION ----------
def authorized():
    # Fail closed if the environment variable is missing.
    if not DEVICE_TOKEN:
        return False

    supplied = request.headers.get("X-Device-Token", "")
    return supplied == DEVICE_TOKEN


# ---------- HEALTH ----------
@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "Pune CubeSat Weather"
    })


# ---------- RECEIVE ESP32 TELEMETRY ----------
@app.route("/api/telemetry", methods=["POST"])
def receive_telemetry():
    if not DEVICE_TOKEN:
        app.logger.error("CUBESAT_DEVICE_KEY is not configured")
        return jsonify({
            "error": "Device authentication is not configured"
        }), 500

    if not authorized():
        return jsonify({"error": "Unauthorized device"}), 401

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Expected a JSON object"}), 400

    def read_number(key, minimum=None, maximum=None):
        value = data.get(key)

        if value is None or isinstance(value, bool):
            return None

        try:
            number = float(value)
        except (TypeError, ValueError):
            return None

        if not __import__("math").isfinite(number):
            return None

        if minimum is not None and number < minimum:
            return None

        if maximum is not None and number > maximum:
            return None

        return number

    temperature = read_number("temperature", -80, 100)
    humidity = read_number("humidity", 0, 100)
    pressure = read_number("pressure_hpa", 100, 1200)
    bmp_temperature = read_number("bmp_temperature", -80, 100)
    latitude = read_number("latitude", -90, 90)
    longitude = read_number("longitude", -180, 180)

    gps_valid = data.get("gps_valid") is True

    if temperature is None or humidity is None:
        return jsonify({
            "error": "Valid temperature and humidity are required"
        }), 400

    if gps_valid and (latitude is None or longitude is None):
        return jsonify({
            "error": "Valid GPS coordinates are required when gps_valid is true"
        }), 400

    # Keep invalid GPS coordinates as NULL, not (0, 0).
    if not gps_valid:
        latitude = None
        longitude = None

    import json

    timestamp = datetime.now(timezone.utc).isoformat()

    with db_lock:
        with sqlite3.connect(DB_PATH, timeout=15) as conn:
            conn.execute("""
                INSERT INTO telemetry (
                    created_at, temperature, humidity,
                    pressure_hpa, bmp_temperature,
                    latitude, longitude, gps_valid, extra
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                timestamp,
                temperature,
                humidity,
                pressure,
                bmp_temperature,
                latitude,
                longitude,
                int(gps_valid),
                json.dumps(data)
            ))
            conn.commit()

    app.logger.info("Accepted ESP32 telemetry at %s", timestamp)

    return jsonify({
        "ok": True,
        "message": "Telemetry accepted",
        "received_at": timestamp
    }), 200


# ---------- WEATHER DATA ----------
def get_weather():
    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": PUNE_LAT,
        "longitude": PUNE_LON,
        "current": (
            "temperature_2m,relative_humidity_2m,"
            "precipitation,surface_pressure,cloud_cover"
        ),
        "hourly": (
            "temperature_2m,relative_humidity_2m,"
            "precipitation,surface_pressure,cloud_cover"
        ),
        "forecast_days": 2,
        "timezone": "Asia/Kolkata"
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        app.logger.warning("Weather request failed: %s", exc)
        return {"error": "Weather service temporarily unavailable"}


# ---------- DASHBOARD API ----------
@app.route("/api/dashboard")
def dashboard_api():
    latest = get_latest()

    with sqlite3.connect(DB_PATH, timeout=15) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM telemetry"
        ).fetchone()[0]

    return jsonify({
        "ok": True,
        "telemetry": latest,
        "count": count
    })


@app.route("/api/history")
def history_api():
    limit = request.args.get("limit", default=50, type=int)
    limit = max(1, min(limit or 50, 500))

    with sqlite3.connect(DB_PATH, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT created_at, temperature, humidity,
                   pressure_hpa, latitude, longitude, gps_valid
            FROM telemetry
            ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()

    return jsonify({
        "count": len(rows),
        "history": [dict(row) for row in rows]
    })


@app.route("/api/weather")
def weather_api():
    return jsonify(get_weather())


# ---------- BASIC WEB DASHBOARD ----------
PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="15">
<title>CubeSat Mission Dashboard</title>
<style>
body{margin:0;background:#101827;color:#edf3ff;
font-family:Arial,sans-serif}
header{padding:22px;background:#19263c}
main{max-width:950px;margin:auto;padding:16px}
.grid{display:grid;grid-template-columns:
repeat(auto-fit,minmax(180px,1fr));gap:12px}
.card{background:#1c2b43;padding:18px;border-radius:14px}
.label{color:#b8c8e4;font-size:14px}
.value{font-size:25px;font-weight:bold;margin-top:10px;
overflow-wrap:anywhere}
a{color:#8ecbff}
#status{padding:12px;margin-bottom:14px;background:#243653;
border-radius:10px}
</style>
</head>
<body>
<header>
<h2>CubeSat Mission Dashboard</h2>
<p>ESP32 telemetry · Environmental monitoring · GPS</p>
</header>
<main>
<div id="status">Loading telemetry...</div>
<div class="grid">
<div class="card"><div class="label">Temperature</div>
<div class="value" id="temp">--</div></div>
<div class="card"><div class="label">Humidity</div>
<div class="value" id="hum">--</div></div>
<div class="card"><div class="label">Pressure</div>
<div class="value" id="pres">--</div></div>
<div class="card"><div class="label">BMP Temperature</div>
<div class="value" id="bmp">--</div></div>
<div class="card"><div class="label">GPS Latitude</div>
<div class="value" id="lat">--</div></div>
<div class="card"><div class="label">GPS Longitude</div>
<div class="value" id="lon">--</div></div>
</div>
<p id="updated"></p>
<p><a href="/api/dashboard">Dashboard JSON</a> ·
<a href="/api/history">Telemetry history</a> ·
<a href="/api/weather">Pune weather data</a></p>
</main>
<script>
function display(id,value,unit=""){
  document.getElementById(id).textContent =
    value === null || value === undefined ? "--" : value + unit;
}
async function update(){
  try{
    const response = await fetch("/api/dashboard",{cache:"no-store"});
    const data = await response.json();
    const t = data.telemetry;
    document.getElementById("status").textContent =
      t ? "Telemetry received · Records: " + data.count
        : "Waiting for the first ESP32 reading";
    display("temp",t && t.temperature," °C");
    display("hum",t && t.humidity," %");
    display("pres",t && t.pressure_hpa," hPa");
    display("bmp",t && t.bmp_temperature," °C");
    display("lat",t && t.latitude);
    display("lon",t && t.longitude);
    document.getElementById("updated").textContent =
      t ? "Last received (UTC): " + t.created_at : "";
  }catch(error){
    document.getElementById("status").textContent =
      "Unable to load dashboard data";
  }
}
update();
setInterval(update,15000);
</script>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(PAGE)


# ---------- STARTUP ----------
init_db()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
 
