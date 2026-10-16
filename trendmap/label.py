"""Temų žymėjimas: Claude priskiria kiekvienam įrašui temas iš augančio temų katalogo."""
from datetime import timedelta

from .common import (LABELS, TOPICS, chunks, iso, load_items, load_json, log, now, parse_dt,
                     profile_text, save_json, settings)
from .llm import LLM

BATCH = 40

LABEL_SYSTEM = """Tu esi marketingo trendų analitikas. Tavo darbas: priskirti įrašams diskusijų temas.

Tema yra konkreti diskusija, kuri vyksta marketingo, brandingo, reklamos ir turinio kūrimo pasaulyje.
Gera tema: „AI generuotas UGC reklamose“, „Brand'ų „unhinged“ tonas socialiniuose tinkluose“, „Founder-led turinys“.
Bloga tema (per plati): „Marketingas“, „Socialiniai tinklai“, „AI“.
Bloga tema (per siaura): konkretus vieno brand'o įvykis, nebent juo kalba daugelis.

Taisyklės:
- Pirmiausia naudok esamas katalogo temas. Naują temą kurk tik tada, kai nė viena esama netinka.
- Įrašui priskirk 0–3 temas. Įrašai ne apie marketingą, brandingą, reklamą ar turinio kūrimą gauna tuščią sąrašą.
- Naujos temos pavadinimas lietuviškai, 2–6 žodžiai. Angliški terminai leidžiami, jei taip įprasta (pvz., „Founder-led turinys“).
- Aprašymas vienas sakinys lietuviškai: apie ką ši diskusija.
- Atsakyk tik JSON, be jokio kito teksto."""

FIT_SYSTEM = """Tu vertini, ar marketingo diskusijų temos tinka konkrečiam turinio kūrėjui, pagal jo pozicionavimą.
Atsakyk tik JSON."""


def _item_line(i, it):
    body = (it.get("text") or "")[:600].replace("\n", " ")
    title = (it.get("title") or "").replace("\n", " ")
    src = "Instagram @" + it["source"] if it["source_type"] == "instagram" else it["source"]
    if body.startswith(title):
        return f"[{i}] ({src}) {body}"
    return f"[{i}] ({src}) {title} — {body}"


def _mock_label(batch, topics):
    from .demo import DEMO_TOPICS
    name_to_id = {t["name"]: tid for tid, t in topics.items()}
    new_topics, assignments, keys = [], [], {}
    for i, it in enumerate(batch):
        text = ((it.get("title") or "") + " " + (it.get("text") or "")).lower()
        ids = []
        for name, desc, kw, *_ in DEMO_TOPICS:
            if kw in text:
                if name in name_to_id:
                    ids.append(name_to_id[name])
                else:
                    if name not in keys:
                        keys[name] = f"n{len(keys) + 1}"
                        new_topics.append({"key": keys[name], "name": name, "description": desc})
                    ids.append(keys[name])
        assignments.append({"i": i, "topics": ids[:3]})
    return {"new_topics": new_topics, "assignments": assignments}


def _next_id(topics):
    n = max([int(t[1:]) for t in topics] or [0]) + 1
    return f"t{n:03d}"


def label_new(llm=None):
    cfg = settings()
    llm = llm or LLM(cfg["model"])
    items = load_items()
    labels = load_json(LABELS, {})
    topics = load_json(TOPICS, {})
    cutoff = now() - timedelta(days=cfg["window_days"] + 14)
    todo = [it for iid, it in items.items()
            if iid not in labels and (parse_dt(it.get("published")) or now()) >= cutoff]
    todo.sort(key=lambda it: it.get("published") or "")
    log(f"Žymima {len(todo)} naujų įrašų")

    for n_batch, batch in enumerate(chunks(todo, BATCH), 1):
        catalog = "\n".join(f"{tid}: {t['name']} — {t['description']}" for tid, t in topics.items()) or "(katalogas tuščias)"
        lines = "\n".join(_item_line(i, it) for i, it in enumerate(batch))
        prompt = f"""ESAMŲ TEMŲ KATALOGAS:
{catalog}

ĮRAŠAI:
{lines}

Grąžink JSON tokios formos:
{{"new_topics": [{{"key": "n1", "name": "...", "description": "..."}}],
  "assignments": [{{"i": 0, "topics": ["t001", "n1"]}}]}}

„topics“ sąraše naudok esamų temų ID (t001...) arba naujų temų raktus (n1, n2...). Įtrauk kiekvieną įrašą."""
        out = llm.json(LABEL_SYSTEM, prompt, mock_fn=lambda b=batch: _mock_label(b, topics))

        key_map = {}
        for nt in out.get("new_topics", []):
            name = (nt.get("name") or "").strip()
            if not name:
                continue
            existing = next((tid for tid, t in topics.items() if t["name"].lower() == name.lower()), None)
            if existing:
                key_map[nt.get("key")] = existing
                continue
            tid = _next_id(topics)
            topics[tid] = {"name": name, "description": (nt.get("description") or "").strip(),
                           "created": iso(now())}
            key_map[nt.get("key")] = tid

        done = set()
        for a in out.get("assignments", []):
            i = a.get("i")
            if not isinstance(i, int) or not 0 <= i < len(batch):
                continue
            ids = []
            for t in a.get("topics", []):
                tid = key_map.get(t, t)
                if tid in topics and tid not in ids:
                    ids.append(tid)
            labels[batch[i]["id"]] = ids[:3]
            done.add(i)
        for i, it in enumerate(batch):
            if i not in done:
                labels[it["id"]] = []
        save_json(TOPICS, topics)
        save_json(LABELS, labels)
        log(f"  partija {n_batch}: {len(batch)} įrašų, temų kataloge: {len(topics)}")

    # išmesti žymes įrašams, kurių jau nebėra saugykloje
    labels = {k: v for k, v in labels.items() if k in items}
    save_json(LABELS, labels)
    score_fit(llm, topics)
    return len(todo)


def _mock_fit(missing, topics):
    from .demo import DEMO_TOPICS
    fits = {name: (fit, why) for name, _, _, fit, why, *_ in DEMO_TOPICS}
    return {tid: {"fit": fits.get(topics[tid]["name"], (0.5, ""))[0],
                  "why": fits.get(topics[tid]["name"], (0, "Vidutiniškai artima tavo temoms."))[1]}
            for tid in missing}


def score_fit(llm, topics, force=False):
    missing = [tid for tid, t in topics.items() if force or "fit" not in t]
    if not missing:
        return
    profile = profile_text()
    for batch in chunks(missing, 60):
        listing = "\n".join(f"{tid}: {topics[tid]['name']} — {topics[tid]['description']}" for tid in batch)
        prompt = f"""KŪRĖJO POZICIONAVIMAS:
{profile}

TEMOS:
{listing}

Kiekvienai temai įvertink, kiek ji tinka šiam kūrėjui (0.0 = visiškai ne jo sritis, 1.0 = tiesiai jo teritorija),
ir vienu trumpu sakiniu lietuviškai paaiškink kodėl. Atsižvelk ir į tai, apie ką jis nekalba.
JSON: {{"t001": {{"fit": 0.8, "why": "..."}}}}"""
        out = llm.json(FIT_SYSTEM, prompt, mock_fn=lambda b=batch: _mock_fit(b, topics), max_tokens=6000)
        for tid in batch:
            r = out.get(tid) or {}
            try:
                fit = max(0.0, min(1.0, float(r.get("fit", 0.5))))
            except (TypeError, ValueError):
                fit = 0.5
            topics[tid]["fit"] = round(fit, 2)
            topics[tid]["fit_why"] = (r.get("why") or "").strip()
    save_json(TOPICS, topics)
    log(f"Tinkamumas įvertintas {len(missing)} temoms")
