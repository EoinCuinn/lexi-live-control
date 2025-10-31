import os
import requests
from flask import Flask, request, abort, jsonify
from markupsafe import escape

app = Flask(__name__)

# --- CONFIG ---
EEG_BASE = "https://www.eegcloud.tv/speech-recognition/live/v2"
INSTANCE_ID = "asr_instance_EUwk84qjnygKawQK"  # Lexi Live test
API_USERNAME = "api_key"
API_KEY = os.environ.get("EEG_API_KEY")  # stored in Render env vars


def fetch_instance_info():
    """
    Low-level helper.
    Returns the full instance dict for INSTANCE_ID (or None on error).
    """
    if not API_KEY:
        return None

    url = f"{EEG_BASE}/instances?get_history=0"
    try:
        resp = requests.get(
            url,
            auth=(API_USERNAME, API_KEY),
            headers={"Accept": "application/json"},
            timeout=10,
        )
    except Exception:
        return None

    if not resp.ok:
        return None

    data = resp.json()
    for inst in data.get("all_instances", []):
        if inst.get("instance_id") == INSTANCE_ID:
            return inst
    return None


def eeg_status():
    """
    Friendly wrapper.
    Returns (instance_name, instance_state).
    """
    info = fetch_instance_info()
    if not info:
        return ("Lexi Live test", "UNKNOWN")

    instance_name = info.get("settings", {}).get("name", "Unknown instance")
    instance_state = info.get("state", "UNKNOWN")
    return (instance_name, instance_state)


def eeg_post(action):
    """
    POST /turn_on or /turn_off for our Lexi instance.
    Returns (ok:boolean, msg:str)
    """
    if action not in ("turn_on", "turn_off"):
        abort(400, "Invalid action")

    if not API_KEY:
        abort(500, "EEG_API_KEY is not set on the server")

    url = f"{EEG_BASE}/instances/{INSTANCE_ID}/{action}"
    try:
        resp = requests.post(
            url,
            auth=(API_USERNAME, API_KEY),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={},
            timeout=10,
        )
    except Exception as e:
        return False, f"Request error: {e}"

    if resp.ok:
        if action == "turn_on":
            return True, "Lexi Live started ✅"
        else:
            return True, "Lexi Live stopped ⛔"
    else:
        return False, f"Request failed ({resp.status_code})"


def pick_badge_color(state_text):
    """
    Decide pill color for a given state.
    """
    st_upper = (state_text or "UNKNOWN").upper()
    if st_upper in ("ON", "RUNNING", "ACTIVE"):
        return "#28a745"  # green
    elif st_upper in ("OFF", "STOPPED", "IDLE"):
        return "#dc3545"  # red
    else:
        return "#6c757d"  # grey/unknown


def render_home(flash_msg=None):
    """
    Build the HTML page with inline JS that auto-refreshes status.
    """
    instance_name, instance_state = eeg_status()
    badge_color = pick_badge_color(instance_state)

    safe_flash = (
        escape(flash_msg)
        if flash_msg
        else "No API key is shown here. All control happens server-side."
    )

    # Note the <span id="stateText"> and <div id="stateBadge"> wrappers.
    # JS will update those in-place every 10 seconds.
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8"/>
        <title>Lexi Live Control</title>
        <script>
        async function refreshStatus() {{
            try {{
                const res = await fetch('/status.json', {{ cache: 'no-store' }});
                if (!res.ok) return;
                const data = await res.json();

                // Update text
                const stateEl = document.getElementById('stateText');
                const nameEl  = document.getElementById('instanceName');
                const badgeEl = document.getElementById('stateBadge');

                if (stateEl && data.state) {{
                    stateEl.textContent = data.state;
                }}
                if (nameEl && data.name) {{
                    nameEl.textContent = data.name;
                }}
                if (badgeEl && data.badge_color) {{
                    badgeEl.style.background = data.badge_color;
                }}
            }} catch (e) {{
                // swallow errors silently
            }}
        }}

        // Poll every 10 seconds
        setInterval(refreshStatus, 10000);
        // Also do one immediate refresh on load
        window.addEventListener('load', refreshStatus);
        </script>
    </head>
    <body style="font-family:sans-serif; max-width:400px; margin:40px auto; text-align:center;">

        <h1 style="margin-bottom:0.25em;">Lexi Live Control</h1>
        <p style="color:#666;margin:0 0 1em 0;">Instance: <span id="instanceName">{instance_name}</span></p>

        <div id="stateBadge" style="
            margin-bottom:1em;
            font-size:0.9em;
            color:#fff;
            background:{badge_color};
            display:inline-block;
            padding:4px 10px;
            border-radius:6px;">
            State: <span id="stateText">{instance_state}</span>
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
    return render_home()


@app.route("/on", methods=["POST"])
def turn_on():
    ok, msg = eeg_post("turn_on")
    # We don't force-refresh state server-side here anymore,
    # because the browser will poll /status.json anyway.
    return render_home(msg if ok else msg)


@app.route("/off", methods=["POST"])
def turn_off():
    ok, msg = eeg_post("turn_off")
    return render_home(msg if ok else msg)


@app.route("/status.json", methods=["GET"])
def status_json():
    """
    Lightweight status endpoint used by JS polling.
    Returns current state + badge color.
    """
    name, state = eeg_status()
    return jsonify({
        "name": name,
        "state": state,
        "badge_color": pick_badge_color(state),
    })


if __name__ == "__main__":
    # Local dev
    app.run(host="0.0.0.0", port=8080)
