import os
import datetime
import pytz
import requests
from flask import Flask, request, abort, jsonify, redirect, make_response
from markupsafe import escape

# -------------------
# CONFIG & SETUP
# -------------------

# Control API base (turn_on / turn_off / status)
EEG_BASE = "https://www.eegcloud.tv/speech-recognition/live/v2"

# Scheduling API base (calendar events)
SCHED_BASE = "https://www.eegcloud.tv/events"

# Your Lexi instance ID
INSTANCE_ID = "asr_instance_EUwk84qjnygKawQK"  # Lexi Live test instance

# EEG auth: username is always literally "api_key"
API_USERNAME = "api_key"
API_KEY = os.environ.get("EEG_API_KEY")

# PIN lock config
ACCESS_PIN = os.environ.get("ACCESS_PIN", "2065")

# Flask app
app = Flask(__name__)

# Secret for signing cookies etc.
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE-ME-LATER")


# -------------------
# AUTH HELPERS
# -------------------

def is_authorized(req: request) -> bool:
    """
    Check whether the user already passed the PIN.
    We store a cookie 'auth_ok' = 'yes'.
    """
    auth_ok = req.cookies.get("auth_ok", "")
    return auth_ok == "yes"


def check_pin(submitted_pin: str) -> bool:
    """
    Compare PIN typed by user with ACCESS_PIN from env.
    """
    return submitted_pin == ACCESS_PIN


# -------------------
# EEG HELPERS
# -------------------

def fetch_instance_info():
    """
    Fetch info about all instances, then return the dict for INSTANCE_ID.
    Uses /speech-recognition/live/v2/instances?get_history=0
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
            json={},  # body can be empty
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
    Choose pill color for ON/OFF/UNKNOWN.
    """
    st_upper = (state_text or "UNKNOWN").upper()
    if st_upper in ("ON", "RUNNING", "ACTIVE"):
        return "#28a745"  # green
    elif st_upper in ("OFF", "STOPPED", "IDLE"):
        return "#dc3545"  # red
    else:
        return "#6c757d"  # grey / unknown

def render_upcoming_page():
    """
    Read-only Upcoming Jobs view.
    Shows all future jobs (next 30 days for now) in a scrollable table.
    """
    upcoming = get_upcoming_events()

    if upcoming:
        rows_html = ""
        for row in upcoming:
            # safely get values with .get() so we don't KeyError
            date_str = row.get("date_str", "")
            time_str = row.get("time_str", "")
            title    = row.get("title", "")

            rows_html += f"""
            <tr>
                <td style="padding:8px 10px; border-bottom:1px solid #eee; white-space:nowrap;">
                    {escape(date_str)}
                </td>
                <td style="padding:8px 10px; border-bottom:1px solid #eee; white-space:nowrap;">
                    {escape(time_str)}
                </td>
                <td style="padding:8px 10px; border-bottom:1px solid #eee;">
                    {escape(title)}
                </td>
            </tr>
            """
    else:
        rows_html = """
        <tr>
            <td colspan="3" style="padding:12px; text-align:center; color:#666;">
                No upcoming jobs found.
            </td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8"/>
        <title>Upcoming Jobs</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                background:#f5f5f5;
                color:#222;
                padding:30px 10px;
                text-align:center;
            }}
            h1 {{
                margin:0 0 .25em 0;
                font-size:1.5em;
                font-weight:600;
                color:#000;
            }}
            .subhead {{
                color:#666;
                font-size:0.9em;
                margin-bottom:1.5em;
            }}
            .frame {{
                max-width:600px;
                margin:0 auto;
                background:#fff;
                border-radius:12px;
                box-shadow:0 2px 10px rgba(0,0,0,0.08);
                padding:16px;
                text-align:left;
            }}
            table {{
                width:100%;
                border-collapse:collapse;
                font-size:0.9em;
            }}
            thead th {{
                background:#f8f9fa;
                text-align:left;
                padding:8px 10px;
                border-bottom:1px solid #ddd;
                font-weight:600;
                white-space:nowrap;
            }}
            tbody td {{
                font-weight:400;
            }}
            .scroller {{
                max-height:260px;
                overflow-y:auto;
                border:1px solid #eee;
                border-radius:6px;
            }}
            .backlink {{
                text-align:center;
                margin-top:1.5em;
                font-size:0.9em;
            }}
            .backlink a {{
                color:#007bff;
                text-decoration:none;
            }}
        </style>
    </head>
    <body>

        <h1>Upcoming Jobs</h1>
        <div class="subhead">Next scheduled Lexi Live bookings</div>

        <div class="frame">
            <div class="scroller">
                <table>
                    <thead>
                        <tr>
                            <th style="width:30%;">Date</th>
                            <th style="width:30%;">Time</th>
                            <th style="width:40%;">Event</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="backlink">
            <a href="/">← Back to Control Panel</a>
        </div>

    </body>
    </html>
    """


def get_upcoming_events():
    """
    Fetch upcoming scheduled Lexi jobs from the EEG scheduling API and return
    a list of dicts:
        { "date_str": "...", "time_str": "...", "title": "..." }

    We look forward ~30 days from 'now' in Australia/Sydney.
    """
    if not API_KEY:
        return []

    tz = pytz.timezone("Australia/Sydney")

    now_local = datetime.datetime.now(tz)
    future_local = now_local + datetime.timedelta(days=30)

    start_ts = int(now_local.timestamp())
    end_ts   = int(future_local.timestamp())

    params = {
        "duration_start": start_ts,
        "duration_end": end_ts,
        "calculate_recurrences": "true"
    }

    try:
        resp = requests.get(
            SCHED_BASE,
            params=params,
            auth=(API_USERNAME, API_KEY),
            headers={"Accept": "application/json"},
            timeout=10,
        )
    except Exception:
        return []

    if not resp.ok:
        return []

    data = resp.json()
    rows = []

    # Reuse the same ICS parsing style as /events.json :contentReference[oaicite:2]{index=2}
    for ev in data.get("events", []):
        ics = ev.get("ics", "") or ""

        title = "LEXI Booking"
        description = ""

        # SUMMARY → title
        if "SUMMARY:" in ics:
            try:
                after = ics.split("SUMMARY:", 1)[1]
                title_line = after.split("\r\n", 1)[0]
                if title_line.strip():
                    title = title_line.strip()
            except Exception:
                pass

        # DESCRIPTION (not shown in table yet but we could surface later)
        if "DESCRIPTION:" in ics:
            try:
                after_d = ics.split("DESCRIPTION:", 1)[1]
                desc_line = after_d.split("\r\n", 1)[0]
                if desc_line.strip():
                    description = desc_line.strip()
            except Exception:
                pass

        def extract_dt(tag):
            marker = f"{tag};TZID=Australia/Sydney:"
            if marker in ics:
                try:
                    raw = ics.split(marker, 1)[1].split("\r\n", 1)[0].strip()
                    dt_naive = datetime.datetime.strptime(raw, "%Y%m%dT%H%M%S")
                    return tz.localize(dt_naive)
                except Exception:
                    return None
            return None

        start_dt = extract_dt("DTSTART")
        end_dt   = extract_dt("DTEND")

        # Fallbacks using epoch times from API if ICS missing times
        if not start_dt:
            st_epoch = ev.get("start_time")
            if st_epoch is not None:
                start_dt = datetime.datetime.fromtimestamp(st_epoch, tz)
        if not end_dt:
            en_epoch = ev.get("end_time")
            if en_epoch is not None:
                end_dt = datetime.datetime.fromtimestamp(en_epoch, tz)

        # If still no times, skip
        if not start_dt or not end_dt:
            continue

        # Build display strings for table
        # Example: "Thu Oct 30" and "17:30 – 18:00"
        date_str = start_dt.strftime("%a %b %d")
        time_str = f"{start_dt.strftime('%H:%M')} – {end_dt.strftime('%H:%M')}"

        rows.append({
            "date_str": date_str,
            "time_str": time_str,
            "title": title,
        })

    # Sort by start time ascending just in case API gives weird order
    # (we can sort using start_dt, but we didn't store start_dt itself,
    # so let's rebuild temporarily above if we want true ordering).
    # For now assume API is chronological enough.

    return rows

# -------------------
# HTML RENDER HELPERS
# -------------------

def render_lock_page(error_msg=None):
    """
    PIN gate screen for both panel and calendar.
    Clean, client-facing.
    """
    safe_error = escape(error_msg) if error_msg else ""
    error_block = (
        f"<p style='color:#dc3545; font-weight:bold; margin-top:1em;'>{safe_error}</p>"
        if safe_error
        else ""
    )

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8"/>
        <title>Access PIN Required</title>
    </head>
    <body style="font-family:sans-serif; max-width:360px; margin:60px auto; text-align:center;">
        <h1 style="margin-bottom:0.5em;">Access PIN Required</h1>
        <p style="color:#666; margin-top:0;">Enter PIN to continue.</p>

        {error_block}

        <form method="post" action="/unlock" style="margin-top:1.5em;">
            <input
                type="password"
                name="pin"
                placeholder="PIN"
                style="font-size:1.2em; padding:0.5em 0.75em; width:200px;
                       text-align:center; border-radius:6px; border:1px solid #aaa;"
                autofocus
            />
            <div style="margin-top:1em;">
                <button
                    style="font-size:1.1em; padding:0.6em 1.2em; border-radius:6px;
                           border:0; background:#007bff; color:#fff; cursor:pointer;">
                    Unlock
                </button>
            </div>
        </form>
    </body>
    </html>
    """

def render_home(flash_msg=None):
    """
    Control panel main screen.
    - instance name / state
    - ON / OFF buttons
    - buttons for View Schedule + Upcoming Jobs
    - Lock Panel
    """
    instance_name, instance_state = eeg_status()
    badge_color = pick_badge_color(instance_state)

    safe_flash = escape(flash_msg) if flash_msg else "PIN accepted."

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

    <body style="font-family:sans-serif; max-width:420px; margin:40px auto; text-align:center; color:#222;">

        <h1 style="margin-bottom:0.25em;">Lexi Live Control</h1>
        <p style="color:#666;margin:0 0 1em 0;">Instance:
            <span id="instanceName">{escape(instance_name)}</span>
        </p>

        <div id="stateBadge" style="
            margin-bottom:1em;
            font-size:0.9em;
            color:#fff;
            background:{badge_color};
            display:inline-block;
            padding:4px 10px;
            border-radius:6px;">
            State: <span id="stateText">{escape(instance_state)}</span>
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

        <div style="margin-top:1.5em;">
            <a href="/calendar" style="
                display:inline-block;
                font-size:1.0em;
                padding:0.6em 1.2em;
                border-radius:6px;
                background:#17a2b8;
                color:#fff;
                text-decoration:none;
                margin-bottom:0.5em;">
                View Schedule
            </a>
        </div>

        <div style="margin-top:0.5em;">
            <a href="/upcoming" style="
                display:inline-block;
                font-size:1.0em;
                padding:0.6em 1.2em;
                border-radius:6px;
                background:#343a40;
                color:#fff;
                text-decoration:none;">
                Upcoming Jobs
            </a>
        </div>

        <p style="font-size:0.9em;color:#444;margin-top:2em;">
            {safe_flash}
        </p>

        <form action="/lock" method="post" style="margin-top:1em;">
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



def render_calendar_page():
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8"/>
        <title>LEXI Scheduling</title>

        <!-- FullCalendar (from CDN) -->
        <link href="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.9/index.global.min.css" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.9/index.global.min.js"></script>

        <style>
            body {{
                font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
                background:#f5f5f5;
                color:#222;
                text-align:center;
                padding:30px 10px;
            }}
            h1 {{
                margin:0 0 .25em 0;
                font-size:1.75em;
                font-weight:600;
                color:#000;
            }}
            .subhead {{
                color:#666;
                font-size:0.95em;
                margin-bottom:1em;
            }}
            #calendarWrapper {{
                max-width: 960px;
                background:#fff;
                margin:0 auto;
                border-radius:12px;
                box-shadow:0 2px 10px rgba(0,0,0,0.08);
                padding:20px;
                text-align:left;
                position: relative; /* important for tooltip positioning */
            }}
            #calendar {{
                max-width: 960px;
                margin: 0 auto;
            }}
            .backlink {{
                font-size: 0.9em;
                margin-top: 1em;
                text-align:center;
            }}
            .backlink a {{
                color: #007bff;
                text-decoration: none;
            }}

            /* tooltip that WE control */
            #fc-tooltip {{
                position: absolute;
                z-index: 9999;
                background: rgba(0,0,0,0.8);
                color: #fff;
                padding: 8px 10px;
                border-radius: 6px;
                font-size: 12px;
                line-height: 1.4em;
                pointer-events: none;
                white-space: nowrap;
                display: none;
                box-shadow: 0 2px 6px rgba(0,0,0,0.4);
            }}
        </style>
    </head>
    <body>

        <h1>LEXI Scheduling</h1>
        <div class="subhead">Live view of scheduled Lexi Live jobs</div>

        <div id="calendarWrapper">
            <div id="calendar"></div>
            <div id="fc-tooltip"></div>
        </div>

        <div class="backlink">
            <a href="/">← Back to Control Panel</a>
        </div>

        <script>
        document.addEventListener('DOMContentLoaded', function() {{

            const tooltipEl = document.getElementById('fc-tooltip');

            function fmtDateTime(isoStr) {{
                // isoStr is like "2025-11-01T17:30:00+11:00"
                // We turn it into "01 Nov 2025 17:30"
                const d = new Date(isoStr);
                const pad = n => n.toString().padStart(2,'0');
                const day = pad(d.getDate());
                const mon = d.toLocaleString('en-AU', {{ month: 'short' }});
                const yr  = d.getFullYear();
                const hr  = pad(d.getHours());
                const min = pad(d.getMinutes());
                return day + ' ' + mon + ' ' + yr + ' ' + hr + ':' + min;
            }}

            // --- basic tooltip for now (mouse-follow) ---
            function showTooltip(jsEvent, html) {{
                tooltipEl.innerHTML = html;
                tooltipEl.style.display = 'block';

                // position near mouse (safe default baseline)
                tooltipEl.style.left = (jsEvent.pageX + 10) + 'px';
                tooltipEl.style.top  = (jsEvent.pageY + 10) + 'px';
            }}

            function hideTooltip() {{
                tooltipEl.style.display = 'none';
            }}

            var calEl = document.getElementById('calendar');
            var calendar = new FullCalendar.Calendar(calEl, {{
                initialView: 'dayGridMonth',
                timeZone: 'Australia/Sydney',
                height: 'auto',
                headerToolbar: {{
                    left: 'prev,next today',
                    center: 'title',
                    right: 'dayGridMonth,timeGridWeek,timeGridDay'
                }},

                // 24h formatting
                eventTimeFormat: {{ hour: '2-digit', minute: '2-digit', hour12: false }},
                slotLabelFormat: {{ hour: '2-digit', minute: '2-digit', hour12: false }},

                events: function(fetchInfo, successCallback, failureCallback) {{
                    const params = new URLSearchParams({{
                        start: fetchInfo.startStr,
                        end: fetchInfo.endStr
                    }});
                    fetch('/events.json?' + params, {{
                        credentials: 'include' // send cookies so PIN lock still applies
                    }})
                    .then(r => r.json())
                    .then(data => {{
                        if (data.error === "locked") {{
                            alert("Session locked. Please re-enter PIN.");
                            window.location = "/";
                            return;
                        }}
                        successCallback(data);
                    }})
                    .catch(err => failureCallback(err));
                }},

                eventDidMount: function(info) {{
                    // Stop FullCalendar / browser default hover tooltip.
                    // This is what was putting that black box way out to the right.
                    info.el.removeAttribute('title');

                    // Custom hover handling (OUR tooltip)
                    info.el.addEventListener('mouseenter', function(ev) {{
                        const title = info.event.title || '(no title)';
                        const startStr = fmtDateTime(info.event.startStr);
                        const endStr   = info.event.endStr ? fmtDateTime(info.event.endStr) : '';
                        let tipHtml = '<strong>' + title + '</strong><br/>' + startStr;
                        if (endStr) {{
                            tipHtml += ' → ' + endStr;
                        }}

                        showTooltip(ev, tipHtml);
                    }});

                    info.el.addEventListener('mousemove', function(ev) {{
                        if (tooltipEl.style.display === 'block') {{
                            tooltipEl.style.left = (ev.pageX + 10) + 'px';
                            tooltipEl.style.top  = (ev.pageY + 10) + 'px';
                        }}
                    }});

                    info.el.addEventListener('mouseleave', function() {{
                        hideTooltip();
                    }});
                }},

                eventClick: function(info) {{
                    info.jsEvent.preventDefault();
                    const title = info.event.title || '(no title)';
                    const startStr = fmtDateTime(info.event.startStr);
                    const endStr   = info.event.endStr ? fmtDateTime(info.event.endStr) : '';
                    const desc = info.event.extendedProps && info.event.extendedProps.description
                        ? info.event.extendedProps.description
                        : '';

                    let msg = title + "\\n" + startStr;
                    if (endStr) {{
                        msg += " → " + endStr;
                    }}
                    if (desc) {{
                        msg += "\\n\\n" + desc;
                    }}
                    alert(msg);
                }}
            }});

            calendar.render();
        }});
        </script>
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
    
@app.route("/upcoming", methods=["GET"])
def upcoming_page():
    # same auth check pattern as other protected pages
    if not is_authorized(request):
        return redirect("/lock")

    return render_upcoming_page()
  
@app.route("/unlock", methods=["POST"])
def unlock():
    """
    User submits the PIN here.
    If correct -> set auth_ok cookie, redirect home.
    If wrong   -> show lock page w/ error.
    """
    submitted_pin = request.form.get("pin", "").strip()
    if check_pin(submitted_pin):
        resp = make_response(redirect("/"))
        resp.set_cookie(
            "auth_ok",
            "yes",
            httponly=True,
            samesite="Lax"
        )
        return resp
    else:
        return render_lock_page(error_msg="Incorrect PIN")


@app.route("/lock", methods=["POST"])
def relock():
    """
    User presses "Lock Panel".
    Clear auth cookie and show PIN screen again.
    """
    resp = make_response(render_lock_page(error_msg="Panel locked. Enter PIN again."))
    resp.set_cookie(
        "auth_ok",
        "",
        httponly=True,
        samesite="Lax"
    )
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
    Called by auto-refresh JS on the main page.
    Also PIN-protected.
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


@app.route("/calendar", methods=["GET"])
def calendar_page():
    """
    Show the scheduling calendar (read-only).
    PIN-protected with the same cookie logic.
    """
    if not is_authorized(request):
        return render_lock_page()
    return render_calendar_page()


@app.route("/events.json", methods=["GET"])
def events_feed():
    """
    Returns scheduled events for FullCalendar (read-only).
    Calls the EEG scheduling API:
    GET /events?duration_start=...&duration_end=...&calculate_recurrences=true

    We also try to pull SUMMARY and DESCRIPTION from ICS so we can show
    nicer details on hover and click.
    """
    if not is_authorized(request):
        return jsonify({"error": "locked"}), 403

    start_str = request.args.get("start")
    end_str = request.args.get("end")
    if not start_str or not end_str:
        return jsonify([])

    def parse_iso_loose(s):
        # remove trailing 'Z' if present because fromisoformat can't handle 'Z'
        s = (s or "").replace("Z", "")
        # fromisoformat gives naive datetime (no tz)
        return datetime.datetime.fromisoformat(s)

    tz = pytz.timezone("Australia/Sydney")
    try:
        start_dt_local = tz.localize(parse_iso_loose(start_str))
        end_dt_local   = tz.localize(parse_iso_loose(end_str))
    except Exception:
        return jsonify([])

    start_ts = int(start_dt_local.timestamp())
    end_ts   = int(end_dt_local.timestamp())

    params = {
        "duration_start": start_ts,
        "duration_end": end_ts,
        "calculate_recurrences": "true"
    }

    try:
        resp = requests.get(
            SCHED_BASE,
            params=params,
            auth=(API_USERNAME, API_KEY),
            headers={"Accept": "application/json"},
            timeout=10,
        )
    except Exception:
        return jsonify([])

    if not resp.ok:
        return jsonify([])

    data = resp.json()
    cal_events = []

    for ev in data.get("events", []):
        ics = ev.get("ics", "") or ""

        # Defaults
        title = "LEXI Booking"
        description = ""

        # Try SUMMARY:
        if "SUMMARY:" in ics:
            try:
                after = ics.split("SUMMARY:", 1)[1]
                title_line = after.split("\r\n", 1)[0]
                if title_line.strip():
                    title = title_line.strip()
            except Exception:
                pass

        # Try DESCRIPTION:
        if "DESCRIPTION:" in ics:
            try:
                after_d = ics.split("DESCRIPTION:", 1)[1]
                desc_line = after_d.split("\r\n", 1)[0]
                if desc_line.strip():
                    description = desc_line.strip()
            except Exception:
                pass

        # Helper to extract DTSTART/DTEND with TZID=Australia/Sydney
        def extract_dt(tag):
            marker = f"{tag};TZID=Australia/Sydney:"
            if marker in ics:
                try:
                    raw = ics.split(marker, 1)[1].split("\r\n", 1)[0].strip()
                    dt_naive = datetime.datetime.strptime(raw, "%Y%m%dT%H%M%S")
                    return tz.localize(dt_naive)
                except Exception:
                    return None
            return None

        start_dt = extract_dt("DTSTART")
        end_dt   = extract_dt("DTEND")

        # Fallback to API-provided epoch times if ICS parse fails
        if not start_dt:
            start_epoch = ev.get("start_time")
            if start_epoch is not None:
                start_dt = datetime.datetime.fromtimestamp(start_epoch, tz)

        if not end_dt:
            end_epoch = ev.get("end_time")
            if end_epoch is not None:
                end_dt = datetime.datetime.fromtimestamp(end_epoch, tz)

        # If still missing, skip this event
        if not start_dt or not end_dt:
            continue

        cal_events.append({
            "title": title,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "extendedProps": {
                "description": description
            }
        })

    return jsonify(cal_events)


# -------------------
# ENTRY POINT
# -------------------

if __name__ == "__main__":
    # Local dev. On Render, Gunicorn will serve app, so this won't run.
    app.run(host="0.0.0.0", port=8080)
