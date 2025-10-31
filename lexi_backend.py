import os
import requests
from flask import Flask, request, abort, jsonify, redirect, make_response
from markupsafe import escape

# -------------------
# CONFIG & SETUP
# -------------------

EEG_BASE = "https://www.eegcloud.tv/speech-recognition/live/v2"
INSTANCE_ID = "asr_instance_EUwk84qjnygKawQK"  # Lexi Live test instance

API_USERNAME = "api_key"
API_KEY = os.environ.get("EEG_API_KEY")

# PIN lock config
ACCESS_PIN = os.environ.get("ACCESS_PIN", "2065")

app = Flask(__name__)

# Flask session signing key: set SECRET_KEY in Render env for better security
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE-ME-LATER")


# -------------------
# HELPERS
# -------------------

def is_authorized(req: request) -> bool:
    """
    Check whether the user already passed the PIN.
    We store a signed cookie 'auth_ok' = 'yes'.
    """
    auth_ok = req.cookies.get("auth_ok", "")
    # If cookie is 'yes', they're in.
    return auth_ok == "yes"


def check_pin(submitted_pin: str) -> bool:
    """
    Compare PIN typed by user with ACCESS_PIN from env.
    """
    return submitted_pin == ACCESS_PIN


def fetch_instance_info():
    """
    Fetch info about all instances, then return the dict for INSTANCE_ID.
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
    Call /turn_on or /turn_off for our instance.
    Returns (ok:boolean, msg:str).
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
    Colour for the status pill.
    """
    st_upper = (state_text or "UNKNOWN").upper()
    if st_upper in ("ON", "RUNNING", "ACTIVE"):
        return "#28a745"  # green
    elif st_upper in ("OFF", "STOPPED", "IDLE"):
        return "#dc3545"  # red
    else:
        return "#6c757d"  # grey / unknown


def render_lock_page(error_msg=None):
    """
    HTML shown when user is not yet unlocked.
    A simple PIN form.
    """
    safe_error = escape(error_msg) if error_msg else ""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8"/>
        <title>Lexi Live Control - Locked</title>
    </head>
    <body style="font-family:sans-serif; max-width:360px; margin:60px auto; text-align:center;">
        <h1 style="margin-bottom:0.5em;">Access PIN Required</h1>
        <p style="color:#666; margin-top:0;">Enter PIN to control Lexi Live.</p>

        {"<p style='color:#dc3545; font-weight:bold;'>" + safe_error + "</p>" if safe_error else ""}

        <form method="post" action="/unlock" style="margin-top:1.5em;">
            <input
                type="password"
                name="pin"
                placeholder="PIN"
                style="font-size:1.2em; padding:0.5em 0.75em; width:200px; text-align:center; border-radius:6px; border:1px solid #aaa;"
                autofocus
            />
            <div style="margin-top:1em;">
                <button
                    style="font-size:1.1em; padding:0.6em 1.2em; border-radius:6px; border:0; background:#007bff; color:#fff; cursor:pointer;">
                    Unlock
                </button>
            </div>
        </form>

        <p style="font-size:0.8em;color:#999;margin-top:2em;">
            This panel is restricted to AVE staff.
        </p>
    </body>
    </html>
    """


def render_home(flash_msg=None):
    """
    Full control panel HTML (only shown if authorized).
    Includes auto-refresh JS.
    """
    instance_name, instance_state = eeg_status()
    badge_color = pick_badge_color(instance_state)

    safe_flash = (
        escape(flash_msg)
        if flash_msg
        else "Control panel is live. PIN verified."
    )

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8"/>
        <title>Lexi Live Control</title>
        <script>
        async function refreshStatus() {{
            try {{
                const res = await fetch('/status.json', {{
                    cache: 'no-store',
                    credentials: 'include'
                }});
                if (!res.ok) return;
                const data = await res.json();

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
                // ignore refresh errors
            }}
        }}

        // Poll every 10 seconds
        setInterval(refreshStatus, 10000);
        window.addEventListener('load', refreshStatus);
        </script>
    </head>

    <body style="font-family:sans-serif; max-width:400px; margin:40px auto; text-align:center;">

        <h1 style="margin-bottom:0.25em;">Lexi Live Control</h1>
        <p style="color:#666;margin:0 0 1em 0;">Instance:
            <span id="instanceName">{instance_name}</span>
        </p>

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

        <form action="/lock" method="post" style="margin-top:2em;">
            <button style="
                font-size:0.9em;
                padding:0.5em 1em;
                border-radius:6px;
                border:0;
                background:#6c757d;
                color:#fff;
                cursor:pointer;">
                Lock Panel
            </button>
        </form>

    </body>
    </html>
    """


# -------------------
# ROUTES
# -------------------

@app.route("/", methods=["GET"])
def home():
    # If not authorized yet, show PIN prompt
    if not is_authorized(request):
        return render_lock_page()
    # Otherwise show control panel
    return render_home()


@app.route("/unlock", methods=["POST"])
def unlock():
    """
    User submits the PIN here.
    If correct -> set auth_ok cookie, redirect home.
    If wrong   -> show lock page w/ error.
    """
    submitted_pin = request.form.get("pin", "").strip()
    if check_pin(submitted_pin):
        # Set a cookie auth_ok=yes
        resp = make_response(redirect("/"))
        # httponly stops JS from reading cookie; path=/ so it's valid everywhere
        resp.set_cookie("auth_ok", "yes", httponly=True, samesite="Lax")
        return resp
    else:
        return render_lock_page(error_msg="Incorrect PIN")


@app.route("/lock", methods=["POST"])
def relock():
    """
    User presses "Lock Panel".
    Clear auth cookie.
    """
    resp = make_response(render_lock_page("Panel locked. Enter PIN again."))
    resp.set_cookie("auth_ok", "", httponly=True, samesite="Lax")
    return resp


@app.route("/on", methods=["POST"])
def turn_on():
    if not is_authorized(request):
        return render_lock_page("Please enter PIN first.")
    ok, msg = eeg_post("turn_on")
    return render_home(msg)


@app.route("/off", methods=["POST"])
def turn_off():
    if not is_authorized(request):
        return render_lock_page("Please enter PIN first.")
    ok, msg = eeg_post("turn_off")
    return render_home(msg)


@app.route("/status.json", methods=["GET"])
def status_json():
    """
    Called by auto-refresh JS.
    Must also be PIN-protected.
    """
    if not is_authorized(request):
        # Return 403 JSON so the frontend knows it's locked again.
        return jsonify({"error": "locked"}), 403

    name, state = eeg_status()
    return jsonify({
        "name": name,
        "state": state,
        "badge_color": pick_badge_color(state),
    })


# -------------------
# ENTRY POINT
# -------------------

if __name__ == "__main__":
    # local dev
    app.run(host="0.0.0.0", port=8080)
