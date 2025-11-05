import os
import datetime
import pytz
import requests
from flask import Flask, request, abort, jsonify, redirect, make_response, url_for
from markupsafe import escape

# -------------------
# CONFIG & SETUP
# -------------------

# Base URLs
EEG_BASE = "https://www.eegcloud.tv/speech-recognition/live/v2"   # Control API base (turn_on / turn_off / status)
SCHED_BASE = "https://www.eegcloud.tv/events"                      # Scheduling API base (calendar events)

# Default (legacy) instance ID – used only as a last‑resort fallback
DEFAULT_INSTANCE_ID = os.environ.get("DEFAULT_INSTANCE_ID", "asr_instance_EUwk84qjnygKawQK")

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
# MULTI‑INSTANCE SUPPORT
# -------------------

# Tiny in‑memory cache so we don't hit /instances on every page draw
_instances_cache = {"ts": 0, "data": []}


def fetch_all_instances(force: bool = False):
    """
    Hit /instances and return a list of {"id", "name"} dicts, sorted by name.
    Uses ?get_history=0 to keep payload small. Caches for ~60s.
    """
    now_ts = datetime.datetime.now().timestamp()
    if (not force) and _instances_cache["data"] and (now_ts - _instances_cache["ts"] < 60):
        return _instances_cache["data"]

    if not API_KEY:
        return []

    url = f"{EEG_BASE}/instances?get_history=0"
    try:
        resp = requests.get(
            url,
            auth=(API_USERNAME, API_KEY),
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if not resp.ok:
            return []
        raw = resp.json() or {}
    except Exception:
        return []

    items = []
    for inst in raw.get("all_instances", []):
        iid = inst.get("instance_id")
        name = (inst.get("settings", {}) or {}).get("name") or iid
        if iid:
            items.append({"id": iid, "name": name})

    items.sort(key=lambda x: x["name"].lower())
    _instances_cache["data"] = items
    _instances_cache["ts"] = now_ts
    return items


def current_instance_id(req: request):
    """
    Determine the active instance:
      1) cookie 'instance_id' if present
      2) first result from /instances
      3) DEFAULT_INSTANCE_ID as a last resort
    """
    cid = req.cookies.get("instance_id")
    if cid:
        return cid

    instances = fetch_all_instances()
    if instances:
        return instances[0]["id"]

    return DEFAULT_INSTANCE_ID


# -------------------
# EEG HELPERS
# -------------------

def fetch_instance_info():
    """
    Fetch info about all instances, then return the dict for the currently
    selected instance. Uses /speech-recognition/live/v2/instances?get_history=0
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

    data = resp.json() or {}
    active_id = current_instance_id(request)

    for inst in data.get("all_instances", []):
        if inst.get("instance_id") == active_id:
            return inst
    return None


def eeg_status():
    """
    Returns (instance_name, instance_state).
    """
    info = fetch_instance_info()
    if not info:
        # Attempt to show something graceful even if nothing resolved
        return ("(No instance found)", "UNKNOWN")

    instance_name = (info.get("settings", {}) or {}).get("name", "Unknown instance")
    instance_state = info.get("state", "UNKNOWN")
    return (instance_name, instance_state)


def eeg_post(action):
    """
    Call /turn_on or /turn_off for our selected instance.
    Returns (ok:boolean, msg:str).
    """
    if action not in ("turn_on", "turn_off"):
        abort(400, "Invalid action")

    if not API_KEY:
        abort(500, "EEG_API_KEY is not set on the server")

    cid = current_instance_id(request)
    url = f"{EEG_BASE}/instances/{cid}/{action}"
    try:
        resp = requests.post(
            url,
            auth=(API_USERNAME, API_KEY),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={},  # body can be empty (you can add initialization_origin/reason if desired)
            timeout=12,
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


# -------------------
# SCHEDULING / UPCOMING
# -------------------

def render_upcoming_page():
    """
    Read-only Upcoming Jobs view.
    Shows all future jobs (next 30 days for now) in a scrollable table.
    """
    upcoming = get_upcoming_events()

    if upcoming:
        rows_html = ""
        for row in upcoming:
            date_str = row.get("date_str", "")
            time_str = row.get("time_str", "")
            title    = row.get("title", "")
            desc     = row.get("description", "")

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
                <td style="padding:8px 10px; border-bottom:1px solid #eee;">
                    {escape(desc)}
                </td>
            </tr>
            """
    else:
        rows_html = """
        <tr>
            <td colspan="4" style="padding:12px; text-align:center; color:#666;">
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
                vertical-align:top;
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
                            <th style="width:25%;">Date</th>
                            <th style="width:25%;">Time</th>
                            <th style="width:25%;">Event</th>
                            <th style="width:25%;">Description</th>
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
    a list of dicts with display fields.
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
            timeout=12,
        )
    except Exception:
        return []

    if not resp.ok:
        return []

    data = resp.json() or {}
    rows = []

    for ev in data.get("events", []):
        ics = ev.get("ics", "") or ""

        title = "LEXI Booking"
        description = ""

        if "SUMMARY:" in ics:
            try:
                after = ics.split("SUMMARY:", 1)[1]
                title_line = after.split("\r\n", 1)[0]
                if title_line.strip():
                    title = title_line.strip()
            except Exception:
                pass

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

        if not start_dt:
            st_epoch = ev.get("start_time")
            if st_epoch is not None:
                start_dt = datetime.datetime.fromtimestamp(st_epoch, tz)
        if not end_dt:
            en_epoch = ev.get("end_time")
            if en_epoch is not None:
                end_dt = datetime.datetime.fromtimestamp(en_epoch, tz)

        if not start_dt or not end_dt:
            continue

        date_str = start_dt.strftime("%d/%b/%Y").upper()
        time_str = f"{start_dt.strftime('%H:%M')} – {end_dt.strftime('%H:%M')}"

        rows.append({
            "date_str": date_str,
            "time_str": time_str,
            "title": title,
            "description": description,
        })

    return rows


# -------------------
# HTML RENDER HELPERS
# -------------------

def render_lock_page(error_msg=None):
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
    instance_name, instance_state = eeg_status()
    badge_color = pick_badge_color(instance_state)

    # Build instance selector (appears above the state)
    instances = fetch_all_instances()
    selector_html = "<form method='post' action='/set_instance'>"
    selector_html += "<label style=\"margin-right:6px;color:#666;\">Instance:</label>"
    selector_html += "<select name='instance_id' onchange='this.form.submit()' style='padding:6px;'>"

    cid = current_instance_id(request)
    for inst in instances:
        selected = "selected" if inst["id"] == cid else ""
        selector_html += f"<option value='{inst['id']}' {selected}>{escape(inst['name'])}</option>"

    selector_html += "</select></form>"

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
            }} catch (e) {{}}
        }}
        setInterval(refreshStatus, 10000);
        window.addEventListener('load', refreshStatus);
        </script>
    </head>

    <body style="font-family:sans-serif; max-width:460px; margin:40px auto; text-align:center; color:#222;">

        <h1 style="margin-bottom:0.5em;">Lexi Live Control</h1>

        <div style="margin-bottom:12px;">{selector_html}</div>

        <p style="color:#666;margin:0 0 1em 0;">Active:
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


# -------------------
# CALENDAR PAGE (unchanged other than imports)
# -------------------

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
                position: relative;
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
                const d = new Date(isoStr);
                const pad = n => n.toString().padStart(2,'0');
                const day = pad(d.getDate());
                const mon = d.toLocaleString('en-AU', {{ month: 'short' }});
                const yr  = d.getFullYear();
                const hr  = pad(d.getHours());
                const min = pad(d.getMinutes());
                return day + ' ' + mon + ' ' + yr + ' ' + hr + ':' + min;
            }}
            function showTooltip(jsEvent, html) {{
                tooltipEl.innerHTML = html;
                tooltipEl.style.display = 'block';
                tooltipEl.style.left = (jsEvent.pageX + 10) + 'px';
                tooltipEl.style.top  = (jsEvent.pageY + 10) + 'px';
            }}
            function hideTooltip() {{ tooltipEl.style.display = 'none'; }}

            var calEl = document.getElementById('calendar');
            var calendar = new FullCalendar.Calendar(calEl, {{
                initialView: 'dayGridMonth',
                timeZone: 'Australia/Sydney',
                height: 'auto',
                headerToolbar: {{ left: 'prev,next today', center: 'title', right: 'dayGridMonth,timeGridWeek,timeGridDay' }},
                eventTimeFormat: {{ hour: '2-digit', minute: '2-digit', hour12: false }},
                slotLabelFormat: {{ hour: '2-digit', minute: '2-digit', hour12: false }},
                events: function(fetchInfo, successCallback, failureCallback) {{
                    const params = new URLSearchParams({{ start: fetchInfo.startStr, end: fetchInfo.endStr }});
                    fetch('/events.json?' + params, {{ credentials: 'include' }})
                      .then(r => r.json())
                      .then(data => {{
                        if (data.error === 'locked') {{
                            alert('Session locked. Please re-enter PIN.');
                            window.location = '/';
                            return;
                        }}
                        successCallback(data);
                      }})
                      .catch(err => failureCallback(err));
                }},
                eventDidMount: function(info) {{
                    info.el.removeAttribute('title');
                    info.el.addEventListener('mouseenter', function(ev) {{
                        const title = info.event.title || '(no title)';
                        const startStr = fmtDateTime(info.event.startStr);
                        const endStr   = info.event.endStr ? fmtDateTime(info.event.endStr) : '';
                        let tipHtml = '<strong>' + title + '</strong><br/>' + startStr;
                        if (endStr) {{ tipHtml += ' → ' + endStr; }}
                        showTooltip(ev, tipHtml);
                    }});
                    info.el.addEventListener('mousemove', function(ev) {{
                        if (tooltipEl.style.display === 'block') {{
                            tooltipEl.style.left = (ev.pageX + 10) + 'px';
                            tooltipEl.style.top  = (ev.pageY + 10) + 'px';
                        }}
                    }});
                    info.el.addEventListener('mouseleave', function() { hideTooltip(); });
                }},
                eventClick: function(info) {{
                    info.jsEvent.preventDefault();
                    const title = info.event.title || '(no title)';
                    const startStr = fmtDateTime(info.event.startStr);
                    const endStr   = info.event.endStr ? fmtDateTime(info.event.endStr) : '';
                    const desc = info.event.extendedProps && info.event.extendedProps.description ? info.event.extendedProps.description : '';
                    let msg = title + "\n" + startStr;
                    if (endStr) {{ msg += ' → ' + endStr; }}
                    if (desc)  {{ msg += "\n\n" + desc; }}
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
    if not is_authorized(request):
        return render_lock_page()
    return render_home()


@app.route("/set_instance", methods=["POST"])
def set_instance():
    if not is_authorized(request):
        return render_lock_page("Please enter PIN first.")

    iid = request.form.get("instance_id", "").strip()
    instances = fetch_all_instances()
    if not any(i["id"] == iid for i in instances):
        # If somehow invalid, just go home
        return redirect(url_for("home"))

    resp = make_response(redirect(url_for("home")))
    resp.set_cookie("instance_id", iid, httponly=True, samesite="Lax")
    return resp


@app.route("/upcoming", methods=["GET"])
def upcoming_page():
    if not is_authorized(request):
        return redirect("/lock")
    return render_upcoming_page()


@app.route("/unlock", methods=["POST"])
def unlock():
    submitted_pin = request.form.get("pin", "").strip()
    if check_pin(submitted_pin):
        resp = make_response(redirect("/"))
        resp.set_cookie("auth_ok", "yes", httponly=True, samesite="Lax")
        return resp
    else:
        return render_lock_page(error_msg="Incorrect PIN")


@app.route("/lock", methods=["POST"])
def relock():
    resp = make_response(render_lock_page(error_msg="Panel locked. Enter PIN again."))
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
    if not is_authorized(request):
        return jsonify({"error": "locked"}), 403

    name, state = eeg_status()
    return jsonify({
        "name": name,
        "state": state,
        "badge_color": pick_badge_color(state),
    })


@app.route("/calendar", methods=["GET"])
def calendar_page():
    if not is_authorized(request):
        return render_lock_page()
    return render_calendar_page()


@app.route("/events.json", methods=["GET"])
def events_feed():
    if not is_authorized(request):
        return jsonify({"error": "locked"}), 403

    start_str = request.args.get("start")
    end_str = request.args.get("end")
    if not start_str or not end_str:
        return jsonify([])

    def parse_iso_loose(s):
        s = (s or "").replace("Z", "")
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
            timeout=12,
        )
    except Exception:
        return jsonify([])

    if not resp.ok:
        return jsonify([])

    data = resp.json() or {}
    cal_events = []

    for ev in data.get("events", []):
        ics = ev.get("ics", "") or ""

        title = "LEXI Booking"
        description = ""

        if "SUMMARY:" in ics:
            try:
                after = ics.split("SUMMARY:", 1)[1]
                title_line = after.split("\r\n", 1)[0]
                if title_line.strip():
                    title = title_line.strip()
            except Exception:
                pass

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

        if not start_dt:
            start_epoch = ev.get("start_time")
            if start_epoch is not None:
                start_dt = datetime.datetime.fromtimestamp(start_epoch, tz)
        if not end_dt:
            end_epoch = ev.get("end_time")
            if end_epoch is not None:
                end_dt = datetime.datetime.fromtimestamp(end_epoch, tz)

        if not start_dt or not end_dt:
            continue

        cal_events.append({
            "title": title,
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "extendedProps": {"description": description}
        })

    return jsonify(cal_events)


# -------------------
# ENTRY POINT
# -------------------

if __name__ == "__main__":
    # Local dev. On Render, Gunicorn will serve app, so this won't run.
    app.run(host="0.0.0.0", port=8080)
