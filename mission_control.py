
import os
import time
import json
import sqlite3
import threading
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request, render_template_string, Response

app = Flask(__name__)

PUNE_LAT = 18.5204
PUNE_LON = 73.8567
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

DB_PATH = os.getenv("DATABASE_PATH", "weather.db")
DEVICE_TOKEN = os.getenv("DEVICE_TOKEN", "change-this-secret-token")

db_lock = threading.Lock()
collector_started = False

PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pune Weather | CubeSat Mission Control</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<link rel="stylesheet"
 href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root{font-family:Arial,sans-serif;color:#172b4d;background:#eef4fb}
*{box-sizing:border-box}
body{margin:0}
header{background:linear-gradient(120deg,#164e9a,#438de7);color:white;padding:24px 18px}
header h1{margin:0 0 8px;font-size:27px}
header p{margin:0;color:#e2edff}
main{max-width:1100px;margin:auto;padding:16px}
.card{background:white;border-radius:20px;padding:18px;margin-bottom:16px;
box-shadow:0 5px 20px #173c6410}
.hero{background:linear-gradient(135deg,#dbeafe,#f8fbff)}
.label{font-size:13px;color:#60718b}
.big{font-size:48px;font-weight:700;margin:8px 0}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.metric{background:#f5f8fc;padding:15px;border-radius:15px}
.metric strong{display:block;font-size:23px;margin-top:8px}
h2{font-size:19px;margin-top:0}
.status{font-size:13px;color:#45617e}
#map{height:280px;border-radius:15px}
canvas{max-height:300px}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{text-align:left;padding:10px;border-bottom:1px solid #e6edf5}
.table-wrap{overflow-x:auto}
button{background:#1769d2;color:white;border:0;border-radius:10px;
padding:11px 15px;font-weight:bold}
a{color:#1769d2}
footer{text-align:center;color:#687b94;padding:20px;font-size:12px}
@media(max-width:650px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}
.big{font-size:42px}header h1{font-size:23px}}
</style>
</head>
<body>
<header>
<h1>🌤️ Pune Weather & CubeSat</h1>
<p>Live weather monitoring · Experimental forecast · Mission telemetry</p>
</header>
<main>
<section class="card hero">
<div class="label">PUNE, MAHARASHTRA · LIVE WEATHER</div>
<div style="display:flex;align-items:center;gap:18px;flex-wrap:wrap">
<div id="symbol" style="font-size:60px">🌤️</div>
<div><div class="big" id="temp">--°C</div>
<div id="condition">Loading weather...</div>
<div class="status" id="updated">Connecting to weather service...</div></div>
</div>
</section>

<section class="grid">
<div class="card metric"><span class="label">Humidity</span><strong id="humidity">--%</strong></div>
<div class="card metric"><span class="label">Rainfall</span><strong id="rain">-- mm</strong></div>
<div class="card metric"><span class="label">Pressure</span><strong id="pressure">-- hPa</strong></div>
<div class="card metric"><span class="label">Cloud cover</span><strong id="cloud">--%</strong></div>
<div class="card metric"><span class="label">Wind speed</span><strong id="wind">-- km/h</strong></div>
<div class="card metric"><span class="label">2-hour estimate</span><strong id="estimate">--°C</strong></div>
<div class="card metric"><span class="label">Weather records</span><strong id="count">0</strong></div>
<div class="card metric"><span class="label">Collector</span><strong id="collector" style="font-size:16px">Checking</strong></div>
</section>

<section class="card">
<h2>📈 Temperature history</h2>
<p class="status">Stored observations collected by the server.</p>
<canvas id="chart"></canvas>
</section>

<section class="card">
<h2>🛰️ CubeSat telemetry</h2>
<p class="status">This section is separate from public weather data. It updates when your ESP32 sends telemetry.</p>
<div class="grid">
<div class="metric"><span class="label">Satellite temperature</span><strong id="sattemp">--</strong></div>
<div class="metric"><span class="label">Satellite humidity</span><strong id="sathum">--</strong></div>
<div class="metric"><span class="label">GPS latitude</span><strong id="lat">--</strong></div>
<div class="metric"><span class="label">GPS longitude</span><strong id="lon">--</strong></div>
</div>
<p id="satstatus" class="status">Waiting for ESP32 telemetry.</p>
</section>

<section class="card">
<h2>🗺️ Pune ground station</h2>
<div id="map"></div>
<p class="status">Map uses OpenStreetMap. Marker shows the configured Pune ground-station location.</p>
</section>

<section class="card">
<h2>🌡️ MLX90640 thermal camera</h2>
<img id="thermal" alt="Thermal camera image will appear after upload"
 style="width:100%;max-height:400px;object-fit:contain;border-radius:12px;display:none">
<p id="thermalstatus" class="status">Waiting for a thermal image from your hardware.</p>
</section>

<section class="card">
<h2>🗂️ Recent stored weather records</h2>
<div class="table-wrap"><table>
<thead><tr><th>Time</th><th>Temp</th><th>Humidity</th><th>Rain</th><th>Pressure</th><th>Cloud</th></tr></thead>
<tbody id="records"><tr><td colspan="6">Loading...</td></tr></tbody>
</table></div>
<p><a href="/api/history.csv">Download weather history (CSV)</a></p>
</section>

<section class="card">
<h2>About the forecast</h2>
<p class="status">The 2-hour temperature estimate is an experimental trend-based estimate, not an official IMD forecast. Weather data is provided by Open-Meteo. Internet/API outages can interrupt collection.</p>
<p class="status">IMD data import and advanced forecast-model training can be added as a next step.</p>
</section>
</main>
<footer>Pune Weather & CubeSat Mission Control · Prototype dashboard</footer>

<script>
let chart;
function iconFor(code){
 if(code===0)return "☀️";
 if([1,2].includes(code))return "🌤️";
 if(code===3)return "☁️";
 if([45,48].includes(code))return "🌫️";
 if([51,53,55,61,63,65,80,81,82].includes(code))return "🌧️";
 if([71,73,75,77,85,86].includes(code))return "❄️";
 if([95,96,99].includes(code))return "⛈️";
 return "🌦️";
}
async function refresh(){
 try{
  const r=await fetch('/api/dashboard',{cache:'no-store'});
  const d=await r.json();
  if(d.weather){
   const w=d.weather;
   document.getElementById('temp').textContent=w.temperature+'°C';
   document.getElementById('symbol').textContent=iconFor(w.weather_code);
   document.getElementById('condition').textContent=w.description;
   document.getElementById('humidity').textContent=w.humidity+'%';
   document.getElementById('rain').textContent=w.rain+' mm';
   document.getElementById('pressure').textContent=w.pressure+' hPa';
   document.getElementById('cloud').textContent=w.cloud+'%';
   document.getElementById('wind').textContent=w.wind+' km/h';
   document.getElementById('estimate').textContent=
      d.estimate===null?'--°C':d.estimate+'°C';
   document.getElementById('updated').textContent='Last observation: '+w.time;
  }
  document.getElementById('count').textContent=d.count;
  document.getElementById('collector').textContent=d.collector?'Running':'Waiting';
  const sat=d.telemetry;
  if(sat){
   document.getElementById('sattemp').textContent=sat.temperature??'--';
   document.getElementById('sathum').textContent=sat.humidity??'--';
   document.getElementById('lat').textContent=sat.latitude??'--';
   document.getElementById('lon').textContent=sat.longitude??'--';
   document.getElementById('satstatus').textContent='Last telemetry: '+sat.time;
  }
  if(d.thermal){
   const im=document.getElementById('thermal');
   im.src='/thermal-image?time='+encodeURIComponent(d.thermal.time);
   im.style.display='block';
   document.getElementById('thermalstatus').textContent='Last thermal image: '+d.thermal.time;
  }
  const labels=d.history.map(x=>x.time);
  const values=d.history.map(x=>x.temperature);
  if(chart){chart.data.labels=labels;chart.data.datasets[0].data=values;chart.update();}
  else{
   chart=new Chart(document.getElementById('chart'),{
    type:'line',
    data:{labels:labels,datasets:[{label:'Temperature °C',data:values,
    tension:.3,fill:true}]},
    options:{responsive:true,scales:{y:{title:{display:true,text:'°C'}}}}
   });
  }
  document.getElementById('records').innerHTML=d.history.slice(-10).reverse().map(x=>
   '<tr><td>'+x.time+'</td><td>'+x.temperature+'</td><td>'+x.humidity+
   '%</td><td>'+x.rain+'</td><td>'+x.pressure+'</td><td>'+x.cloud+'%</td></tr>'
  ).join('')||'<tr><td colspan="6">No records yet</td></tr>';
 }catch(e){document.getElementById('updated').textContent='Refresh failed; retrying...';}
}
const map=L.map('map').setView([18.5204,73.8567],10);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{
 attribution:'&copy; OpenStreetMap contributors'
}).addTo(map);
L.marker([18.5204,73.8567]).addTo(map).bindPopup('Pune ground station');
refresh();setInterval(refresh,30000);
</script>
</body>
</html>
"""


def connect_db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with connect_db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS weather (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          time TEXT UNIQUE,
          temperature REAL,
          humidity REAL,
          rain REAL,
          pressure REAL,
          cloud REAL,
          wind REAL,
          weather_code INTEGER
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS telemetry (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          time TEXT,
          temperature REAL,
          humidity REAL,
          latitude REAL,
          longitude REAL,
          extra TEXT
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS thermal (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          time TEXT,
          image BLOB,
          content_type TEXT
        )""")
        conn.commit()


def weather_description(code):
    codes = {
        0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy",
        3: "Overcast", 45: "Fog", 48: "Depositing rime fog",
        51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
        61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
        71: "Light snow", 73: "Snow", 75: "Heavy snow",
        80: "Rain showers", 81: "Rain showers", 82: "Heavy showers",
        95: "Thunderstorm", 96: "Thunderstorm with hail",
        99: "Severe thunderstorm"
    }
    return codes.get(int(code or 0), "Current conditions")


def fetch_weather():
    params = {
        "latitude": PUNE_LAT,
        "longitude": PUNE_LON,
        "current": (
            "temperature_2m,relative_humidity_2m,precipitation,"
            "pressure_msl,cloud_cover,wind_speed_10m,weather_code"
        ),
        "timezone": "Asia/Kolkata"
    }
    response = requests.get(WEATHER_URL, params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    cur = payload["current"]
    record = {
        "time": cur.get("time") or datetime.now().isoformat(timespec="minutes"),
        "temperature": cur.get("temperature_2m"),
        "humidity": cur.get("relative_humidity_2m"),
        "rain": cur.get("precipitation"),
        "pressure": cur.get("pressure_msl"),
        "cloud": cur.get("cloud_cover"),
        "wind": cur.get("wind_speed_10m"),
        "weather_code": cur.get("weather_code", 0)
    }
    with db_lock, connect_db() as conn:
        conn.execute("""
        INSERT OR REPLACE INTO weather
        (time,temperature,humidity,rain,pressure,cloud,wind,weather_code)
        VALUES (:time,:temperature,:humidity,:rain,:pressure,:cloud,:wind,:weather_code)
        """, record)
        conn.commit()
    return record


def collector_loop():
    while True:
        try:
            fetch_weather()
            print("Weather collection successful", flush=True)
        except Exception as exc:
            print("Weather collection error:", str(exc), flush=True)
        time.sleep(600)


def start_collector():
    global collector_started
    if not collector_started:
        collector_started = True
        thread = threading.Thread(target=collector_loop, daemon=True)
        thread.start()


@app.route("/")
def home():
    return render_template_string(PAGE)


@app.route("/health")
def health():
    return jsonify({"ok": True, "service": "Pune CubeSat Weather"})


@app.route("/api/dashboard")
def dashboard():
    with db_lock, connect_db() as conn:
        rows = conn.execute(
            "SELECT * FROM weather ORDER BY time DESC LIMIT 100"
        ).fetchall()
        sat = conn.execute(
            "SELECT * FROM telemetry ORDER BY id DESC LIMIT 1"
        ).fetchone()
        thermal = conn.execute(
            "SELECT time FROM thermal ORDER BY id DESC LIMIT 1"
        ).fetchone()
    history = [dict(row) for row in reversed(rows)]
    latest = dict(rows[0]) if rows else None
    estimate = None
    if len(history) >= 2:
        a, b = history[-2], history[-1]
        delta = float(b["temperature"]) - float(a["temperature"])
        estimate = round(float(b["temperature"]) + max(-3, min(3, delta * 12)), 1)
    weather = None
    if latest:
        weather = {
            "time": latest["time"],
            "temperature": latest["temperature"],
            "humidity": latest["humidity"],
            "rain": latest["rain"],
            "pressure": latest["pressure"],
            "cloud": latest["cloud"],
            "wind": latest["wind"],
            "weather_code": latest["weather_code"],
            "description": weather_description(latest["weather_code"])
        }
    return jsonify({
        "weather": weather,
        "estimate": estimate,
        "count": len(history),
        "collector": collector_started,
        "history": history,
        "telemetry": dict(sat) if sat else None,
        "thermal": dict(thermal) if thermal else None
    })


@app.route("/api/telemetry", methods=["POST"])
def receive_telemetry():
    if request.headers.get("X-Device-Token", "") != DEVICE_TOKEN:
        return jsonify({"error": "Unauthorized device"}), 401
    data = request.get_json(silent=True) or {}
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with db_lock, connect_db() as conn:
        conn.execute("""
        INSERT INTO telemetry(time,temperature,humidity,latitude,longitude,extra)
        VALUES(?,?,?,?,?,?)
        """, (
            now, data.get("temperature"), data.get("humidity"),
            data.get("latitude"), data.get("longitude"),
            json.dumps(data)
        ))
        conn.commit()
    return jsonify({"ok": True, "received_at": now})


@app.route("/api/thermal", methods=["POST"])
def receive_thermal():
    if request.headers.get("X-Device-Token", "") != DEVICE_TOKEN:
        return jsonify({"error": "Unauthorized device"}), 401
    image_data = request.get_data()
    if not image_data:
        return jsonify({"error": "Send image bytes in request body"}), 400
    content_type = request.headers.get("Content-Type", "image/jpeg")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with db_lock, connect_db() as conn:
        conn.execute(
            "INSERT INTO thermal(time,image,content_type) VALUES(?,?,?)",
            (now, image_data, content_type)
        )
        conn.commit()
    return jsonify({"ok": True, "received_at": now})


@app.route("/thermal-image")
def thermal_image():
    with db_lock, connect_db() as conn:
        row = conn.execute(
            "SELECT image,content_type FROM thermal ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return "No thermal image received yet", 404
    return Response(row["image"], mimetype=row["content_type"])


@app.route("/api/history.csv")
def history_csv():
    with db_lock, connect_db() as conn:
        rows = conn.execute("SELECT * FROM weather ORDER BY time").fetchall()
    columns = ["time", "temperature", "humidity", "rain", "pressure",
               "cloud", "wind", "weather_code"]
    output = [",".join(columns)]
    for row in rows:
        output.append(",".join("" if row[c] is None else str(row[c]) for c in columns))
    return Response("\n".join(output), mimetype="text/csv",
                    headers={"Content-Disposition":
                             "attachment; filename=pune_weather_history.csv"})


init_db()
start_collector()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
