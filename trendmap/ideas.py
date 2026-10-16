"""Savaitės turinio idėjos pagal geriausias galimybes ir tavo pozicionavimą."""
import json

from .common import ANALYSIS, IDEAS_HISTORY, iso, load_json, log, now, profile_text, save_json, settings
from .llm import LLM

SYSTEM = """Tu esi turinio strategas, kuris padeda marketingo turinio kūrėjui nuspręsti, apie ką kalbėti šią savaitę.
Tavo idėjos remiasi duomenimis: kas kyla, kur dar tuščia, kas gerai veikia pas kitus kūrėjus, ką rašo portalai.
Idėjos turi tikti būtent šiam kūrėjui: jo temos, jo tonas, jo požiūris. Nesiūlyk to, kas akivaizdu ir ką jau visi pasakė;
geriau rask kampą, kurio niekas dar nepaėmė, arba pagrįstai prieštarauk populiariai nuomonei.
Rašyk lietuviškai, aiškiai, be marketingo žargono pertekliaus. Atsakyk tik JSON."""

FORMAT_LT = {"reel": "reel", "carousel": "carousel", "image": "vienas vaizdas"}


def _topic_brief(t):
    posts = "\n".join(
        f"    - IG @{p['source']} ({p['format']}, {p['ratio']}x nuo jo vidurkio): {p['title']}"
        for p in t["top_posts"][:3])
    arts = "\n".join(f"    - {a['source']}: {a['title']}  [{a['url']}]" for a in t["top_articles"][:3])
    fmts = ", ".join(f"{f['format']} {f['ratio']}x" for f in t["best_formats"]) or "nėra duomenų"
    return f"""- {t['id']} „{t['name']}“: {t['description']}
  stadija: {t['stage']}; kvadrantas: {t['quadrant']}; momentum: {t['momentum']:+.2f};
  prisotinimas: {round(t['saturation'] * 100)}% stebimų kūrėjų; pranokimas: {t['outperformance'] or '–'}x;
  portalai lenkia IG: {'taip' if t['gap'] > 0.01 else 'ne'}; tinkamumas tau: {t['fit']} ({t['fit_why']});
  geriausi formatai: {fmts}
  pavyzdžiai iš Instagram:
{posts or '    (nėra)'}
  straipsniai:
{arts or '    (nėra)'}"""


def _mock_ideas(cands, n):
    out = []
    for t in cands[:n]:
        src = [a["url"] for a in t["top_articles"][:2] if a.get("url")]
        out.append({
            "topic_id": t["id"],
            "title": f"Ką visi praleidžia kalbėdami apie „{t['name']}“",
            "angle": f"Pažiūrėk į „{t['name'].lower()}“ per pozicionavimo prizmę: ne kaip į taktiką, o kaip į sprendimą, ką brand'as pasirenka nebūti.",
            "why_now": f"Tema {t['stage']} stadijoje: per savaitę {t['recent']['web']} straipsniai ir {t['recent']['ig']} IG įrašai, o kalba tik {round(t['saturation'] * 100)}% stebimų kūrėjų.",
            "hooks": [f"Visi kalba apie {t['name'].lower()}. Niekas neklausia, kodėl.",
                      "Tai ne trendas. Tai simptomas.",
                      "3 brand'ai, kurie tai padarė prieš 10 metų ir to nežinojo."],
            "format": (t["best_formats"][0]["format"] if t["best_formats"] else "carousel"),
            "format_why": "Šioje temoje šis formatas pas kitus kūrėjus surenka daugiausiai įsitraukimo.",
            "contrarian": "Galbūt problema ne tai, kad brand'ai to nedaro, o tai, kad daro be strategijos.",
            "sources": src,
        })
    return {"ideas": out}


def generate(analysis=None, llm=None):
    cfg = settings()
    analysis = analysis or load_json(ANALYSIS, {})
    topics = analysis.get("topics", [])
    n = cfg["ideas"]["count"]
    cands = [t for t in topics if t["fit"] >= 0.35][: n + 4] or topics[: n + 4]
    if not cands:
        log("Idėjų negeneruoju: nėra temų")
        analysis["ideas"] = []
        save_json(ANALYSIS, analysis)
        return []
    llm = llm or LLM(cfg["model"])
    history = load_json(IDEAS_HISTORY, [])
    recent_titles = [h["title"] for h in history[-40:]]
    hooks_lang = "lietuvių" if cfg["ideas"]["hooks_language"] == "lt" else "anglų"

    prompt = f"""KŪRĖJO POZICIONAVIMAS:
{profile_text()}

GERIAUSIOS ŠIOS SAVAITĖS GALIMYBĖS (surikiuotos pagal galimybės balą):
{chr(10).join(_topic_brief(t) for t in cands)}

ANKSČIAU JAU SIŪLYTOS IDĖJOS (nekartok):
{json.dumps(recent_titles, ensure_ascii=False)}

Sugalvok {n} konkrečias turinio idėjas šiai savaitei. Kiekviena idėja remiasi viena tema iš sąrašo.
Pirmenybė temoms „Neužimta erdvė“ ir „ankstyva“/„kylanti“ stadijoms, kurios tinka kūrėjui.

Kiekvienai idėjai:
- title: darbinis įrašo pavadinimas (lietuviškai)
- angle: 1–2 sakiniai, koks unikalus kampas ar mintis
- why_now: 1 sakinys, kodėl būtent dabar (remkis skaičiais iš duomenų)
- hooks: 3 pirmieji sakiniai / pirmosios 3 sekundės ({hooks_lang} kalba), skirtingų tipų
- format: reel | carousel | image
- format_why: 1 sakinys
- contrarian: (nebūtina) priešinga nuomonė, kurią galima ginti
- sources: 1–3 straipsnių URL iš duomenų, kuriais remiesi (tik iš pateiktų)

JSON: {{"ideas": [{{"topic_id": "t001", "title": "...", "angle": "...", "why_now": "...", "hooks": ["...","...","..."],
"format": "carousel", "format_why": "...", "contrarian": "...", "sources": ["https://..."]}}]}}"""

    out = llm.json(SYSTEM, prompt, mock_fn=lambda: _mock_ideas(cands, n), max_tokens=10000)
    valid_urls = {a["url"] for t in cands for a in t["top_articles"] if a.get("url")}
    valid_urls |= {p["url"] for t in cands for p in t["top_posts"] if p.get("url")}
    by_id = {t["id"]: t for t in topics}
    ideas = []
    for idea in out.get("ideas", [])[:n]:
        t = by_id.get(idea.get("topic_id"))
        if not t:
            continue
        idea["topic_name"] = t["name"]
        idea["quadrant"] = t["quadrant"]
        idea["sources"] = [u for u in idea.get("sources", []) if u in valid_urls][:3]
        idea["hooks"] = [h for h in idea.get("hooks", []) if isinstance(h, str)][:3]
        ideas.append(idea)
    analysis["ideas"] = ideas
    save_json(ANALYSIS, analysis)
    stamp = iso(now())
    history += [{"date": stamp, "title": i["title"], "topic": i["topic_name"]} for i in ideas]
    save_json(IDEAS_HISTORY, history[-300:])
    log(f"Idėjos: {len(ideas)}")
    return ideas
