#!/usr/bin/env python3
"""Trend Map serveris: nuolatinis duomenų rinkimas pagal grafiką + svetainė su prisijungimu.

Visa būsena laikoma /data (TRENDMAP_HOME):
  config/      profile.md, creators.yml, sources.yml, settings.yml (redaguojami)
  data/        surinkti įrašai, temos, analizė
  site/        sugeneruota svetainė ir archyvas
  reports/     savaitinės markdown ataskaitos
  secrets.json API raktai (tik serveryje)
  auth.json    slaptažodžio maišos reikšmė
  state.json   paskutinių paleidimų laikas
"""
import hashlib
import hmac
import html
import json
import os
import secrets as pysecrets
import shutil
import sys
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

APP = Path(__file__).resolve().parent
HOME = Path(os.environ.get("TRENDMAP_HOME", "/data"))
for sub in ("config", "data", "site", "reports"):
    (HOME / sub).mkdir(parents=True, exist_ok=True)
os.environ.update({
    "TRENDMAP_CONFIG_DIR": str(HOME / "config"),
    "TRENDMAP_DATA_DIR": str(HOME / "data"),
    "TRENDMAP_DOCS_DIR": str(HOME / "site"),
    "TRENDMAP_REPORTS_DIR": str(HOME / "reports"),
    "TRENDMAP_SERVER": "1",
})
# pradiniai konfigūracijos failai, jei jų dar nėra
for f in (APP / "config").glob("*"):
    if not (HOME / "config" / f.name).exists():
        shutil.copy(f, HOME / "config" / f.name)
        if f.name == "profile.md" and os.environ.get("PROFILE_SEED", "").strip():
            (HOME / "config" / f.name).write_text(os.environ["PROFILE_SEED"].strip() + "\n", encoding="utf-8")

sys.path.insert(0, str(APP))
from trendmap import analyze, build_site, collect_instagram, collect_portals, ideas, label  # noqa: E402
from trendmap.common import creators, normalize_handle, save_creators  # noqa: E402

TZ = ZoneInfo(os.environ.get("TZ", "Europe/Vilnius"))
PORT = int(os.environ.get("PORT", "8080"))
SECRETS = HOME / "secrets.json"
AUTH = HOME / "auth.json"
STATE = HOME / "state.json"
LOGFILE = HOME / "log.txt"

SCHEDULE = {  # valandos tarp paleidimų
    "portals": float(os.environ.get("EVERY_PORTALS_H", 3)),
    "instagram": float(os.environ.get("EVERY_INSTAGRAM_H", 24)),
    "report": float(os.environ.get("EVERY_REPORT_H", 24)),
}
IDEAS_WEEKDAY = int(os.environ.get("IDEAS_WEEKDAY", 0))  # 0 = pirmadienis
IDEAS_HOUR = int(os.environ.get("IDEAS_HOUR", 7))

LOG = deque(maxlen=400)
JOB_LOCK = threading.Lock()
RUNNING = {"job": None, "since": None}


# ---------- pagalbinės ----------

def jload(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def jsave(p, obj, private=False):
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    if private:
        os.chmod(tmp, 0o600)
    tmp.replace(p)


def now():
    return datetime.now(timezone.utc)


def log(msg):
    line = f"{datetime.now(TZ).strftime('%m-%d %H:%M:%S')}  {msg}"
    LOG.append(line)
    print(line, file=sys.__stdout__, flush=True)
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if LOGFILE.stat().st_size > 2_000_000:
            lines = LOGFILE.read_text(encoding="utf-8").splitlines()[-3000:]
            LOGFILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


class _Tee:
    """Nukreipia trendmap modulių print() į žurnalą."""
    def write(self, s):
        for line in s.rstrip().splitlines():
            if line.strip():
                log("  " + line.strip())

    def flush(self):
        pass


def load_secrets_into_env():
    s = jload(SECRETS, {})
    for k in ("ANTHROPIC_API_KEY", "APIFY_TOKEN", "IG_USER_ID", "IG_ACCESS_TOKEN"):
        if s.get(k):
            os.environ[k] = s[k]
        else:
            os.environ.pop(k, None)
    return s


# ---------- darbai ----------

def job_portals():
    collect_portals.collect()


def job_instagram():
    return collect_instagram.collect()


def job_report():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log("Ataskaita praleista: nenustatytas Claude API raktas (Nustatymai).")
        return False
    label.label_new()
    analyze.analyze()
    state = jload(STATE, {})
    if ideas_due(state) or not (HOME / "data" / "ideas_current.json").exists():
        a = jload(HOME / "data" / "analysis.json", {})
        ideas.generate(a)
        state = jload(STATE, {})
        state["ideas"] = now().isoformat()
        jsave(STATE, state)
    build_site.build()
    return True


def job_ideas():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log("Idėjos praleistos: nenustatytas Claude API raktas.")
        return False
    a = analyze.analyze()
    ideas.generate(a)
    build_site.build()
    state = jload(STATE, {})
    state["ideas"] = now().isoformat()
    jsave(STATE, state)
    return True


JOBS = {"portals": job_portals, "instagram": job_instagram, "report": job_report, "ideas": job_ideas}
JOB_NAMES = {"portals": "Portalų surinkimas", "instagram": "Instagram surinkimas",
             "report": "Analizė ir svetainė", "ideas": "Naujos idėjos"}


def ideas_due(state):
    last = state.get("ideas")
    if not last:
        return True
    last = datetime.fromisoformat(last).astimezone(TZ)
    local = datetime.now(TZ)
    # paskutinis planuotas idėjų laikas
    days_back = (local.weekday() - IDEAS_WEEKDAY) % 7
    slot = (local - timedelta(days=days_back)).replace(hour=IDEAS_HOUR, minute=0, second=0, microsecond=0)
    if slot > local:
        slot -= timedelta(days=7)
    return last < slot


def run_job(name, reason="grafikas"):
    if not JOB_LOCK.acquire(blocking=False):
        return False
    RUNNING.update(job=name, since=now().isoformat())
    old_out = sys.stdout
    sys.stdout = _Tee()
    ok = True
    try:
        load_secrets_into_env()
        log(f"▶ {JOB_NAMES[name]} ({reason})")
        t0 = time.time()
        res = JOBS[name]()
        ok = res is not False
        log(f"✓ {JOB_NAMES[name]} baigta per {time.time() - t0:.0f} s" if ok else f"– {JOB_NAMES[name]} praleista")
    except BaseException as e:  # noqa: BLE001
        ok = False
        sys.stdout = old_out
        log(f"✗ {JOB_NAMES[name]}: {e}")
        traceback.print_exc(file=sys.__stderr__)
    finally:
        sys.stdout = old_out
        state = jload(STATE, {})
        state[f"{name}_last"] = now().isoformat()
        state[f"{name}_ok"] = ok
        jsave(STATE, state)
        RUNNING.update(job=None, since=None)
        JOB_LOCK.release()
    return True


def run_chain(names, reason):
    def go():
        for n in names:
            while JOB_LOCK.locked():
                time.sleep(2)
            run_job(n, reason)
    threading.Thread(target=go, daemon=True).start()


def scheduler():
    time.sleep(5)
    while True:
        try:
            state = jload(STATE, {})
            due = []
            for name, hours in SCHEDULE.items():
                last = state.get(f"{name}_last")
                if not last or now() - datetime.fromisoformat(last) >= timedelta(hours=hours):
                    due.append(name)
            if "report" not in due and ideas_due(state) and os.environ.get("ANTHROPIC_API_KEY"):
                due.append("ideas")
            for name in ("portals", "instagram", "report", "ideas"):
                if name in due:
                    run_job(name)
        except Exception as e:  # noqa: BLE001
            log(f"Planuoklio klaida: {e}")
        time.sleep(60)


# ---------- Meta / Instagram prijungimas ----------

def meta_connect(data):
    import requests
    ver = os.environ.get("META_GRAPH_VERSION", "v23.0")
    app_id, secret, token = (data.get(k, "").strip() for k in ("app_id", "app_secret", "token"))
    if not (app_id and secret and token):
        raise ValueError("Užpildyk visus tris laukus.")
    g = f"https://graph.facebook.com/{ver}"

    def call(url, params):
        r = requests.get(url, params=params, timeout=30).json()
        if "error" in r:
            raise ValueError("Meta atsakė: " + r["error"].get("message", "nežinoma klaida"))
        return r

    long_lived = call(f"{g}/oauth/access_token", {
        "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": secret,
        "fb_exchange_token": token})["access_token"]
    pages = call(f"{g}/me/accounts", {"fields": "name,access_token,instagram_business_account{id,username}",
                                      "access_token": long_lived, "limit": 50}).get("data", [])
    page = next((p for p in pages if p.get("instagram_business_account")), None)
    if not page:
        raise ValueError("Neradau Facebook puslapio su prijungta Instagram paskyra. Patikrink, ar Instagram "
                         "paskyra yra Creator/Business ir susieta su Facebook puslapiu, o generuodamas raktą "
                         "pažymėjai tą puslapį.")
    ig = page["instagram_business_account"]
    # patikrinimas su vienu stebimu kūrėju
    test = creators()[0] if creators() else ig.get("username")
    check = requests.get(f"{g}/{ig['id']}", params={
        "fields": f"business_discovery.username({test}){{username,media_count}}",
        "access_token": page["access_token"]}, timeout=30).json()
    s = jload(SECRETS, {})
    s.update({"IG_USER_ID": ig["id"], "IG_ACCESS_TOKEN": page["access_token"],
              "IG_ACCOUNT": ig.get("username", "")})
    s.pop("APIFY_TOKEN", None)
    jsave(SECRETS, s, private=True)
    log(f"Instagram prijungtas per @{ig.get('username')} (puslapis {page.get('name')})")
    if "error" in check:
        note = f" Bandomasis @{test} patikrinimas nepavyko: {check['error'].get('message')}"
    else:
        note = f" Patikrinta: @{test} matomas."
    run_chain(["instagram", "report"], "prijungtas Instagram")
    return {"ok": True, "message": f"Prijungta per @{ig.get('username')}.{note} Surinkimas jau paleistas."}


# ---------- prisijungimas ----------

def hash_pw(pw, salt=None):
    salt = salt or pysecrets.token_hex(16)
    h = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1).hex()
    return salt, h


def check_pw(pw):
    a = jload(AUTH, None)
    if not a:
        return False
    return hmac.compare_digest(hash_pw(pw, a["salt"])[1], a["hash"])


def session_key():
    a = jload(AUTH, None)
    return (a or {}).get("session_key", "")


def make_cookie():
    exp = int(time.time()) + 60 * 60 * 24 * 30
    sig = hmac.new(session_key().encode(), str(exp).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def valid_cookie(val):
    try:
        exp, sig = val.split(".", 1)
        if int(exp) < time.time() or not session_key():
            return False
        good = hmac.new(session_key().encode(), exp.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, good)
    except (ValueError, AttributeError):
        return False


FAILED = {}


# ---------- puslapiai ----------

BASE_CSS = """
:root{--paper:#f3f0e8;--card:#fbfaf6;--ink:#16150f;--ink-2:#4a473f;--muted:#7a766b;--line:#dcd7ca;--line-2:#ebe7dd;--accent:#e8501a;--ok:#2d7a3e;--bad:#c23b2a;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#15140f;--card:#1d1c17;--ink:#f1eee6;--ink-2:#c9c5b9;--muted:#8f8a7d;--line:#34322a;--line-2:#26241e;--accent:#ff6a35;--ok:#5bbf6e;--bad:#ec6a58;color-scheme:dark}}
:root[data-theme="dark"]{--paper:#15140f;--card:#1d1c17;--ink:#f1eee6;--ink-2:#c9c5b9;--muted:#8f8a7d;--line:#34322a;--line-2:#26241e;--accent:#ff6a35;--ok:#5bbf6e;--bad:#ec6a58;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 "Inter Tight",system-ui,sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:32px 16px 80px}
h1{font:400 52px/1 "Instrument Serif",Georgia,serif;margin:10px 0 24px}h2{font:400 30px/1.1 "Instrument Serif",Georgia,serif;margin:0 0 8px}
.eyebrow,.lbl{font:500 11px/1 "JetBrains Mono",monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin-bottom:16px}
.card p{color:var(--ink-2);margin:0 0 12px}
input,textarea{font:inherit;color:inherit;width:100%;border:1px solid var(--line);background:var(--paper);border-radius:8px;padding:9px 12px}
textarea{min-height:320px;font:13.5px/1.55 "JetBrains Mono",monospace}
label{display:block;margin:12px 0 4px;font-size:13px;color:var(--ink-2)}
.btn{border:0;background:var(--ink);color:var(--paper);border-radius:8px;padding:9px 16px;font:600 14px inherit;cursor:pointer}
.btn:hover{background:var(--accent)}.btn.sec{background:none;color:var(--ink);border:1px solid var(--line)}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:12px}
.jobs{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:8px}
.job{border:1px solid var(--line);border-radius:8px;padding:10px 12px;font-size:13px}
.job b{display:block;font-size:14px;margin-bottom:2px}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;vertical-align:middle}
pre{background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:12px;font:12px/1.5 "JetBrains Mono",monospace;max-height:340px;overflow:auto;white-space:pre-wrap;margin:0}
nav{display:flex;gap:16px;align-items:center;font-size:14px}nav a{color:var(--ink-2)}
.keyset{color:var(--ok);font-size:12px}.keymiss{color:var(--bad);font-size:12px}
.msg{padding:10px 14px;border-radius:8px;background:var(--line-2);margin-bottom:12px;font-size:14px}
.err{color:var(--bad);font-size:14px;margin-top:8px}
"""
FONTS = ('<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=Inter+Tight:wght@400;600'
         '&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">')


def page(title, body):
    return f"""<!doctype html><html lang="lt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>{FONTS}
<style>{BASE_CSS}</style></head><body><div class="wrap">{body}</div></body></html>"""


def login_page(err=""):
    return page("Prisijungti · Trend Map", f"""
<div style="max-width:380px;margin:12vh auto 0"><div class="eyebrow">Trend Map</div><h1>Prisijungti</h1>
<form method="post" action="/login" class="card">
<label for="pw">Slaptažodis</label><input id="pw" type="password" name="password" autofocus autocomplete="current-password">
{f'<div class="err">{html.escape(err)}</div>' if err else ''}
<div class="row"><button class="btn">Prisijungti</button></div></form></div>""")


def setup_page(code, err=""):
    return page("Pradžia · Trend Map", f"""
<div style="max-width:420px;margin:10vh auto 0"><div class="eyebrow">Trend Map · pirmas kartas</div><h1>Susikurk slaptažodį</h1>
<form method="post" action="/setup" class="card"><p>Šiuo slaptažodžiu jungsiesi prie savo Trend Map. Bent 10 simbolių.</p>
<input type="hidden" name="code" value="{html.escape(code)}">
<label for="p1">Slaptažodis</label><input id="p1" type="password" name="password" autocomplete="new-password" autofocus>
<label for="p2">Pakartok</label><input id="p2" type="password" name="password2" autocomplete="new-password">
{f'<div class="err">{html.escape(err)}</div>' if err else ''}
<div class="row"><button class="btn">Išsaugoti</button></div></form></div>""")


def fmt_time(iso):
    if not iso:
        return "dar nebuvo"
    return datetime.fromisoformat(iso).astimezone(TZ).strftime("%m-%d %H:%M")


def settings_page():
    s = jload(SECRETS, {})
    state = jload(STATE, {})
    profile = (HOME / "config" / "profile.md").read_text(encoding="utf-8")

    def keyline(k, title, hint):
        st = '<span class="keyset">● nustatytas</span>' if s.get(k) else '<span class="keymiss">● nenustatytas</span>'
        return (f'<label for="{k}">{title} {st}</label>'
                f'<input id="{k}" name="{k}" type="password" autocomplete="off" placeholder="{html.escape(hint)}">')

    if s.get("IG_ACCESS_TOKEN") and s.get("IG_USER_ID"):
        ig_status = (f'<p><span class="keyset">● prijungta</span> per @{html.escape(s.get("IG_ACCOUNT", "?"))}. '
                     'Kitų kūrėjų įrašai renkami per šią paskyrą.</p>')
    elif s.get("APIFY_TOKEN"):
        ig_status = '<p><span class="keyset">● naudojamas Apify</span></p>'
    else:
        ig_status = '<p><span class="keymiss">● neprijungta</span></p>'
    jobs = ""
    for name in ("portals", "instagram", "report", "ideas"):
        last = state.get(f"{name}_last") if name != "ideas" else state.get("ideas")
        ok = state.get(f"{name}_ok", True)
        color = "var(--muted)" if not last else ("var(--ok)" if ok else "var(--bad)")
        every = {"portals": f"kas {SCHEDULE['portals']:g} val.", "instagram": f"kas {SCHEDULE['instagram']:g} val.",
                 "report": f"kas {SCHEDULE['report']:g} val.", "ideas": "pirmadieniais"}[name]
        jobs += (f'<div class="job"><b><span class="dot" style="background:{color}"></span>{JOB_NAMES[name]}</b>'
                 f'<span style="color:var(--muted)">{every} · paskutinis {fmt_time(last)}</span>'
                 f'<div class="row" style="margin-top:8px"><button class="btn sec" data-run="{name}">Paleisti dabar</button></div></div>')
    return page("Nustatymai · Trend Map", f"""
<nav><a href="/">← Ataskaita</a><span style="flex:1"></span><a href="/logout">Atsijungti</a></nav>
<div class="eyebrow" style="margin-top:28px">Trend Map</div><h1>Nustatymai</h1>
<div id="msg"></div>

<div class="card"><h2>Grafikas</h2><p>Serveris viską daro pats. Čia gali paleisti bet kurį žingsnį iškart.</p>
<div class="jobs">{jobs}</div>
<div class="row"><button class="btn" data-run="all">Paleisti viską iš eilės</button><span id="running" style="color:var(--muted);font-size:13px"></span></div></div>

<div class="card"><h2>API raktai</h2><p>Saugomi tik šiame serveryje. Tuščias laukas palieka esamą reikšmę.</p>
<form id="keys">
{keyline("ANTHROPIC_API_KEY", "Claude API raktas", "sk-ant-…  (console.anthropic.com → API Keys)")}
{keyline("APIFY_TOKEN", "Apify raktas (Instagram)", "apify_api_…  (apify.com → Settings → API & Integrations)")}
<div class="row"><button class="btn">Išsaugoti raktus</button></div></form></div>

<div class="card"><h2>Instagram (nemokamai, per Meta)</h2>
{ig_status}
<p>Reikia Instagram Creator ar Business paskyros, susietos su Facebook puslapiu, ir Meta programėlės.
Įklijuok tris reikšmes iš Meta. Serveris pats gaus nesibaigiantį raktą ir rastų tavo Instagram paskyrą.
Programėlės slaptasis raktas naudojamas tik vieną kartą ir neišsaugomas.</p>
<form id="meta">
<label for="app_id">App ID</label><input id="app_id" name="app_id" autocomplete="off" placeholder="App settings → Basic → App ID">
<label for="app_secret">App Secret</label><input id="app_secret" name="app_secret" type="password" autocomplete="off" placeholder="App settings → Basic → App secret → Show">
<label for="token">Laikinas raktas iš Graph API Explorer</label><input id="token" name="token" type="password" autocomplete="off" placeholder="EAA…">
<div class="row"><button class="btn">Prijungti Instagram</button></div></form></div>

<div class="card"><h2>Tavo pozicionavimas</h2><p>Claude pagal tai vertina, kurios temos tinka tau, ir rašo idėjas. Pakeitus, tinkamumas perskaičiuojamas.</p>
<form id="profile"><textarea name="text" spellcheck="false">{html.escape(profile)}</textarea>
<div class="row"><button class="btn">Išsaugoti</button></div></form></div>

<div class="card"><h2>Žurnalas</h2><pre id="log"></pre></div>

<div class="card"><h2>Slaptažodis</h2><form id="pw">
<label for="np">Naujas slaptažodis</label><input id="np" name="password" type="password" autocomplete="new-password">
<div class="row"><button class="btn sec">Pakeisti</button></div></form></div>

<script>
const H = {{"Content-Type":"application/json","X-Requested-With":"trendmap"}};
const msg = (t, bad) => {{ const m = document.getElementById("msg"); m.innerHTML = `<div class="msg" style="${{bad ? 'color:var(--bad)' : ''}}">${{t}}</div>`; scrollTo({{top:0,behavior:"smooth"}}); }};
async function post(url, body){{ const r = await fetch(url, {{method:"POST", headers:H, body:JSON.stringify(body)}}); const j = await r.json().catch(() => ({{}})); if (!r.ok) throw new Error(j.error || r.status); return j; }}
document.getElementById("keys").onsubmit = async e => {{ e.preventDefault(); const d = Object.fromEntries(new FormData(e.target));
  try {{ await post("/api/keys", d); msg("Raktai išsaugoti."); setTimeout(() => location.reload(), 900); }} catch(x) {{ msg("Klaida: " + x.message, 1); }} }};
document.getElementById("meta").onsubmit = async e => {{ e.preventDefault(); const d = Object.fromEntries(new FormData(e.target));
  msg("Jungiama…");
  try {{ const r = await post("/api/meta-connect", d); msg(r.message); e.target.reset(); setTimeout(() => location.reload(), 2500); }} catch(x) {{ msg("Nepavyko: " + x.message, 1); }} }};
document.getElementById("profile").onsubmit = async e => {{ e.preventDefault();
  try {{ await post("/api/profile", {{text: e.target.text.value}}); msg("Pozicionavimas išsaugotas. Tinkamumas bus perskaičiuotas per kitą analizę."); }} catch(x) {{ msg("Klaida: " + x.message, 1); }} }};
document.getElementById("pw").onsubmit = async e => {{ e.preventDefault();
  try {{ await post("/api/password", {{password: e.target.password.value}}); msg("Slaptažodis pakeistas."); e.target.reset(); }} catch(x) {{ msg("Klaida: " + x.message, 1); }} }};
document.querySelectorAll("[data-run]").forEach(b => b.onclick = async () => {{
  try {{ await post("/api/run", {{job: b.dataset.run}}); msg("Paleista. Eigą matysi žurnale."); poll(); }} catch(x) {{ msg("Klaida: " + x.message, 1); }} }});
async function poll(){{ try {{ const r = await fetch("/api/status", {{headers:H}}); const j = await r.json();
  const L = document.getElementById("log"); const atBottom = L.scrollTop + L.clientHeight >= L.scrollHeight - 20;
  L.textContent = j.log.join("\\n") || "Kol kas tuščia."; if (atBottom) L.scrollTop = L.scrollHeight;
  document.getElementById("running").textContent = j.running ? "Dabar vyksta: " + j.running : ""; }} catch(e) {{}} }}
poll(); setInterval(poll, 4000);
</script>""")


NO_REPORT = page("Trend Map", """
<div class="eyebrow">Trend Map</div><h1>Ataskaitos dar nėra</h1>
<div class="card"><p>Serveris veikia ir renka duomenis. Pirma ataskaita atsiras, kai nustatysi Claude API raktą ir praeis pirmas paleidimas.</p>
<div class="row"><a class="btn" href="/nustatymai" style="text-decoration:none">Į nustatymus</a></div></div>""")


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "TrendMap"

    def log_message(self, fmt, *args):
        pass

    # atsakymai
    def send(self, code, body, ctype="text/html; charset=utf-8", headers=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, to, headers=None):
        self.send(303, "", headers={"Location": to, **(headers or {})})

    def json(self, obj, code=200):
        self.send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def cookie(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "tm_session":
                return v
        return ""

    def authed(self):
        return valid_cookie(self.cookie())

    def body(self, limit=200_000):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("per didelė užklausa")
        return self.rfile.read(n).decode("utf-8") if n else ""

    def form(self):
        return {k: v[0] for k, v in parse_qs(self.body()).items()}

    def api_body(self):
        if self.headers.get("X-Requested-With") != "trendmap":
            raise PermissionError("csrf")
        return json.loads(self.body() or "{}")

    # GET
    def do_GET(self):
        path = urlparse(self.path).path
        q = parse_qs(urlparse(self.path).query)
        if path == "/healthz":
            return self.send(200, "ok", "text/plain")
        if not AUTH.exists():
            code = (q.get("code") or [""])[0]
            if path == "/setup" and code and hmac.compare_digest(code, os.environ.get("SETUP_CODE", "")):
                return self.send(200, setup_page(code))
            return self.send(200, page("Trend Map", '<div class="eyebrow">Trend Map</div><h1>Serveris veikia</h1>'
                                       '<div class="card"><p>Pirmam prisijungimui atidaryk nuorodą su pradžios kodu.</p></div>'))
        if path == "/login":
            return self.send(200, login_page())
        if path == "/logout":
            return self.redirect("/login", {"Set-Cookie": "tm_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})
        if not self.authed():
            if path.startswith("/api/"):
                return self.json({"error": "neprisijungta"}, 401)
            return self.redirect("/login")
        if path in ("/", "/index.html"):
            f = HOME / "site" / "index.html"
            return self.send(200, f.read_bytes()) if f.exists() else self.send(200, NO_REPORT)
        if path == "/nustatymai":
            return self.send(200, settings_page())
        if path == "/api/status":
            return self.json({"running": JOB_NAMES.get(RUNNING["job"]), "log": list(LOG)[-150:],
                              "state": jload(STATE, {})})
        if path.startswith("/snapshots/") and path.endswith(".json"):
            name = Path(path).name
            f = HOME / "site" / "snapshots" / name
            if f.exists() and f.parent == HOME / "site" / "snapshots":
                return self.send(200, f.read_bytes(), "application/json; charset=utf-8")
        return self.send(404, page("Nerasta", "<h1>Nerasta</h1>"))

    # POST
    def do_POST(self):
        path = urlparse(self.path).path
        ip = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()
        try:
            if path == "/setup":
                if AUTH.exists():
                    return self.redirect("/login")
                f = self.form()
                if not hmac.compare_digest(f.get("code", ""), os.environ.get("SETUP_CODE", "") or "\0"):
                    return self.send(403, "Neteisingas kodas", "text/plain; charset=utf-8")
                if len(f.get("password", "")) < 10:
                    return self.send(200, setup_page(f["code"], "Slaptažodis per trumpas (bent 10 simbolių)."))
                if f.get("password") != f.get("password2"):
                    return self.send(200, setup_page(f["code"], "Slaptažodžiai nesutampa."))
                salt, h = hash_pw(f["password"])
                jsave(AUTH, {"salt": salt, "hash": h, "session_key": pysecrets.token_hex(32)}, private=True)
                log("Slaptažodis sukurtas")
                return self.redirect("/nustatymai", {"Set-Cookie": self.session_cookie()})
            if path == "/login":
                fails = [t for t in FAILED.get(ip, []) if t > time.time() - 900]
                if len(fails) >= 8:
                    return self.send(429, login_page("Per daug bandymų. Pabandyk po 15 min."))
                if check_pw(self.form().get("password", "")):
                    FAILED.pop(ip, None)
                    return self.redirect("/", {"Set-Cookie": self.session_cookie()})
                FAILED[ip] = fails + [time.time()]
                time.sleep(1)
                return self.send(401, login_page("Neteisingas slaptažodis."))
            if not self.authed():
                return self.json({"error": "neprisijungta"}, 401)
            data = self.api_body()
            return self.api(path, data)
        except PermissionError:
            return self.json({"error": "draudžiama"}, 403)
        except (ValueError, json.JSONDecodeError) as e:
            return self.json({"error": str(e)}, 400)

    def session_cookie(self):
        return f"tm_session={make_cookie()}; Path=/; Max-Age=2592000; HttpOnly; SameSite=Strict"

    def api(self, path, data):
        if path == "/api/creators":
            current = creators()
            if data.get("add"):
                new = [h for h in (normalize_handle(x) for x in data["add"]) if h and h not in current]
                save_creators(current + new)
                log(f"Pridėti kūrėjai: {', '.join(new) or '–'}")
                if new:
                    run_chain(["instagram", "report"], "nauji kūrėjai")
                return self.json({"added": new, "creators": creators()})
            if data.get("remove"):
                h = normalize_handle(data["remove"])
                save_creators([c for c in current if c != h])
                log(f"Pašalintas kūrėjas: {h}")
                return self.json({"removed": h, "creators": creators()})
            raise ValueError("nėra ką keisti")
        if path == "/api/keys":
            s = jload(SECRETS, {})
            changed = []
            for k in ("ANTHROPIC_API_KEY", "APIFY_TOKEN", "IG_USER_ID", "IG_ACCESS_TOKEN"):
                v = (data.get(k) or "").strip()
                if v:
                    s[k] = v
                    changed.append(k)
            jsave(SECRETS, s, private=True)
            log(f"Atnaujinti raktai: {', '.join(changed) or '–'}")
            if "ANTHROPIC_API_KEY" in changed or "APIFY_TOKEN" in changed:
                run_chain(["instagram", "report"], "nauji raktai")
            return self.json({"ok": True})
        if path == "/api/meta-connect":
            return self.json(meta_connect(data))
        if path == "/api/profile":
            text = data.get("text", "")
            if not text.strip():
                raise ValueError("tuščias tekstas")
            (HOME / "config" / "profile.md").write_text(text, encoding="utf-8")
            topics = jload(HOME / "data" / "topics.json", {})
            for t in topics.values():
                t.pop("fit", None)
            if topics:
                jsave(HOME / "data" / "topics.json", topics)
            log("Pozicionavimas atnaujintas")
            return self.json({"ok": True})
        if path == "/api/password":
            pw = data.get("password", "")
            if len(pw) < 10:
                raise ValueError("Slaptažodis per trumpas (bent 10 simbolių)")
            salt, h = hash_pw(pw)
            jsave(AUTH, {"salt": salt, "hash": h, "session_key": session_key()}, private=True)
            return self.json({"ok": True})
        if path == "/api/run":
            job = data.get("job")
            names = ["portals", "instagram", "report"] if job == "all" else [job]
            if not all(n in JOBS for n in names):
                raise ValueError("nežinomas darbas")
            run_chain(names, "rankiniu būdu")
            return self.json({"ok": True})
        return self.json({"error": "nerasta"}, 404)


def main():
    load_secrets_into_env()
    log(f"Trend Map serveris paleistas, prievadas {PORT}")
    if (HOME / "data" / "analysis.json").exists():
        try:  # perpiešti svetainę su naujausiu šablonu
            old_out, sys.stdout = sys.stdout, _Tee()
            build_site.build()
        except Exception as e:  # noqa: BLE001
            log(f"Svetainės perpiešimas nepavyko: {e}")
        finally:
            sys.stdout = old_out
    threading.Thread(target=scheduler, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
