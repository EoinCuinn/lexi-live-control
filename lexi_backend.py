import os
import requests
from flask import Flask, jsonify, abort

app = Flask(__name__)

# --- Config you can change ---
EEG_BASE = "https://www.eegcloud.tv/speech-recognition/live/v2"
INSTANCE_ID = "asr_instance_EUwk84qjnygKawQK"  # Lexi Live test
API_USERNAME = "api_key"

# We'll load the real EEG API key from the environment at runtime.
API_KEY = os.environ.get("EEG_API_KEY")


def send_command(action):
    """
    action must be "turn_on" or "turn_off".
    We POST to:
      /speech-recognition/live/v2/instances/{INSTANCE_ID}/{action}
    using Basic Auth (api_key : your-secret-key)
    """
    if action not in ("turn_on", "turn_off"):
        abort(400, "Invalid action")

    if not API_KEY:
        abort(500, "EEG_API_KEY is not set on the server")

    url = f"{EEG_BASE}/instances/{INSTANCE_ID}/{action}"

    r = requests.post(
        url,
        auth=(API_USERNAME, API_KEY),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json={}
    )

    if not r.ok:
        abort(r.status_code, r.text)

    # Return the JSON back to the browser so you can see what happened
    try:
        return r.json()
    except Exception:
        return {"status": "ok", "raw": r.text[:500]}


@app.route("/")
def home():
    # Simple HTML UI with two buttons that call /on and /off via POST
    # (onsubmit forms so it's easy, no JS required)
    return """
        <div style="font-family:sans-serif;max-width:400px;margin:40px auto;text-align:center;">
            <h1 style="margin-bottom:0.5em;">Lexi Live Control</h1>
            <p style="color:#666;margin-top:0;">Instance: Lexi Live test</p>

            <form action="/on" method="post" style="margin:1em 0;">
                <button style="font-size:1.1em;padding:0.75em 1.5em;border-radius:8px;border:0;background:#28a745;color:#fff;cursor:pointer;">
                    Turn ON
                </button>
            </form>

            <form action="/off" method="post" style="margin:1em 0;">
                <button style="font-size:1.1em;padding:0.75em 1.5em;border-radius:8px;border:0;background:#dc3545;color:#fff;cursor:pointer;">
                    Turn OFF
                </button>
            </form>

            <p style="font-size:0.8em;color:#999;">No API key is shown here. All control happens server-side.</p>
        </div>
    """


@app.route("/on", methods=["POST"])
def on():
    result = send_command("turn_on")
    return jsonify(result)


@app.route("/off", methods=["POST"])
def off():
    result = send_command("turn_off")
    return jsonify(result)


if __name__ == "__main__":
    # Local dev: run on http://localhost:8080
    app.run(host="0.0.0.0", port=8080)
