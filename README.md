# Trend Map

Marketingo turinio radaras. Kas savaitę peržiūri, apie ką kalba stebimi Instagram kūrėjai ir marketingo portalai, randa kylančias ir krentančias temas ir pasiūlo, apie ką kalbėti tau, kad sulauktum daugiausiai dėmesio.

Veikia be serverio: GitHub Actions renka duomenis pagal grafiką, Claude juos analizuoja, rezultatas publikuojamas kaip GitHub Pages svetainė.

## Ką gauni

- **Savaitės idėjos:** 8 konkrečios idėjos su kampu, „kodėl dabar“, trimis hook'ais, formatu ir šaltiniais.
- **Trendų žemėlapis:** temos pagal momentum (kyla ar krenta) ir prisotinimą (kiek kūrėjų jau kalba). Viršutinis kairys kampas, „Neužimta erdvė“, yra temos, kurios kyla, bet dar mažai kas apie jas kalba.
- **Temos:** kas labiausiai kyla ir krenta, kiekvienos temos geriausi Instagram įrašai, naujausi straipsniai ir 8 savaičių eiga.
- **Kūrėjai:** kas ką kalba, kieno įrašai veikia geriausiai. Pridėti ir pašalinti kūrėjus galima tiesiai svetainėje.
- **Šaltiniai:** kurie portalai veikia, kurie ne.
- **Archyvas:** kiekvienos savaitės ataskaita išsaugoma (`reports/` ir svetainės datos pasirinkimas).

## Paleidimas (~20 min., vieną kartą)

### 1. Repozitorija
Sukurk naują GitHub repozitoriją ir įkelk šiuos failus. Viešai repozitorijai GitHub Pages nemokamas; privačiai reikia GitHub Pro.

### 2. Raktai
**Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Ar būtinas | Iš kur |
|---|---|---|
| `ANTHROPIC_API_KEY` | Taip | [console.anthropic.com](https://console.anthropic.com) → API Keys |
| `APIFY_TOKEN` | Vienas iš dviejų Instagram būdų | [apify.com](https://apify.com) → Settings → API & Integrations |
| `IG_USER_ID` + `IG_ACCESS_TOKEN` | Kitas Instagram būdas | Meta for Developers (žr. žemiau) |

**Kurį Instagram būdą rinktis?**
- **Apify** (rekomenduojama pradžiai): paprasčiausia nustatyti, mato reels peržiūras. Mokamas pagal naudojimą. 15 kūrėjų kartą per savaitę dažniausiai telpa į nemokamą mėnesio kreditą, bet kainą pasitikrink Apify svetainėje. Duomenys renkami iš viešų puslapių, o tai Instagram taisyklių atžvilgiu yra pilkoji zona.
- **Oficialus Graph API** (nemokamas): reikia tavo Instagram Business arba Creator paskyros, susietos su Facebook puslapiu, ir Meta programėlės su `instagram_basic` leidimu. Mato kitų verslo ir kūrėjų paskyrų aprašymus, like'us ir komentarus, bet ne peržiūras. Asmeninių paskyrų nemato.

Jei nustatyti abu, naudojamas Apify. Jei nenustatytas nė vienas, įrankis veikia tik su portalais.

### 3. Leidimai
**Settings → Actions → General → Workflow permissions → Read and write permissions.**

### 4. Svetainė
**Settings → Pages → Source: Deploy from a branch → Branch: `main`, folder: `/docs`.**

### 5. Pirmas paleidimas
**Actions → Savaitinė ataskaita → Run workflow.** Po ~5–15 min. svetainė bus adresu `https://<tavo-vardas>.github.io/<repo>/`.

## Kaip tai veikia

| Kada | Kas vyksta |
|---|---|
| Kasdien ~6:17 | Surenkami portalų RSS (jie laiko tik paskutinius įrašus, todėl renkama kasdien) |
| Pirmadieniais ~7:47 | Instagram + portalai → Claude priskiria temas → metrikos → idėjos → svetainė |
| Kai sukuri issue `[pridėti] @...` | Kūrėjas pridedamas į sąrašą |

Bet kurį workflow galima paleisti rankiniu būdu skiltyje Actions.

**Svarbu:** portalų momentum įsibėgėja per 3–4 savaites, nes RSS saugo tik naujausius įrašus. Instagram istorija (35 d.) surenkama iškart.

## Ką gali keisti

| Failas | Kam |
|---|---|
| `config/profile.md` | Tavo pozicionavimas, tonas ir apie ką nekalbi. Nuo to priklauso tinkamumo balas ir idėjos. **Užpildyk pirmiausia.** Pakeitus paleisk `python run.py rescore-fit` |
| `config/creators.yml` | Stebimi kūrėjai (arba per svetainę) |
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
python run.py weekly          # tikras paleidimas → docs/index.html
```

## Kaina

Claude API: maždaug 0,3–1 $ per savaitinį paleidimą (pirmas brangesnis, nes žymima visa istorija). Apify: pagal naudojimą. GitHub Actions ir Pages viešai repozitorijai nemokami.

## Kitos versijos

- v2: hook'ų biblioteka, reels transkripcijos, turinio juodraščiai tavo balsu, perpanaudojimas į Substack ir LinkedIn
- v3: tavo Instagram Insights grįžtamasis ryšys, teiginių sekimas, prognozių tikslumas, TikTok ir LinkedIn šaltiniai
