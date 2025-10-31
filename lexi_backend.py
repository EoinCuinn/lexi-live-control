import os
import requests
from flask import Flask, request, abort
from markupsafe import escape

app = Flask(__name__)

# --- CONFIG ---
EEG_BASE = "https://www.eegcloud.tv/speech-recognition/live/v2"
INSTANCE_ID = "asr_instance_EUwk84qjnygKawQK"  # Lexi Live test
API_USERNAME = "api_key"
API_KEY = os.environ.get("EEG_API_KEY")  # set in Render env vars


def eeg_status():
    """
    Ask EEG for current state of our Lexi instance.
    Returns a dict with (name, state, last_updated_timestamp, etc) or None on failure.
    """
    if not API_KEY:
        return None

    url = f"{EEG_BASE}/instances?get_history=0"
    resp = requests.get(
        url,
        auth=(API_USERNAME, API_KEY),
        headers={"Accept": "application/json"},
        timeout=10,
    )

    if not resp.ok:
        return None

    data = resp.json()
    for inst in data.get("all_instances", []):
        if inst.get("instance_id") == INSTANCE_ID:
            return inst

    return None


def eeg_post(action):
    """
    POST /turn_on or /turn_off for our Lexi instance.
    Returns (ok:boolean, short_msg:str)
    """
    if action not in ("turn_on", "turn_off"):
        abort(400, "Invalid action")

    if not API_KEY:
        abort(500, "EEG_API_KEY is not set on the server")

    url = f"{EEG_BASE}/instances/{INSTANCE_ID}/{action}"
    resp = requests.post(
        url,
        auth=(API_USERNAME, API_KEY),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        json={},  # body can be empty; API still wants JSON
        timeout=10,
    )

    if resp.ok:
        if action == "turn_on":
            return True, "Lexi Live started ✅"
        else:
            return True, "Lexi Live stopped ⛔"
    else:
        return False, f"Request failed ({resp.status_code})"


def render_home(status_info, flash_msg=None):
    """
    Build the HTML page.
    status_info is whatever eeg_status() returned (or None).
    flash_msg is a short status string from last ON/OFF click.
    """

    if status_info:
        instance_name = status_info.get("settings", {}).get("name", "Unknown instance")
        instance_state = status_info.get("state", "UNKNOWN")
    else:
        instance_name = "Lexi Live test"
        instance_state = "UNKNOWN"

    # Choose badge color:
    st_upper = (instance_state or "UNKNOWN").upper()
    if st_upper in ("ON", "RUNNING", "ACTIVE"):
        badge_color = "#28a745"  # green
    elif st_upper in ("OFF", "STOPPED", "IDLE"):
        badge_color = "#dc3545"  # red
    else:
        # The API sometimes leaves "state": "ON" even though the session is TERMINATED.
        # We'll treat anything else as "amber/grey" to warn it's in-between.
        badge_color = "#6c757d"  # grey

    safe_flash = escape(flash_msg) if flash_msg else "No API key is shown here. All control happens server-side."

    # Very basic inline-styled HTML so we don't need any extra files.
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8"/>
        <title>Lexi Live Control</title>
    </head>
    <body style="font-family:sans-serif; max-width:400px; margin:40px auto; text-align:center;">

        <h1 style="margin-bottom:0.25em;">Lexi Live Control</h1>
        <p style="color:#666;margin:0 0 1em 0;">Instance: {instance_name}</p>

        <div style="
            margin-bottom:1em;
            font-size:0.9em;
            color:#fff;
            background:{badge_color};
            display:inline-block;
            padding:4px 10px;
            border-radius:6px;">
            State: {instance_state}
        </div>

        <form action="/on" method="post" style="margin:1em 0;">
            <button style="
                font-size:1.1em;
                padding:0.75em 1.5em;
                border-radius:8px;
                border:0;
                background:#28a745;
                color:#fff;
                cursor:pointer;">
                Turn ON
            </button>
        </form>

        <form action="/off" method="post" style="margin:1em 0;">
            <button style="
                font-size:1.1em;
                padding:0.75em 1.5em;
                border-radius:8px;
                border:0;
                background:#dc3545;
                color:#fff;
                cursor:pointer;">
                Turn OFF
            </button>
        </form>

        <p style="font-size:0.8em;color:#999;margin-top:2em;">
            {safe_flash}
        </p>

    </body>
    </html>
    """


@app.route("/", methods=["GET"])
def home():
    info = eeg_status()
    return render_home(info)


@app.route("/on", methods=["POST"])
def turn_on():
    ok, msg = eeg_post("turn_on")

    # After sending ON, ask EEG again so we show updated state
    info = eeg_status()
    # Even if eeg_status() still reports "ON" / "OFF" weirdly, we still surface msg.
    return render_home(info, flash_msg=msg if ok else msg)


@app.route("/off", methods=["POST"])
def turn_off():
    ok, msg = eeg_post("turn_off")

    info = eeg_status()
    return render_home(info, flash_msg=msg if ok else msg)


if __name__ == "__main__":
    # Local dev
    app.run(host="0.0.0.0", port=8080)
