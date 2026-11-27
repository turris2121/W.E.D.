# World Politics Dashboard

A self-updating dashboard covering about 195 countries:

- **Politics:** the form of government; the head of state and head of government and how each is chosen; the legislature's chambers, with seats, electoral system, term length and last election; and national elections from the past 2 years plus upcoming ones, with winners where recorded.
- **Economy:** population, GDP, GDP per capita, growth and inflation (World Bank); currency and exchange rate against the US dollar (updated daily).

Every day at 06:00 UTC a GitHub Action runs `scripts/fetch_all.py`, commits the new data and redeploys the site to GitHub Pages.

## Data sources (all free, no API keys)

| Source | Provides | Refreshed |
|---|---|---|
| [Wikidata](https://www.wikidata.org) + [World Bank](https://data.worldbank.org) | country list, capitals, currencies, regions | weekly |
| [World Bank API](https://data.worldbank.org) | population, GDP, GDP per capita, growth, inflation | daily (data itself is annual) |
| [open.er-api.com](https://www.exchangerate-api.com/docs/free) | USD exchange rates | every 12 h |
| [Wikidata SPARQL](https://query.wikidata.org) | government form, leaders, how offices are filled, elections | daily |
| [IPU Parline](https://data.ipu.org) | chambers, seats, electoral system, term, last election | weekly |
| [BIS](https://data.bis.org) | central bank policy rates, CPI inflation, exchange rates (13 central banks) | daily |

If a source fails, the previous copy in `data/raw/` is used and the page shows a warning.

## Setup (one time)

1. **Install git and Python on your Mac** (if you haven't already): run `xcode-select --install`.
2. **Create a GitHub repo** and push this folder:
   ```sh
   cd ~/world-dashboard
   git init -b main && git add . && git commit -m "Initial dashboard"
   git remote add origin https://github.com/<you>/world-dashboard.git
   git push -u origin main
   ```
3. In the repo, open **Settings → Pages** and set **Source** to **GitHub Actions**.
4. Open the **Actions** tab, choose **Update dashboard**, then **Run workflow**. When it finishes, the site is at `https://<you>.github.io/world-dashboard/`.

## Run locally

```sh
pip3 install -r requirements.txt
python3 scripts/fetch_all.py            # add --force to ignore cache ages
python3 -m http.server -d site 8000     # then open http://localhost:8000
```

At the end the script prints a coverage report: the percentage of countries that have each field.

## Fixing or adding data

Wikidata is crowd-edited and doesn't record every detail (how a head of state is chosen is the most common gap). To correct a country, add it to `scripts/overrides.json` under its ISO3 code. Overrides are merged on top of the fetched data and always win:

```json
"ITA": { "politics": { "head_of_state": { "selection": "Elected by Parliament in joint session plus regional delegates" } } }
```

## Notes
- The "Next (estimated)" legislative date is the last election year plus the term length. Snap elections can make it wrong. Dates from Wikidata take priority.
- GitHub turns off scheduled workflows in repos with no activity for 60 days. The daily data commits normally count as activity.
- IPU data is licensed CC BY-NC-SA 4.0 (non-commercial).
