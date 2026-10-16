"""Svetainės (docs/index.html), momentinių kopijų ir markdown ataskaitos generavimas."""
import json
import os

from .common import ANALYSIS, DOCS, IDEAS_CURRENT, REPORTS, ROOT, load_json, log, save_json

FORMAT_LT = {"reel": "Reel", "carousel": "Carousel", "image": "Vienas vaizdas"}


def _report_md(a):
    date = a["generated"][:10]
    lines = [f"# Trend Map — {date}", "",
             f"{a['stats']['ig_posts']} IG įrašų iš {a['stats']['creators_watched']} kūrėjų, "
             f"{a['stats']['articles']} straipsnių, {a['stats']['topics']} temos per {a['window_days']} d.", ""]
    if a.get("ideas"):
        lines += ["## Šios savaitės idėjos", ""]
        for i, idea in enumerate(a["ideas"], 1):
            lines += [f"### {i}. {idea['title']}",
                      f"*{idea['topic_name']} · {FORMAT_LT.get(idea.get('format'), idea.get('format'))}*", "",
                      idea.get("angle", ""), "", f"**Kodėl dabar:** {idea.get('why_now', '')}", "",
                      "**Hook'ai:**"] + [f"- {h}" for h in idea.get("hooks", [])] + [""]
    rising = [t for t in a["topics"] if t["momentum"] >= 0.3][:8]
    falling = sorted([t for t in a["topics"] if t["momentum"] <= -0.3], key=lambda t: t["momentum"])[:8]
    lines += ["## Kylančios temos", ""] + [f"- **{t['name']}** ({t['momentum']:+.2f}, {t['quadrant']})" for t in rising]
    lines += ["", "## Krentančios temos", ""] + [f"- **{t['name']}** ({t['momentum']:+.2f})" for t in falling]
    lines += ["", "## Visos temos pagal galimybę", "", "| Tema | Galimybė | Momentum | Prisotinimas | Kvadrantas |",
              "|---|---|---|---|---|"]
    lines += [f"| {t['name']} | {t['opportunity']} | {t['momentum']:+.2f} | {round(t['saturation'] * 100)}% | {t['quadrant']} |"
              for t in a["topics"]]
    return "\n".join(lines) + "\n"


def build(demo=False):
    a = load_json(ANALYSIS, None)
    if not a:
        raise SystemExit("Nėra analizės. Pirma paleisk: python run.py report")
    a["demo"] = demo
    a["repo"] = os.environ.get("GITHUB_REPOSITORY", "")
    a["server"] = os.environ.get("TRENDMAP_SERVER") == "1"
    if "ideas" not in a:
        cur = load_json(IDEAS_CURRENT, {})
        a["ideas"] = cur.get("ideas", [])
        a["ideas_generated"] = cur.get("generated")
    date = a["generated"][:10]

    snap_dir = DOCS / "snapshots"
    save_json(snap_dir / f"{date}.json", a)
    index = sorted({p.stem for p in snap_dir.glob("*.json") if p.stem != "index"}, reverse=True)
    save_json(snap_dir / "index.json", index)
    a["snapshots"] = index

    template = (ROOT / "site" / "template.html").read_text(encoding="utf-8")
    payload = json.dumps(a, ensure_ascii=False).replace("</", "<\\/")
    html = template.replace("/*__DATA__*/null", payload)
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "index.html").write_text(html, encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{date}.md").write_text(_report_md(a), encoding="utf-8")
    log(f"Svetainė: {DOCS / 'index.html'}; ataskaita: reports/{date}.md")
