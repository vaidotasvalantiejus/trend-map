"""Kūrėjų pridėjimas/šalinimas per GitHub issue (pavadinimas „[pridėti] @a @b“ arba „[pašalinti] @a“)."""
import re

from .common import creators, normalize_handle, save_creators


def handle_issue(title, body=""):
    t = (title or "").strip()
    m = re.match(r"^\[(pridėti|pašalinti)\]\s*(.*)$", t, flags=re.I)
    if not m:
        return "Nežinoma komanda. Pavadinimas turi prasidėti „[pridėti]“ arba „[pašalinti]“."
    action = m.group(1).lower()
    raw = m.group(2) + " " + (body or "")
    tokens = re.findall(r"(?:https?://(?:www\.)?instagram\.com/[^\s,]+|@?[A-Za-z0-9._]{2,30})", raw)
    handles = []
    for tok in tokens:
        if not (tok.startswith("@") or "instagram.com" in tok):
            continue
        h = normalize_handle(tok)
        if h and h not in handles:
            handles.append(h)
    if not handles:
        return "Neradau paskyrų. Rašyk jas su @, pvz.: [pridėti] @paskyra1 @paskyra2"
    current = creators()
    if action == "pridėti":
        new = [h for h in handles if h not in current]
        save_creators(current + new)
        skipped = [h for h in handles if h in current]
        msg = f"Pridėta: {', '.join('@' + h for h in new) or 'nieko'}."
        if skipped:
            msg += f" Jau buvo sąraše: {', '.join('@' + h for h in skipped)}."
        return msg + " Duomenys atsiras po kito savaitinio paleidimo."
    removed = [h for h in handles if h in current]
    save_creators([h for h in current if h not in handles])
    return f"Pašalinta: {', '.join('@' + h for h in removed) or 'nieko (tokių sąraše nebuvo)'}."
