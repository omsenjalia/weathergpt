# WeatherGPT backend

One FastAPI service for the **weathergpt** web app, **weathergpt-app** and **weathergpt-android**.

```bash
pip install -r requirements-dev.txt
cp .env.example .env        # add keys; everything is optional except what you want to use
uvicorn main:app --reload --port 8888
python -m pytest            # offline: every upstream is faked
```

Vercel: project root `backend/`, entry `api/index.py` (all paths rewritten to it by `vercel.json`).

## Data flow

```
request ─► provider chain ─────────────► supplement ─► payload
           IMD ► WeatherNext ► Open-Meteo   (null fields     (nested v2 + flat legacy,
           first fresh answer wins          from Open-Meteo,  field_sources, provenance,
           pinned source: never substituted attributed)       official alerts)
```

| Provider | Supplies | Needs |
|---|---|---|
| **IMD** | nearest city station (≤ 35 km): observed current conditions + official 7-day forecast; district warnings & nowcast | `IMD_API_KEY` + `IMD_JWT_TOKEN`, egress IP whitelisted by IMD |
| **WeatherNext** | hourly 64-member ensemble statistics (mean, p10–p90), 15 days | `WEATHERNEXT_ENABLED=1`, BigQuery table + Google credentials |
| **Open-Meteo** | global baseline; hourly, UV, AQI, sun times; ERA5 archive | nothing |

Official warnings: IMD district warnings/nowcast (when configured) and the key-less NDMA **SACHET** CAP feed,
matched to the point by alert polygon. If no channel answers, `alerts_status` is `unknown` — never "no alerts".

`degraded` is true only for real failures; providers that don't apply (not configured, outside India, no IMD
station nearby) are listed in `fallback_reasons` but don't degrade.

## Endpoints

| Route | Used by |
|---|---|
| `GET /v2/weather` · `GET /weather` | both apps (home) — same payload; unavailable = 200 `status:"unavailable"` / 502 |
| `POST /chat` · `POST /voice` | all clients — `{response, meta, card}`; `card` holds live numbers for the mobile result screen |
| `GET /advisory` | farm action windows (hourly bands, best window, official warnings, optional System One) |
| `GET /historical` · `GET /comparison` | researcher screens (ERA5 yearly series) |
| `GET /v2/alerts` | official warnings for a point |
| `GET /v2/imd` · `GET /v2/imd/{endpoint}` · `GET /v2/imd/nearest` | every IMD gateway API, proxied with server-side keys |
| `GET /v2/weather/series` · `/catalog` · `/health` | researcher + Debug screen |
| `GET /v2/speech/health` · `POST /v2/speech/tts` · `POST /v2/speech/asr` | Bhashini voice |
| `GET /health` · `GET /dev` · `POST /dev/sandbox` · `GET /dev/intent` · `GET /dev/forecast` | web Dev Suite |
| `GET /dev/imd/probe` · `POST /dev/reset` | operators (`X-Admin-Token`) |

### IMD endpoints

`GET /v2/imd` lists all 30 (28 APIs + 2 mapping helpers). 22 paths are documented publicly; 8 (agromet, radar,
lightning, Mausamgram, fishermen, two highway, all-India bulletin) are provisional until confirmed from the IMD
portal — override with `IMD_ENDPOINT_<KEY>`. After adding credentials, call
`GET /dev/imd/probe` (header `X-Admin-Token`) to test every endpoint at once.

Note the colour scales: `districtwarning` uses 1 = red … 4 = green, `districtnowcast` uses 1 = green … 4 = red.

## Layout

```
weathergpt/
  config.py  http.py  runtime.py  geo.py  app.py
  weather/   models, codes, service (chain), supplement, payloads, summaries, archive, providers/{imd,weathernext,open_meteo}
  imd/       endpoints (registry), client (auth/errors/cache), stations, parse
  alerts/    imd_district, sachet, service
  weathernext/ bigquery, normalize, auth
  farm/      advisory
  ai/        chat (orchestrator), evidence (card/reply/facts), intent, place, agent, tools, typesafe, sanitize
  speech/    bhashini
  api/       routers
```

Rules: missing values are `null`, never 0 (`weather_code` 0 is "clear sky"); all times in payloads are UTC ISO
except daily `date` and `sunrise`/`sunset`, which are location-local.
