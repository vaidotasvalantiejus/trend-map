"""Bendros pagalbinės funkcijos: keliai, laikas, duomenų saugykla."""
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = Path(os.environ.get("TRENDMAP_CONFIG_DIR", ROOT / "config"))
DATA = Path(os.environ.get("TRENDMAP_DATA_DIR", ROOT / "data"))
DOCS = Path(os.environ.get("TRENDMAP_DOCS_DIR", ROOT / "docs"))
REPORTS = Path(os.environ.get("TRENDMAP_REPORTS_DIR", ROOT / "reports"))

ITEMS = DATA / "items.jsonl"
LABELS = DATA / "labels.json"
TOPICS = DATA / "topics.json"
CREATORS_META = DATA / "creators_meta.json"
FEED_HEALTH = DATA / "feed_health.json"
IDEAS_HISTORY = DATA / "ideas_history.json"
ANALYSIS = DATA / "analysis.json"
IDEAS_CURRENT = DATA / "ideas_current.json"

DEFAULT_SETTINGS = {
    "model": "claude-sonnet-5-5",
    "window_days": 28,
    "recent_days": 7,
    "min_mentions": 3,
    "retention_days": 120,
    "instagram": {
        "backend": "auto",
        "posts_per_creator": 30,
        "lookback_days": 35,
        "apify_actor": "apify~instagram-scraper",
        "graph_api_version": "v21.0",
    },
    "ideas": {"count": 8, "hooks_language": "lt"},
}


def log(msg):
    print(msg, flush=True)


def now():
    if os.environ.get("TRENDMAP_NOW"):
        return parse_dt(os.environ["TRENDMAP_NOW"])
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    from dateutil import parser

    try:
        d = parser.parse(str(value))
    except (ValueError, OverflowError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def short_hash(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base, extra):
    out = dict(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def settings():
    return _deep_merge(DEFAULT_SETTINGS, load_yaml(CONFIG / "settings.yml"))


def normalize_handle(raw):
    s = str(raw).strip()
    s = re.sub(r"^https?://(www\.)?instagram\.com/", "", s, flags=re.I)
    s = s.split("?")[0].split("#")[0].strip("/").lstrip("@").lower()
    s = s.split("/")[0]
    return s if re.fullmatch(r"[a-z0-9._]{1,30}", s) else ""


def creators():
    data = load_yaml(CONFIG / "creators.yml")
    seen, out = set(), []
    for c in data.get("creators") or []:
        h = normalize_handle(c)
        if h and h not in seen:
            seen.add(h)
            out.append(h)
    return out


def save_creators(handles):
    handles = sorted(set(h for h in handles if h))
    lines = [
        "# Stebimi Instagram kūrėjai.",
        "# Pridėti ar pašalinti galima svetainėje (skiltis „Kūrėjai“) arba tiesiog redaguojant šį sąrašą.",
        "creators:",
    ] + [f"  - {h}" for h in handles]
    (CONFIG / "creators.yml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def profile_text():
    p = CONFIG / "profile.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    tmp.replace(path)


def load_items():
    items = {}
    if ITEMS.exists():
        with open(ITEMS, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    it = json.loads(line)
                    items[it["id"]] = it
    return items


def save_items(items):
    keep_after = now() - timedelta(days=settings()["retention_days"])
    rows = [it for it in items.values() if (parse_dt(it.get("published")) or now()) >= keep_after]
    rows.sort(key=lambda it: it.get("published") or "")
    ITEMS.parent.mkdir(parents=True, exist_ok=True)
    with open(ITEMS, "w", encoding="utf-8") as f:
        for it in rows:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")


def merge_items(new_items):
    """Prideda naujus įrašus; esamiems atnaujina metrikas ir tekstą."""
    items = load_items()
    added = 0
    for it in new_items:
        old = items.get(it["id"])
        if old:
            it["first_seen"] = old.get("first_seen", it.get("first_seen"))
        else:
            added += 1
        items[it["id"]] = it
    save_items(items)
    return added


def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&quot;|&#8220;|&#8221;", '"', text)
    text = re.sub(r"&#8217;|&#039;|&#39;", "'", text)
    return re.sub(r"\s+", " ", text).strip()


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
