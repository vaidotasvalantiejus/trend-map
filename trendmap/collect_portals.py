"""Marketingo portalų ir kitų RSS šaltinių surinkimas."""
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from .common import (CONFIG, FEED_HEALTH, iso, load_yaml, log, merge_items, now, save_json,
                     short_hash, strip_html)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36 TrendMap/1.0")
BOT_UA = "Mozilla/5.0 (compatible; TrendMap/1.0; +https://github.com)"


def _entry_date(e):
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def collect():
    feeds = load_yaml(CONFIG / "sources.yml").get("feeds") or []
    cutoff = now() - timedelta(days=35)
    items, health = [], {}
    for f in feeds:
        name, url = f["name"], f["url"]
        if "reddit.com" in url:
            time.sleep(3)
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            if r.status_code == 429:  # pvz., Reddit riboja dažnį
                time.sleep(8)
                r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            if r.status_code == 403:  # kai kurie portalai blokuoja naršyklės UA, bet praleidžia botų
                r = requests.get(url, headers={"User-Agent": BOT_UA}, timeout=30)
            r.raise_for_status()
            parsed = feedparser.parse(r.content)
            if parsed.bozo and not parsed.entries:
                raise RuntimeError("netinkamas RSS formatas")
            n = 0
            for e in parsed.entries:
                link = e.get("link") or ""
                pub = _entry_date(e) or now()
                if pub < cutoff:
                    continue
                title = strip_html(e.get("title", ""))
                summary = strip_html(e.get("summary", "") or e.get("description", ""))
                items.append({
                    "id": "web:" + short_hash(link or title),
                    "source_type": "portal",
                    "source": name,
                    "url": link,
                    "title": title[:300],
                    "text": summary[:1500],
                    "published": iso(pub),
                    "format": "article",
                    "metrics": {},
                    "first_seen": iso(now()),
                })
                n += 1
            health[name] = {"ok": True, "items": n, "checked": iso(now()), "url": url}
            log(f"  {name}: {n}")
        except Exception as ex:  # noqa: BLE001
            health[name] = {"ok": False, "error": str(ex)[:200], "checked": iso(now()), "url": url}
            log(f"  {name}: KLAIDA {ex}")
    save_json(FEED_HEALTH, health)
    added = merge_items(items)
    log(f"Portalai: {len(items)} įrašų, iš jų {added} nauji")
    return added
