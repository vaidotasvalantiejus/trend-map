#!/usr/bin/env python3
"""Trend Map komandos.

  python run.py collect-portals     surinkti portalų RSS (kasdien)
  python run.py collect-instagram   surinkti Instagram kūrėjų įrašus
  python run.py label               priskirti temas naujiems įrašams (Claude)
  python run.py report              analizė + idėjos + svetainė
  python run.py weekly              viskas iš eilės (savaitinis paleidimas)
  python run.py rescore-fit         iš naujo įvertinti temų tinkamumą (pakeitus profile.md)
  python run.py manage-creators     pridėti/pašalinti kūrėjus pagal ISSUE_TITLE ir ISSUE_BODY
  python run.py demo                demo su sintetiniais duomenimis į build/demo/ (be API raktų)
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description="Trend Map")
    p.add_argument("command", choices=["collect-portals", "collect-instagram", "label", "report", "weekly",
                                       "rescore-fit", "manage-creators", "demo"])
    args = p.parse_args()

    if args.command == "demo":
        demo_root = ROOT / "build" / "demo"
        shutil.rmtree(demo_root, ignore_errors=True)
        os.environ.update({
            "TRENDMAP_DATA_DIR": str(demo_root / "data"),
            "TRENDMAP_DOCS_DIR": str(demo_root / "site"),
            "TRENDMAP_REPORTS_DIR": str(demo_root / "reports"),
            "TRENDMAP_MOCK_LLM": "1",
        })

    from trendmap import analyze, build_site, collect_instagram, collect_portals, ideas, label

    cmd = args.command
    if cmd == "collect-portals":
        collect_portals.collect()
    elif cmd == "collect-instagram":
        collect_instagram.collect()
    elif cmd == "label":
        label.label_new()
    elif cmd == "rescore-fit":
        from trendmap.common import TOPICS, load_json, settings
        from trendmap.llm import LLM
        label.score_fit(LLM(settings()["model"]), load_json(TOPICS, {}), force=True)
    elif cmd == "report":
        ideas.generate(analyze.analyze())
        build_site.build()
    elif cmd == "weekly":
        for step in (collect_portals.collect, collect_instagram.collect):
            try:
                step()
            except Exception as e:  # noqa: BLE001 — vienas šaltinis neturi sustabdyti viso paleidimo
                print(f"ĮSPĖJIMAS: {step.__module__} nepavyko: {e}", file=sys.stderr)
        label.label_new()
        ideas.generate(analyze.analyze())
        build_site.build()
    elif cmd == "manage-creators":
        from trendmap.manage_creators import handle_issue
        print(handle_issue(os.environ.get("ISSUE_TITLE", ""), os.environ.get("ISSUE_BODY", "")))
    elif cmd == "demo":
        from trendmap import demo
        n = demo.generate()
        print(f"Demo: sugeneruota {n} įrašų")
        label.label_new()
        ideas.generate(analyze.analyze())
        build_site.build(demo=True)


if __name__ == "__main__":
    main()
