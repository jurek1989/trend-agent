# trend-agent

Autonomous agent that runs nightly, pulls the top 10 Google trending searches for Poland, Germany, and the United States, enriches each trend with live web search results, asks Claude to write a Polish-language market narrative, and delivers the finished report as a styled HTML email.

Deployed on GCP Cloud Run + Cloud Scheduler. No servers to manage, no manual steps.

---

## What it does and why

Tracking what people search for in real time is a cheap signal for consumer intent, news cycles, and cross-market patterns. The agent automates the full loop that would otherwise require opening three browser tabs, reading news snippets, and writing a summary by hand — every day.

The output is a single email with two parts: the raw ranked trend lists per country, and a 250–350 word analytical narrative (written by Claude in Polish) that explains *why* specific terms are trending, flags cross-country patterns, and ends with a single "Kluczowy wniosek na dziś" takeaway.

---

## How it works

```
Cloud Scheduler (nightly)
        │
        ▼
Cloud Run HTTP trigger  (main.py → trend_agent.run())
        │
        ├── 1. fetch_trends()           SerpAPI google_trends_trending_now
        │       PL · DE · US            top 10 per country
        │
        ├── 2. enrich_trends()          SerpAPI google (organic search)
        │       top ~10 unique terms    3 snippets per term → context string
        │
        ├── 3. build_claude_prompt()    assembles trends + context into prompt
        │       + ask_claude()          claude-sonnet-4-6, max_tokens=1200
        │                               → Polish narrative prose
        │
        ├── 4. build_html_report()      styled HTML: ranked lists + narrative
        │                               Playfair Display header, yellow accents
        │
        └── 5. send_email()             Gmail SMTP_SSL (port 465)
                                        sends to all RECIPIENT_EMAILS
```

**SerpAPI usage per run:** 3 calls for trends (one per country) + up to ~10 calls for web context enrichment. Deduplication across countries keeps enrichment calls within the free tier for moderate use.

---

## Stack

| Layer | Technology |
|---|---|
| Agent logic | Python 3.11 |
| Trend data | SerpAPI — `google_trends_trending_now` engine |
| Web context | SerpAPI — `google` organic search (3 snippets per term) |
| Analysis | Anthropic Claude (`claude-sonnet-4-6`) |
| Email delivery | Gmail SMTP_SSL, port 465 |
| Runtime | GCP Cloud Run (HTTP service) |
| Scheduling | GCP Cloud Scheduler |
| Entry point | `functions-framework` HTTP handler |

---

## Setup

### Environment variables

Set these in Cloud Run (or export locally for testing):

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `SERPAPI_KEY` | SerpAPI key |
| `SENDER_EMAIL` | Gmail address used to send the report |
| `SENDER_PASSWORD` | Gmail App Password (not the account password) |
| `RECIPIENT_EMAILS` | Comma-separated list of recipient addresses |

### Run locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
export SERPAPI_KEY=...
export SENDER_EMAIL=...
export SENDER_PASSWORD=...
export RECIPIENT_EMAILS=you@example.com

python trend_agent.py
```

### Deploy to Cloud Run

```bash
# Build and deploy from source (uses Cloud Buildpacks — no Dockerfile needed)
gcloud run deploy trend-agent \
  --source . \
  --region europe-central2 \
  --platform managed \
  --no-allow-unauthenticated \
  --set-env-vars "ANTHROPIC_API_KEY=...,SERPAPI_KEY=...,SENDER_EMAIL=...,SENDER_PASSWORD=...,RECIPIENT_EMAILS=..."
```

For production, pass secrets via Secret Manager instead of `--set-env-vars`:

```bash
--set-secrets "ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,SERPAPI_KEY=SERPAPI_KEY:latest,..."
```

### Create the Cloud Scheduler job

```bash
gcloud scheduler jobs create http trend-agent-nightly \
  --schedule="0 22 * * *" \
  --uri="https://trend-agent-HASH.europe-central2.run.app" \
  --oidc-service-account-email=SA@PROJECT.iam.gserviceaccount.com \
  --location=europe-central2
```

Schedule `0 22 * * *` fires at 22:00 UTC (23:00 CET / midnight CEST).

---

## Project structure

```
trend-agent/
├── trend_agent.py   # all agent logic: fetch → enrich → analyze → render → send
├── main.py          # Cloud Run HTTP entry point (functions-framework handler)
└── requirements.txt
```

`trend_agent.py` is self-contained. `main.py` is a thin wrapper that calls `trend_agent.run()` and returns an HTTP 200/500 response — Cloud Run needs an HTTP handler; Cloud Scheduler hits that endpoint to trigger the nightly run.
