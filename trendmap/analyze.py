"""Temų metrikos: momentum, prisotinimas, pranokimas, vėlavimo signalas, galimybės balas."""
import math
from collections import defaultdict
from statistics import median

from .common import (ANALYSIS, CREATORS_META, FEED_HEALTH, LABELS, TOPICS, creators, iso,
                     load_items, load_json, log, now, parse_dt, save_json, settings)

STAGES = ["ankstyva", "kylanti", "pikas", "prisotinta", "gęstanti"]


def engagement(it):
    m = it.get("metrics") or {}
    likes, comments = m.get("likes"), m.get("comments")
    if likes is None and comments is None:
        return None
    return (likes or 0) + 2 * (comments or 0)


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def stage_of(m, sat):
    if m <= -0.4:
        return "gęstanti"
    if m >= 0.3 and sat < 0.25:
        return "ankstyva"
    if m >= 0.3:
        return "kylanti"
    if sat >= 0.4:
        return "prisotinta"
    return "pikas"


def quadrant_of(m, sat):
    if m <= -0.4:
        return "Gęstanti"
    if m >= 0.15:
        return "Neužimta erdvė" if sat < 0.3 else "Karšta"
    return "Perpildyta" if sat >= 0.3 else "Tylu"


def _brief(it, ratio=None):
    return {
        "url": it.get("url"),
        "title": (it.get("title") or it.get("text") or "")[:160],
        "source": it["source"],
        "type": it["source_type"],
        "published": it.get("published"),
        "format": it.get("format"),
        "ratio": round(ratio, 2) if ratio is not None else None,
        "eng": engagement(it),
        "views": (it.get("metrics") or {}).get("views"),
    }


def analyze():
    cfg = settings()
    t_now = now()
    W, R = cfg["window_days"], cfg["recent_days"]
    items = load_items()
    labels = load_json(LABELS, {})
    topics = load_json(TOPICS, {})
    watched = creators()
    meta = load_json(CREATORS_META, {})

    def age(it):
        d = parse_dt(it.get("published"))
        return (t_now - d).total_seconds() / 86400 if d else None

    # kūrėjų medianinis įsitraukimas (60 d.) — pranokimo bazė
    eng_by_creator = defaultdict(list)
    for it in items.values():
        a = age(it)
        if it["source_type"] == "instagram" and a is not None and a <= 60:
            e = engagement(it)
            if e is not None:
                eng_by_creator[it["source"]].append(e)
    creator_median = {h: median(v) for h, v in eng_by_creator.items() if v}

    def ratio(it):
        e, base = engagement(it), creator_median.get(it["source"])
        if e is None or not base:
            return None
        return e / base

    window_items = [it for it in items.values() if (a := age(it)) is not None and 0 <= a <= W]
    ig_window = [it for it in window_items if it["source_type"] == "instagram"]
    web_window = [it for it in window_items if it["source_type"] == "portal"]
    active_creators = {it["source"] for it in ig_window} or set(watched)
    ig_14 = sum(1 for it in ig_window if age(it) <= 14)
    web_14 = sum(1 for it in web_window if age(it) <= 14)

    agg = defaultdict(lambda: {"ig_r": 0, "ig_p": 0, "web_r": 0, "web_p": 0, "ig_14": 0, "web_14": 0,
                               "creators": set(), "ratios": [], "ig_items": [], "web_items": [],
                               "weeks_ig": [0] * 8, "weeks_web": [0] * 8, "formats": defaultdict(list)})
    # savaitinės eilutės — 8 savaitės iš visos saugyklos
    for it in items.values():
        a = age(it)
        if a is None or a < 0 or a >= 56:
            continue
        wk = 7 - int(a // 7)
        for tid in labels.get(it["id"], []):
            agg[tid]["weeks_ig" if it["source_type"] == "instagram" else "weeks_web"][wk] += 1

    for it in window_items:
        a = age(it)
        recent = a <= R
        is_ig = it["source_type"] == "instagram"
        for tid in labels.get(it["id"], []):
            g = agg[tid]
            key = ("ig_" if is_ig else "web_") + ("r" if recent else "p")
            g[key] += 1
            if a <= 14:
                g["ig_14" if is_ig else "web_14"] += 1
            if is_ig:
                g["creators"].add(it["source"])
                r = ratio(it)
                if r is not None:
                    g["ratios"].append(r)
                    g["formats"][it.get("format") or "?"].append(r)
                g["ig_items"].append((it, r))
            else:
                g["web_items"].append(it)

    prior_weeks = max(1.0, (W - R) / 7)
    out_topics = []
    for tid, g in agg.items():
        if tid not in topics:
            continue
        vol = g["ig_r"] + g["ig_p"] + g["web_r"] + g["web_p"]
        if vol < cfg["min_mentions"]:
            continue
        vol_r = g["ig_r"] + g["web_r"]
        vol_p = g["ig_p"] + g["web_p"]
        momentum = math.log2((vol_r + 1) / (vol_p / prior_weeks + 1))
        saturation = len(g["creators"]) / max(1, len(active_creators))
        outperf = median(g["ratios"]) if g["ratios"] else None
        web_share = g["web_14"] / max(1, web_14)
        ig_share = g["ig_14"] / max(1, ig_14)
        gap = web_share - ig_share
        fit = topics[tid].get("fit", 0.5)

        m_n = clamp((momentum + 1) / 3)
        open_n = 1 - clamp(saturation)
        perf_n = clamp((outperf if outperf is not None else 1.0) / 2)
        gap_n = clamp(0.5 + gap * 8)
        score = (0.35 * m_n + 0.25 * open_n + 0.2 * perf_n + 0.2 * gap_n) * (0.35 + 0.65 * fit) * 100

        best_formats = sorted(((f, median(v), len(v)) for f, v in g["formats"].items() if len(v) >= 2),
                              key=lambda x: -x[1])
        top_posts = sorted((x for x in g["ig_items"] if x[1] is not None), key=lambda x: -x[1])[:4]
        if len(top_posts) < 4:
            rest = [x for x in g["ig_items"] if x[1] is None][: 4 - len(top_posts)]
            top_posts += rest
        top_articles = sorted(g["web_items"], key=lambda it: it.get("published") or "", reverse=True)[:4]

        out_topics.append({
            "id": tid,
            "name": topics[tid]["name"],
            "description": topics[tid].get("description", ""),
            "fit": fit,
            "fit_why": topics[tid].get("fit_why", ""),
            "momentum": round(momentum, 3),
            "saturation": round(saturation, 3),
            "outperformance": round(outperf, 2) if outperf is not None else None,
            "gap": round(gap, 4),
            "volume": vol,
            "recent": {"ig": g["ig_r"], "web": g["web_r"]},
            "prior": {"ig": g["ig_p"], "web": g["web_p"]},
            "creators": sorted(g["creators"]),
            "weeks_ig": g["weeks_ig"],
            "weeks_web": g["weeks_web"],
            "stage": stage_of(momentum, saturation),
            "quadrant": quadrant_of(momentum, saturation),
            "opportunity": round(score, 1),
            "best_formats": [{"format": f, "ratio": round(r, 2), "n": n} for f, r, n in best_formats[:3]],
            "top_posts": [_brief(it, r) for it, r in top_posts],
            "top_articles": [_brief(it) for it in top_articles],
            "first_seen": topics[tid].get("created"),
        })
    out_topics.sort(key=lambda t: -t["opportunity"])

    # kūrėjų lentelė
    creator_rows = []
    by_creator = defaultdict(list)
    for it in ig_window:
        by_creator[it["source"]].append(it)
    for h in watched:
        posts = by_creator.get(h, [])
        tcount = defaultdict(int)
        for it in posts:
            for tid in labels.get(it["id"], []):
                tcount[tid] += 1
        best = max(((it, ratio(it)) for it in posts if ratio(it) is not None), key=lambda x: x[1], default=None)
        m = meta.get(h, {})
        creator_rows.append({
            "handle": h,
            "name": m.get("name"),
            "followers": m.get("followers"),
            "status": m.get("status", "laukia"),
            "error": m.get("error"),
            "posts": len(posts),
            "median_eng": round(creator_median[h]) if h in creator_median else None,
            "topics": [topics[t]["name"] for t, _ in sorted(tcount.items(), key=lambda x: -x[1])[:3] if t in topics],
            "best": _brief(best[0], best[1]) if best else None,
        })
    creator_rows.sort(key=lambda r: (-r["posts"], r["handle"]))

    labeled = sum(1 for it in window_items if labels.get(it["id"]))
    analysis = {
        "generated": iso(t_now),
        "window_days": W,
        "recent_days": R,
        "stats": {
            "ig_posts": len(ig_window),
            "articles": len(web_window),
            "creators_active": len(active_creators & set(watched)) if ig_window else 0,
            "creators_watched": len(watched),
            "topics": len(out_topics),
            "labeled": labeled,
        },
        "topics": out_topics,
        "creators": creator_rows,
        "feeds": load_json(FEED_HEALTH, {}),
    }
    save_json(ANALYSIS, analysis)
    log(f"Analizė: {len(out_topics)} temų žemėlapyje, {len(ig_window)} IG įrašų, {len(web_window)} straipsnių")
    return analysis
