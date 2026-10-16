# Trend Map

Marketingo turinio radaras. Kas savaitę peržiūri, apie ką kalba stebimi Instagram kūrėjai ir marketingo portalai, randa kylančias ir krentančias temas ir pasiūlo, apie ką kalbėti tau, kad sulauktum daugiausiai dėmesio.

Veikia kaip vienas Docker konteineris tavo serveryje: pats renka duomenis pagal grafiką (portalai kas 3 val., Instagram ir žemėlapis kasdien, naujos idėjos pirmadieniais), Claude juos analizuoja, o rezultatą matai svetainėje su prisijungimu.

## Ką gauni

- **Savaitės idėjos:** 8 konkrečios idėjos su kampu, „kodėl dabar“, trimis hook'ais, formatu ir šaltiniais.
- **Trendų žemėlapis:** temos pagal momentum (kyla ar krenta) ir prisotinimą (kiek kūrėjų jau kalba). Viršutinis kairys kampas, „Neužimta erdvė“, yra temos, kurios kyla, bet dar mažai kas apie jas kalba.
- **Temos:** kas labiausiai kyla ir krenta, kiekvienos temos geriausi Instagram įrašai, naujausi straipsniai ir 8 savaičių eiga.
- **Kūrėjai:** kas ką kalba, kieno įrašai veikia geriausiai. Pridėti ir pašalinti kūrėjus galima tiesiai svetainėje.
- **Šaltiniai:** kurie portalai veikia, kurie ne.
- **Archyvas:** kiekvienos savaitės ataskaita išsaugoma (`reports/` ir svetainės datos pasirinkimas).

## Paleidimas serveryje

1. Docker Compose projektui naudok `docker-compose.yml` iš šios repozitorijos. `SETUP_CODE` pakeisk į atsitiktinį kodą.
2. Atidaryk `http://<serverio-ip>:8787/setup?code=<SETUP_CODE>` ir susikurk slaptažodį.
3. **Nustatymuose** įklijuok Claude API raktą (console.anthropic.com → API Keys) ir Apify raktą (apify.com → Settings → API & Integrations). Pirmas surinkimas prasidės iškart.
4. Ten pat užpildyk savo pozicionavimą.

Visi duomenys, raktai ir nustatymai laikomi aplanke `./data` šalia `docker-compose.yml`. Kodas atsisiunčiamas iš šios repozitorijos kiekvieną kartą paleidus konteinerį, todėl atnaujinimui pakanka jį perkrauti.

**Instagram:** Apify yra paprasčiausias būdas ir mato reels peržiūras. Mokamas pagal naudojimą, kainą pasitikrink Apify svetainėje. Duomenys renkami iš viešų puslapių, o tai Instagram taisyklių atžvilgiu yra pilkoji zona. Alternatyva yra oficialus Graph API (`IG_USER_ID` + `IG_ACCESS_TOKEN`): nemokamas, bet reikia Instagram Business ar Creator paskyros ir Meta programėlės, o peržiūrų jis nerodo.

**Alternatyva be serverio:** aplanke `github-actions/` yra workflow'ai, kuriais tą patį galima paleisti per GitHub Actions + GitHub Pages (perkelk juos į `.github/workflows/`).

## Ką gali keisti

| Failas | Kam |
|---|---|
| Nustatymai → pozicionavimas | Tavo pozicionavimas, tonas ir apie ką nekalbi. Nuo to priklauso tinkamumo balas ir idėjos. **Užpildyk pirmiausia.** |
| Svetainė → Kūrėjai | Stebimi kūrėjai |
| `config/sources.yml` | Portalai ir RSS. Google News paieška tinka bet kuriam portalui: `site:portalas.lt` |
| `config/settings.yml` | Modelis, analizės langas, idėjų skaičius, hook'ų kalba |

## Metrikos

- **Momentum:** paskutinių 7 d. paminėjimai, palyginti su ankstesnių 3 savaičių savaitiniu vidurkiu (log₂). +1 = dvigubai daugiau.
- **Prisotinimas:** kokia dalis aktyvių stebimų kūrėjų kalbėjo apie temą per 28 d.
- **Pranokimas:** temos įrašų įsitraukimas, palyginti su kiekvieno kūrėjo įprastu įrašu (like'ai + 2 × komentarai).
- **Portalai lenkia:** temos dalis portaluose minus dalis Instagram per 14 d. Teigiama = tema dar tik ateina į Instagram.
- **Galimybė (0–100):** momentum 35%, neužimtumas 25%, pranokimas 20%, portalų persvara 20%, padauginta iš tinkamumo tau.

## Vietinis paleidimas

```bash
pip install -r requirements.txt
python run.py demo            # demo su sugalvotais duomenimis → build/demo/site/index.html
export ANTHROPIC_API_KEY=...  # ir APIFY_TOKEN arba IG_USER_ID + IG_ACCESS_TOKEN
TRENDMAP_HOME=./local SETUP_CODE=test python server.py   # serveris http://localhost:8080
```

## Kaina

Claude API: maždaug 0,3–1 $ per savaitinį paleidimą (pirmas brangesnis, nes žymima visa istorija). Apify: pagal naudojimą. Serveris: tavo esamas VPS.

## Kitos versijos

- v2: hook'ų biblioteka, reels transkripcijos, turinio juodraščiai tavo balsu, perpanaudojimas į Substack ir LinkedIn
- v3: tavo Instagram Insights grįžtamasis ryšys, teiginių sekimas, prognozių tikslumas, TikTok ir LinkedIn šaltiniai
