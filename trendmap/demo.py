"""Demo duomenys: sintetiniai įrašai, kad svetainę ir visą grandinę būtų galima pamatyti be API raktų."""
import random
from datetime import timedelta

from .common import CREATORS_META, FEED_HEALTH, creators, iso, merge_items, now, save_json

# (pavadinimas, aprašymas, raktažodis, tinkamumas, kodėl, portalų kreivė, IG kreivė, kūrėjų dalis, įsitraukimo daugiklis)
DEMO_TOPICS = [
    ("AI agentai agentūrose", "Ar AI agentai pakeis kūrybinių agentūrų darbo modelį ir kainodarą.", "ai agents",
     0.8, "Tiesiai susiję su agentūrų verslo modeliu ir tavo darbu su NEW.", "rise", "rise", 0.55, 1.3),
    ("Brand'ai kaip žiniasklaida", "Brand'ai kuria savo leidinius, laidas ir bendruomenes vietoj reklamos.", "brand as media",
     0.85, "Pozicionavimo ir brand strategijos klausimas, tavo teritorija.", "rise", "flat_low", 0.15, 1.6),
    ("Founder-led turinys", "Įkūrėjai kaip pagrindinis brand'o balsas socialiniuose tinkluose.", "founder-led",
     0.6, "Artima, nors labiau apie asmeninį brandą nei strategiją.", "flat", "flat_high", 0.6, 1.0),
    ("Anti-AI estetika", "Ranka daryto, netobulo dizaino ir copy grįžimas kaip atsakas į AI turinį.", "handmade",
     0.75, "Vizualinis identitetas ir brand balsas, kalba tavo kalba.", "rise_fast", "low", 0.1, 1.8),
    ("Pozicionavimas prieš performance", "Ginčas, ar brand building svarbiau už trumpalaikius performance rezultatus.", "positioning",
     0.95, "Tavo pagrindinė tema.", "flat", "flat_high", 0.7, 1.1),
    ("Paieška per LLM (GEO)", "Kaip brand'ai atsiranda ChatGPT ir kitų AI atsakymuose.", "llm search",
     0.45, "Labiau techninis SEO klausimas, bet turi brand'o kampą.", "rise_fast", "rise", 0.25, 1.2),
    ("Nostalgijos marketingas", "Brand'ai grįžta prie senų logotipų, reklamų ir estetikos.", "nostalgia",
     0.65, "Brand heritage ir identitetas, tinka tavo prizmei.", "flat", "flat", 0.3, 1.0),
    ("Rebrandingų kritika", "Viešos reakcijos į didelių brand'ų rebrandingus ir „blanding“.", "rebrand",
     0.9, "Tiesiogiai apie identitetą ir naming, tavo ekspertizė.", "flat_high", "fall", 0.65, 0.9),
    ("Distinctive brand assets", "Kaip ženklai, spalvos ir garsai kuria atpažįstamumą (Ehrenberg-Bass).", "distinctive assets",
     0.9, "Strategija su moksliniu pagrindu, tavo stiprybė.", "rise", "low", 0.12, 1.7),
    ("„Unhinged“ brand tonas", "Brand'ų chaotiškas, ironiškas tonas socialiniuose tinkluose.", "unhinged",
     0.55, "Brand balso tema, bet trendas jau senka.", "fall", "fall", 0.5, 0.7),
    ("Mikrodramos reklamoje", "Serialinio formato trumpi video kaip reklamos formatas.", "micro-drama",
     0.3, "Labiau produkcijos ir formato klausimas nei strategijos.", "rise_fast", "low", 0.08, 1.4),
    ("Naujienlaiškių bumas", "Kūrėjai ir brand'ai traukiasi iš algoritmų į savo naujienlaiškius.", "newsletter",
     0.7, "Tinka, turi savo Substack ir patirties.", "flat", "flat", 0.3, 1.1),
]

PORTALS = ["Adweek", "Marketing Week", "Digiday", "Marketing Dive", "The Drum", "Campaign",
           "Google News — brand strategy", "Google News — rinkodara"]

CURVES = {  # dienų nuo šiandien funkcija → vidutinis įrašų per dieną
    "rise": lambda a: 0.3 + 1.6 * max(0, (35 - a) / 35) ** 2,
    "rise_fast": lambda a: 0.15 + (2.4 if a < 9 else 0.25),
    "flat": lambda a: 0.7,
    "flat_high": lambda a: 1.1,
    "flat_low": lambda a: 0.12,
    "low": lambda a: 0.06,
    "fall": lambda a: 0.2 + 1.4 * (a / 35) ** 1.5,
}

HOOKS = ["Unpopular opinion:", "Nobody talks about this:", "Here's what most brands get wrong about",
         "3 lessons from", "Stop doing this:", "The real reason behind"]


def generate(seed=7):
    rnd = random.Random(seed)
    t_now = now()
    handles = creators()
    base = {h: rnd.randint(300, 6000) for h in handles}
    items = []
    for name, desc, kw, _fit, _why, web_c, ig_c, share, mult in DEMO_TOPICS:
        topic_creators = rnd.sample(handles, max(1, round(len(handles) * share)))
        for day in range(35):
            for kind, curve in (("portal", CURVES[web_c]), ("instagram", CURVES[ig_c])):
                lam = curve(day) * (1.6 if kind == "portal" else 0.8)
                n = sum(1 for _ in range(12) if rnd.random() < lam / 12)
                for _ in range(n):
                    pub = t_now - timedelta(days=day, hours=rnd.randint(0, 23))
                    if kind == "portal":
                        src = rnd.choice(PORTALS)
                        title = f"{name}: {rnd.choice(['why', 'how', 'what'])} {kw} is changing marketing"
                        items.append({
                            "id": f"web:demo{len(items)}", "source_type": "portal", "source": src,
                            "url": f"https://example.com/{kw.replace(' ', '-')}/{len(items)}",
                            "title": title, "text": f"An article about {kw}.", "published": iso(pub),
                            "format": "article", "metrics": {}, "first_seen": iso(t_now)})
                    else:
                        h = rnd.choice(topic_creators)
                        fmt = rnd.choice(["reel", "reel", "carousel", "image"])
                        f_mult = {"reel": 1.2, "carousel": 1.0, "image": 0.6}[fmt]
                        eng = base[h] * mult * f_mult * rnd.lognormvariate(0, 0.45)
                        caption = f"{rnd.choice(HOOKS)} {kw}. {desc}"
                        items.append({
                            "id": f"ig:demo{len(items)}", "source_type": "instagram", "source": h,
                            "url": f"https://www.instagram.com/p/demo{len(items)}/",
                            "title": caption[:140], "text": caption, "published": iso(pub), "format": fmt,
                            "metrics": {"likes": int(eng * 0.9), "comments": int(eng * 0.05),
                                        "views": int(eng * 14) if fmt == "reel" else None},
                            "first_seen": iso(t_now)})
    # neutralūs įrašai be marketingo temos
    for i in range(40):
        h = rnd.choice(handles)
        items.append({"id": f"ig:demo-x{i}", "source_type": "instagram", "source": h,
                      "url": f"https://www.instagram.com/p/demox{i}/", "title": "Weekend in Lisbon ☀️",
                      "text": "Weekend in Lisbon ☀️", "published": iso(t_now - timedelta(days=rnd.randint(0, 34))),
                      "format": "image", "metrics": {"likes": base[h], "comments": 10, "views": None},
                      "first_seen": iso(t_now)})
    merge_items(items)
    save_json(CREATORS_META, {h: {"status": "ok", "name": None, "followers": base[h] * rnd.randint(25, 60),
                                  "fetched": iso(t_now)} for h in handles})
    health = {p: {"ok": True, "items": rnd.randint(8, 40), "checked": iso(t_now), "url": "https://example.com"} for p in PORTALS}
    health["Ad Age"] = {"ok": False, "error": "404 Not Found (demo)", "checked": iso(t_now), "url": "https://example.com"}
    save_json(FEED_HEALTH, health)
    return len(items)
