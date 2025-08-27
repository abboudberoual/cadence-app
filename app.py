
import os
import requests
import json
import calendar
from flask import Flask, redirect, request
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
import polyline

from openai import OpenAI
from datetime import datetime
from flask import Flask, redirect, request, render_template
from datetime import date
from flask import render_template_string, request

from flask import Flask, render_template, request, redirect, url_for

load_dotenv()

app = Flask(__name__)

CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
REDIRECT_URI = os.getenv("STRAVA_REDIRECT_URI")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")   # get from .env

client = OpenAI(api_key=OPENAI_API_KEY)

def get_access_token():
    """Load saved tokens and refresh if expired."""
    if not os.path.exists("tokens.json"):
        return None  # no tokens saved yet

    with open("tokens.json", "r") as f:
        tokens = json.load(f)

    # Check expiry
    import time
    now = int(time.time())
    if tokens.get("expires_at", 0) < now:
        # Refresh the token
        response = requests.post("https://www.strava.com/oauth/token", data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": tokens.get("refresh_token")
        })
        tokens = response.json()
        # Save new tokens
        with open("tokens.json", "w") as f:
            json.dump(tokens, f, indent=2)

    return tokens.get("access_token")

def get_recent_activities(n=10):
    """Fetch recent activities (fallback to saved file)."""
    if os.path.exists("activities.json"):
        with open("activities.json", "r") as f:
            return json.load(f)
    return []


def generate_stats_sticker(activity, polyline_data=None, output_path="static/sticker.png"):
    # Transparent canvas
    img = Image.new("RGBA", (600, 600), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # Fonts
    font_big = ImageFont.truetype("arial.ttf", 50)
    font_small = ImageFont.truetype("arial.ttf", 30)

    # Write stats
    draw.text((50, 50), f"{activity['distance_km']} km", fill="white", font=font_big)
    draw.text((50, 120), f"{activity['moving_time_min']} min", fill="white", font=font_small)
    if activity.get("avg_hr"):
        draw.text((50, 180), f"{int(activity['avg_hr'])} bpm", fill="red", font=font_small)

    # If polyline → draw trace
    if polyline_data:
        coords = polyline.decode(polyline_data)
        scale = 5
        offset = (300, 300)
        points = [(int(x*scale)+offset[0], int(y*scale)+offset[1]) for y, x in coords]
        draw.line(points, fill="orange", width=6)

    img.save(output_path, "PNG")
    return output_path

@app.route("/")
def home():
    return render_template("home.html", active_page="home")

@app.route("/connect")
def connect():
    auth_url = (
        "https://www.strava.com/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        "&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        "&scope=read,activity:read_all"
        "&approval_prompt=auto"
    )
    return redirect(auth_url)


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "No code returned from Strava", 400

    # Exchange code for token
    token_url = "https://www.strava.com/oauth/token"
    response = requests.post(token_url, data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code"
    })

    tokens = response.json()

    # --- Save tokens to a file ---
    with open("tokens.json", "w") as f:
        json.dump(tokens, f, indent=2)

    access_token = tokens.get("access_token")

    # Fetch last 10 activities
    activities_url = "https://www.strava.com/api/v3/athlete/activities"
    r = requests.get(activities_url, headers={
        "Authorization": f"Bearer {access_token}"
    }, params={"per_page": 10})

    activities = r.json()

    # Display summary info
    output = "<h2>Last 10 Activities</h2><ul>"
    for act in activities:
        name = act.get("name", "Unnamed")
        sport = act.get("type", "Unknown")
        dist = act.get("distance", 0) / 1000  # meters → km
        time_min = act.get("moving_time", 0) / 60  # seconds → minutes
        output += f"<li>{sport} – {name} – {dist:.1f} km – {time_min:.0f} min</li>"
    output += "</ul>"

    return output

@app.route("/activities")
def activities():
    access_token = get_access_token()
    if not access_token:
        return '<a href="/">Connect with Strava first</a>'

    # Pagination
    page = int(request.args.get("page", 1))
    per_page = 20  # show 20 per page

    activities_url = "https://www.strava.com/api/v3/athlete/activities"
    r = requests.get(
        activities_url,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"per_page": per_page, "page": page}
    )
    activities = r.json()

    # Parse into clean dicts
    table_data = []
    for act in activities:
        table_data.append({
            "id": act.get("id"),
            "name": act.get("name"),
            "sport": act.get("type"),
            "date": act.get("start_date_local"),
            "duration_min": round(act.get("moving_time", 0) / 60),
            "distance_km": round(act.get("distance", 0) / 1000, 2),
            "avg_hr": act.get("average_heartrate"),
            "avg_cadence": act.get("average_cadence"),
        })

    return render_template(
        "activities.html",
        activities=table_data,
        page=page,
        per_page=per_page,
        active_page="activities"
    )


@app.route("/activities/<int:activity_id>")
def activity_detail(activity_id):
    access_token = get_access_token()
    if not access_token:
        return '<a href="/">Connect with Strava first</a>'

    # Fetch detailed info
    detail_url = f"https://www.strava.com/api/v3/activities/{activity_id}"
    detail = requests.get(detail_url, headers={"Authorization": f"Bearer {access_token}"}).json()

    # Extract relevant details
    act = {
        "id": detail.get("id"),
        "name": detail.get("name"),
        "type": detail.get("type"),
        "start_date": detail.get("start_date_local"),
        "distance_km": detail.get("distance", 0) / 1000,
        "moving_time_min": detail.get("moving_time", 0) / 60,
        "avg_hr": detail.get("average_heartrate"),
        "avg_cadence": detail.get("average_cadence"),
        "avg_power": detail.get("average_watts"),
        "calories": detail.get("calories"),
        "map_polyline": detail.get("map", {}).get("summary_polyline"),   # 🚨 add this
        "photos": detail.get("photos", {}).get("primary"),               # 🚨 add this
    }

    return render_template("activity_detail.html", activity=act, active_page="activities")

@app.route("/share/<int:activity_id>")
def share_preview(activity_id):
    access_token = get_access_token()
    if not access_token:
        return redirect(url_for("connect"))

    # Fetch activity details
    detail_url = f"https://www.strava.com/api/v3/activities/{activity_id}?include_all_efforts=false"
    detail = requests.get(detail_url, headers={"Authorization": f"Bearer {access_token}"}).json()

    # Collect all images
    images = []
    if detail.get("photos", {}).get("primary"):
        images.append(list(detail["photos"]["primary"]["urls"].values())[0])

    if detail.get("photos", {}).get("count", 0) > 1:
        # Fetch all uploaded photos
        photos_url = f"https://www.strava.com/api/v3/activities/{activity_id}/photos"
        photo_resp = requests.get(
            photos_url, headers={"Authorization": f"Bearer {access_token}"}
        ).json()
        for p in photo_resp:
            if p.get("urls"):
                images.append(list(p["urls"].values())[0])

    # Add map preview if available
    if detail.get("map", {}).get("summary_polyline"):
        map_url = (
            f"https://maps.googleapis.com/maps/api/staticmap"
            f"?size=1080x1080&path=enc:{detail['map']['summary_polyline']}&key=YOUR_API_KEY"
        )
        images.insert(0, map_url)  # put map first in the list

    # Fallback placeholder if no images at all
    if not images:
        images.append(url_for("static", filename="map_placeholder.png"))

    # Pack activity stats
    act = {
        "id": detail.get("id"),
        "name": detail.get("name"),
        "type": detail.get("type"),
        "distance_km": round(detail.get("distance", 0) / 1000, 2),
        "moving_time_min": round(detail.get("moving_time", 0) / 60),
        "avg_hr": detail.get("average_heartrate"),
        "avg_cadence": detail.get("average_cadence"),
        "calories": detail.get("calories"),
    }

    return render_template(
        "share_preview.html",
        activity=act,
        preview_image=images[0],  # first image shown initially
        images=images,
        active_page="aura"
    )


@app.route("/coach")
def coach():
    today = str(date.today())

    # Load athlete profile
    profile_text = ""
    if os.path.exists("profile.json"):
        with open("profile.json", "r") as f:
            profile = json.load(f)
        profile_text = f"Athlete profile: {json.dumps(profile)}"

    # Load existing plan file if it exists
    plan_file = "plan.json"
    if os.path.exists(plan_file):
        with open(plan_file, "r") as f:
            plans = json.load(f)
    else:
        plans = {}

    # If today's plan already exists, reuse it
    if today in plans:
        plan = plans[today]
        return render_template(
            "coach.html",
            advice=plan,
            active_page="coach",
            source="Saved Plan"
        )

    # Otherwise → generate a new plan with OpenAI
    if not os.path.exists("activities.json"):
        return '<p>No detailed activities found. Visit <a href="/activities">/activities</a> first.</p>'

    with open("activities.json", "r") as f:
        activities = json.load(f)

    # Build a summary of last workouts
    summary = ""
    for a in activities:
        summary += (
            f"{a['type']} – {a['name']} – {a['distance_km']:.1f} km – "
            f"{a['moving_time_min']:.0f} min"
        )
        if a.get("avg_hr"):
            summary += f" – HR {a['avg_hr']:.0f} bpm"
        if a.get("avg_cadence"):
            summary += f" – Cadence {a['avg_cadence']:.0f}"
        if a.get("avg_power"):
            summary += f" – Power {a['avg_power']:.0f} W"
        summary += "\n"

    # Ask GPT for a structured JSON plan
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are Cadence, an AI triathlon coach. Output ONLY valid JSON with keys: sport, duration_min, intensity, rationale."},
            {"role": "user", "content": f"{profile_text}\nHere are my last workouts:\n{summary}\n\nGenerate tomorrow's training plan."}
        ],
        response_format={ "type": "json_object" }
    )

    plan = json.loads(completion.choices[0].message.content)

    # Save the plan into plan.json
    plans[today] = plan
    with open(plan_file, "w") as f:
        json.dump(plans, f, indent=2)

    return render_template(
        "coach.html",
        advice=plan,
        active_page="coach",
        source="New Plan"
    )


@app.route("/profile", methods=["GET", "POST"])
def profile():
    profile_file = "profile.json"

    # Load current profile (initialize empty structured dict if not found)
    if os.path.exists(profile_file):
        with open(profile_file, "r") as f:
            profile = json.load(f)
    else:
        profile = {
            "identity": {},
            "anthropometrics": {},
            "goals": {"races": [{}], "preferences": {}},
            "constraints": {},
            "injuries": [{}],
            "thresholds": {"run": {}, "bike": {}, "swim": {}},
            "nutrition": {},
            "equipment": {}
        }

    # Save updates from form
    if request.method == "POST":
        profile["identity"]["name"] = request.form.get("name")
        profile["identity"]["dob"] = request.form.get("dob")
        profile["identity"]["sex"] = request.form.get("sex")
        profile["identity"]["timezone"] = request.form.get("timezone")
        profile["identity"]["locale"] = request.form.get("locale")

        profile["anthropometrics"]["height_cm"] = request.form.get("height_cm")
        profile["anthropometrics"]["weight_kg"] = request.form.get("weight_kg")
        profile["anthropometrics"]["bodyfat_percent"] = request.form.get("bodyfat_percent")

        profile["goals"]["races"][0]["name"] = request.form.get("race_name")
        profile["goals"]["races"][0]["date"] = request.form.get("race_date")
        profile["goals"]["races"][0]["priority"] = request.form.get("race_priority")
        profile["goals"]["methodology"] = request.form.get("methodology")
        profile["goals"]["preferences"]["indoor_ok"] = "indoor_ok" in request.form

        profile["thresholds"]["run"]["threshold_pace"] = request.form.get("run_pace")
        profile["thresholds"]["run"]["threshold_hr"] = request.form.get("run_hr")
        profile["thresholds"]["bike"]["ftp"] = request.form.get("bike_ftp")
        profile["thresholds"]["bike"]["w_kg"] = request.form.get("bike_wkg")
        profile["thresholds"]["swim"]["css"] = request.form.get("swim_css")

        profile["injuries"][0]["area"] = request.form.get("injury_area")
        profile["injuries"][0]["status"] = request.form.get("injury_status")

        profile["nutrition"]["diet"] = request.form.get("diet")
        profile["nutrition"]["restrictions"] = request.form.get("restrictions")

        profile["equipment"]["bike"] = request.form.get("bike")
        profile["equipment"]["sensors"] = request.form.get("sensors")

        # Save to file
        with open(profile_file, "w") as f:
            json.dump(profile, f, indent=2)

    return render_template("profile.html", profile=profile, active_page="profile")



@app.route("/schedule")
def schedule():
    import calendar
    from datetime import date

    plan_file = "plan.json"
    if os.path.exists(plan_file):
        with open(plan_file, "r") as f:
            plans = json.load(f)
    else:
        plans = {}

    # Get year/month from query params or fallback to today
    today = date.today()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))

    cal = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)

    # Navigation links
    prev_month, prev_year = (month - 1, year) if month > 1 else (12, year - 1)
    next_month, next_year = (month + 1, year) if month < 12 else (1, year + 1)

    return render_template(
        "schedule.html",
        plans=plans,
        year=year,
        month=month,
        cal=cal,
        month_name=calendar.month_name[month],
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        active_page="schedule"
    )


@app.route("/calendar.ics")
def calendar_ics():
    plan_file = "plan.json"
    if not os.path.exists(plan_file):
        return "No plans found", 404

    with open(plan_file, "r") as f:
        plans = json.load(f)

    ics = "BEGIN:VCALENDAR\nVERSION:2.0\n"
    for date_str, plan in plans.items():
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        start = dt.strftime("%Y%m%dT070000")  # default 7 AM start
        duration = f"PT{plan['duration_min']}M"

        ics += "BEGIN:VEVENT\n"
        ics += f"DTSTART:{start}\n"
        ics += f"DURATION:{duration}\n"
        ics += f"SUMMARY:{plan['sport']} — {plan['intensity']}\n"
        ics += f"DESCRIPTION:{plan['rationale']}\n"
        ics += "END:VEVENT\n"

    ics += "END:VCALENDAR\n"

    return app.response_class(ics, mimetype="text/calendar")

@app.route("/chat", methods=["GET", "POST"])
def chat():
    history_file = "chat_history.json"

    # Load history
    if os.path.exists(history_file):
        with open(history_file, "r") as f:
            history = json.load(f)
    else:
        history = []

    if request.method == "POST":
        user_msg = request.form.get("message")
        if user_msg:
            history.append({"role": "user", "content": user_msg})

            # Context: profile + plan + recent activities
            context = ""
            if os.path.exists("profile.json"):
                with open("profile.json", "r") as f:
                    profile = json.load(f)
                context += f"Athlete profile: {json.dumps(profile)}\n"

            if os.path.exists("plan.json"):
                with open("plan.json", "r") as f:
                    plan = json.load(f)
                context += f"Current plan: {json.dumps(plan)}\n"

            recent = get_recent_activities(10)
            if recent:
                context += "Recent activities (last 10):\n"
                for act in recent:
                    context += (
                        f"- {act.get('type')} {act.get('name')} | "
                        f"{act.get('distance_km',0):.1f} km, "
                        f"{act.get('moving_time_min',0):.0f} min, "
                        f"HR {act.get('avg_hr','?')}, "
                        f"Cadence {act.get('avg_cadence','?')}\n"
                    )

            # Ask GPT with full context
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are Cadence, an AI triathlon coach. Analyze athlete data and answer clearly with safe, supportive guidance."},
                    {"role": "user", "content": context},
                ] + history[-5:]
            )

            reply = completion.choices[0].message.content
            history.append({"role": "assistant", "content": reply})

            # Save
            with open(history_file, "w") as f:
                json.dump(history, f, indent=2)

    # Render simple UI
    html = """
    <h2>Cadence Chat</h2>
    <div style='border:1px solid #ccc; padding:10px; height:300px; overflow-y:scroll;'>
    """
    for msg in history[-10:]:
        if msg["role"] == "user":
            html += f"<p><b>You:</b> {msg['content']}</p>"
        else:
            html += f"<p><b>Cadence:</b> {msg['content']}</p>"
    html += "</div><br>"

    html += """
    <form method="POST">
        <input type="text" name="message" style="width:80%;" placeholder="Ask Cadence something...">
        <button type="submit">Send</button>
    </form>
    """
    return render_template("chat.html", history=history[-10:], active_page="chat")

@app.route("/aura")
def aura():
    access_token = get_access_token()
    if not access_token:
        return redirect(url_for("connect"))

    # Fetch last 20 activities with photos
    r = requests.get(
        "https://www.strava.com/api/v3/athlete/activities",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"per_page": 20, "page": 1}
    )
    activities = r.json()

    # Preprocess: include photos + polyline
    acts = []
    for act in activities:
        acts.append({
            "id": act["id"],
            "name": act.get("name"),
            "type": act.get("type"),
            "distance_km": round(act.get("distance", 0)/1000, 2),
            "moving_time_min": round(act.get("moving_time", 0)/60),
            "map_polyline": act.get("map", {}).get("summary_polyline"),
            "photos": act.get("photos", {}).get("primary", {}).get("urls") if act.get("photos") else None
        })

    return render_template("aura.html", activities=acts, active_page="aura")


@app.route("/aura/<int:activity_id>")
def aura_preview(activity_id):
    access_token = get_access_token()
    if not access_token:
        return '<a href="/">Connect with Strava first</a>'

    # Fetch activity detail
    detail_url = f"https://www.strava.com/api/v3/activities/{activity_id}"
    detail = requests.get(detail_url, headers={"Authorization": f"Bearer {access_token}"}).json()

    # Fetch photos
    photos_url = f"https://www.strava.com/api/v3/activities/{activity_id}/photos"
    photos = requests.get(photos_url, headers={"Authorization": f"Bearer {access_token}"},
                          params={"size": 1000}).json()

    photo_url = photos[0]["urls"]["1000"] if photos else None

    act = {
        "name": detail.get("name"),
        "distance_km": detail.get("distance", 0) / 1000,
        "duration_min": round(detail.get("moving_time", 0) / 60),
        "avg_hr": detail.get("average_heartrate"),
        "avg_cadence": detail.get("average_cadence"),
        "photo_url": photo_url
    }

    return render_template("aura_preview.html", activity=act, active_page="aura")

if __name__ == "__main__":
    app.run(debug=True)
