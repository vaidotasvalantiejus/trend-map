"""Instagram kūrėjų įrašų surinkimas.

Du būdai:
- Apify (APIFY_TOKEN): mato ir reels peržiūras. Mokamas pagal naudojimą.
- Oficialus Graph API Business Discovery (IG_USER_ID + IG_ACCESS_TOKEN): nemokamas,
  veikia tik su verslo/kūrėjų paskyromis, peržiūrų nerodo.
"""
import os
import time
from datetime import timedelta

import requests

from .common import (CREATORS_META, creators, iso, load_json, log, merge_items, now,
                     parse_dt, save_json, settings, short_hash)


def _item(handle, post_id, caption, published, url, fmt, likes, comments, views):
    caption = (caption or "").strip()
    first_line = caption.split("\n")[0][:140]
    return {
        "id": f"ig:{post_id or short_hash(handle, url)}",
        "source_type": "instagram",
        "source": handle,
        "url": url,
        "title": first_line,
        "text": caption[:2500],
        "published": iso(published) if published else None,
        "format": fmt,
        "metrics": {"likes": likes, "comments": comments, "views": views},
        "first_seen": iso(now()),
    }


# ---------- Graph API ----------

def _graph_format(media_type, product_type):
    if (product_type or "").upper() == "REELS" or (media_type or "").upper() == "VIDEO":
        return "reel"
    if (media_type or "").upper() == "CAROUSEL_ALBUM":
        return "carousel"
    return "image"


def fetch_graph(handles, cfg):
    uid, token = os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"]
    ver = cfg["graph_api_version"]
    limit = cfg["posts_per_creator"]
    cutoff = now() - timedelta(days=cfg["lookback_days"])
    items, meta = [], {}
    for h in handles:
        fields = (
            f"business_discovery.username({h}){{username,name,followers_count,media_count,"
            f"media.limit({limit}){{id,caption,like_count,comments_count,timestamp,media_type,"
            f"media_product_type,permalink}}}}"
        )
        try:
            r = requests.get(f"https://graph.facebook.com/{ver}/{uid}",
                             params={"fields": fields, "access_token": token}, timeout=60)
            data = r.json()
            if "error" in data:
                raise RuntimeError(data["error"].get("message", "nežinoma klaida"))
            bd = data["business_discovery"]
            n = 0
            for p in bd.get("media", {}).get("data", []):
                pub = parse_dt(p.get("timestamp"))
                if pub and pub < cutoff:
                    continue
                items.append(_item(h, p.get("id"), p.get("caption"), pub, p.get("permalink"),
                                   _graph_format(p.get("media_type"), p.get("media_product_type")),
                                   p.get("like_count"), p.get("comments_count"), None))
                n += 1
            meta[h] = {"status": "ok", "name": bd.get("name"), "followers": bd.get("followers_count"),
                       "fetched": iso(now()), "posts": n}
            log(f"  @{h}: {n} įrašų")
        except Exception as e:  # noqa: BLE001
            meta[h] = {"status": "error", "error": str(e)[:200], "fetched": iso(now())}
            log(f"  @{h}: KLAIDA {e}")
    return items, meta


# ---------- Apify ----------

def _apify_format(it):
    if it.get("productType") == "clips" or it.get("type") == "Video":
        return "reel"
    if it.get("type") == "Sidecar":
        return "carousel"
    return "image"


def fetch_apify(handles, cfg):
    token = os.environ["APIFY_TOKEN"]
    actor = cfg["apify_actor"]
    payload = {
        "directUrls": [f"https://www.instagram.com/{h}/" for h in handles],
        "resultsType": "posts",
        "resultsLimit": cfg["posts_per_creator"],
        "onlyPostsNewerThan": f"{cfg['lookback_days']} days",
        "addParentData": True,
    }
    base = "https://api.apify.com/v2"
    r = requests.post(f"{base}/acts/{actor}/runs", params={"token": token}, json=payload, timeout=60)
    r.raise_for_status()
    run = r.json()["data"]
    log(f"  Apify paleistas: {run['id']}")
    deadline = time.time() + 40 * 60
    while run["status"] in ("READY", "RUNNING") and time.time() < deadline:
        time.sleep(20)
        run = requests.get(f"{base}/actor-runs/{run['id']}", params={"token": token}, timeout=60).json()["data"]
    if run["status"] != "SUCCEEDED":
        raise RuntimeError(f"Apify baigėsi būsena {run['status']}")
    rows = requests.get(f"{base}/datasets/{run['defaultDatasetId']}/items",
                        params={"token": token, "clean": "true", "format": "json"}, timeout=120).json()

    wanted = set(handles)
    items, meta = [], {h: {"status": "error", "error": "negauta įrašų", "fetched": iso(now())} for h in handles}
    counts = {}
    for it in rows:
        if it.get("error"):
            continue
        h = (it.get("ownerUsername") or "").lower()
        if h not in wanted:
            continue
        views = it.get("videoPlayCount") or it.get("videoViewCount")
        items.append(_item(h, it.get("id") or it.get("shortCode"), it.get("caption"),
                           parse_dt(it.get("timestamp")), it.get("url"), _apify_format(it),
                           it.get("likesCount") if (it.get("likesCount") or 0) >= 0 else None,
                           it.get("commentsCount"), views))
        counts[h] = counts.get(h, 0) + 1
        meta[h] = {"status": "ok", "name": it.get("ownerFullName"), "followers": it.get("ownerFollowersCount"),
                   "fetched": iso(now()), "posts": counts[h]}
    for h in handles:
        log(f"  @{h}: {counts.get(h, 0)} įrašų")
    return items, meta


def collect():
    cfg = settings()["instagram"]
    handles = creators()
    backend = cfg["backend"]
    if backend == "auto":
        if os.environ.get("APIFY_TOKEN"):
            backend = "apify"
        elif os.environ.get("IG_USER_ID") and os.environ.get("IG_ACCESS_TOKEN"):
            backend = "graph"
        else:
            log("Instagram praleistas: nėra nei APIFY_TOKEN, nei IG_USER_ID + IG_ACCESS_TOKEN.")
            return 0
    log(f"Instagram ({backend}): {len(handles)} kūrėjų")
    items, meta = (fetch_apify if backend == "apify" else fetch_graph)(handles, cfg)
    old_meta = load_json(CREATORS_META, {})
    for h, m in meta.items():
        if m["status"] == "error" and old_meta.get(h, {}).get("followers"):
            m["followers"] = old_meta[h]["followers"]
        old_meta[h] = m
    save_json(CREATORS_META, old_meta)
    added = merge_items(items)
    log(f"Instagram: {len(items)} įrašų, iš jų {added} nauji")
    return added
