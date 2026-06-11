"""
Trend Intelligence Agent
========================
Fetches trending searches via SerpAPI (Google Trends),
enriches each trend with a quick web search for context,
then uses Claude API to write a Polish narrative analysis.
Sends the result as a styled HTML email report to multiple recipients.

Regions: PL, DE, US
Schedule: run nightly via Cloud Scheduler + Cloud Run / Cloud Functions
"""

import os
import datetime
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests

# ── Config ────────────────────────────────────────────────────────────────────
RECIPIENT_EMAILS  = [e.strip() for e in os.environ.get("RECIPIENT_EMAILS", "").split(",") if e.strip()]
SENDER_EMAIL      = os.environ.get("SENDER_EMAIL", "")
SENDER_PASSWORD   = os.environ.get("SENDER_PASSWORD", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SERPAPI_KEY       = os.environ.get("SERPAPI_KEY", "")

TOP_N = 10
CONTEXT_TERMS = 5   # how many top trends to enrich with web search (saves API quota)

COUNTRIES = {
    "Polska":         "PL",
    "Niemcy":         "DE",
    "Stany Zjednoczone": "US",
}
# ─────────────────────────────────────────────────────────────────────────────


def fetch_trends(geo: str, top_n: int = TOP_N) -> list[str]:
    """Return top N daily trending searches via SerpAPI."""
    params = {
        "engine": "google_trends_trending_now",
        "geo": geo,
        "api_key": SERPAPI_KEY,
    }
    try:
        response = requests.get("https://serpapi.com/search", params=params, timeout=15)
        data = response.json()
        searches = data.get("trending_searches", [])
        return [item["query"] for item in searches[:top_n]]
    except Exception as e:
        print(f"  [warn] Could not fetch trends for {geo}: {e}")
        return []


def fetch_context_for_term(term: str) -> str:
    """Search the web for a trending term and return a short snippet of context."""
    params = {
        "engine": "google",
        "q": term,
        "num": 3,
        "api_key": SERPAPI_KEY,
        "hl": "en",
    }
    try:
        response = requests.get("https://serpapi.com/search", params=params, timeout=15)
        data = response.json()
        results = data.get("organic_results", [])
        snippets = [r.get("snippet", "") for r in results[:3] if r.get("snippet")]
        return " | ".join(snippets) if snippets else "brak kontekstu"
    except Exception as e:
        print(f"  [warn] Context fetch failed for '{term}': {e}")
        return "brak kontekstu"


def enrich_trends(trends_by_country: dict) -> dict:
    """
    For the top CONTEXT_TERMS trends across all countries (deduplicated),
    fetch web context. Returns dict: term -> context snippet.
    """
    # collect unique top terms across all countries
    seen = set()
    top_terms = []
    for terms in trends_by_country.values():
        for t in terms[:CONTEXT_TERMS]:
            if t.lower() not in seen:
                seen.add(t.lower())
                top_terms.append(t)
        if len(top_terms) >= CONTEXT_TERMS * 2:
            break

    print(f"   Enriching {len(top_terms)} unique terms with web context...")
    context_map = {}
    for term in top_terms:
        print(f"   • {term}")
        context_map[term] = fetch_context_for_term(term)

    return context_map


def build_claude_prompt(trends_by_country: dict, context_map: dict) -> str:
    lines = []
    for country, terms in trends_by_country.items():
        lines.append(f"\n{country}: {', '.join(terms) if terms else 'brak danych'}")

    context_lines = []
    for term, ctx in context_map.items():
        context_lines.append(f"- {term}: {ctx}")

    data_block    = "\n".join(lines)
    context_block = "\n".join(context_lines)

    return f"""Jesteś analitykiem rynku i trendów konsumenckich. Piszesz po polsku.
Poniżej znajdują się dzisiejsze topowe wyszukiwania Google w trzech krajach oraz krótki kontekst dla wybranych haseł.

TRENDY:
{data_block}

KONTEKST (wyniki wyszukiwania dla wybranych haseł):
{context_block}

Napisz krótki, angażujący raport (~250–350 słów) w języku polskim, który:
1. Omawia najciekawsze i najbardziej zaskakujące trendy w każdym kraju.
2. Wskazuje wspólne tematy lub wzorce pojawiające się w kilku krajach jednocześnie.
3. Komentuje co te trendy mogą oznaczać dla zachowań konsumentów lub e-commerce.
4. Jest napisany płynną prozą — bez list punktowanych, jak artykuł analityczny.
5. Wykorzystuje kontekst z wyników wyszukiwania żeby precyzyjnie wyjaśnić dlaczego dane hasło trenduje.

Nie wymyślaj faktów. Jeśli hasło jest niejednoznaczne, powiedz to wprost.
Zakończ jednym zdaniem "Kluczowy wniosek na dziś:".
"""


def ask_claude(prompt: str) -> str:
    """Send prompt to Claude and return the text response."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def build_html_report(trends_by_country: dict, narrative: str, date_str: str) -> str:
    """Render a clean, styled HTML email report."""

    def trend_list_html(terms: list[str]) -> str:
        if not terms:
            return "<p class='no-data'>Brak danych.</p>"
        items = "".join(
            f'<li><span class="rank">{i+1}</span>{term}</li>'
            for i, term in enumerate(terms)
        )
        return f"<ol>{items}</ol>"

    flag = {"Polska": "🇵🇱", "Niemcy": "🇩🇪", "Stany Zjednoczone": "🇺🇸"}
    country_blocks = ""
    for country, terms in trends_by_country.items():
        country_blocks += f"""
        <div class="country-block">
          <h3>{flag.get(country, "")} {country}</h3>
          {trend_list_html(terms)}
        </div>
        """

    narrative_html = "".join(
        f"<p>{p.strip()}</p>"
        for p in narrative.split("\n\n")
        if p.strip()
    )

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trend Pulse – {date_str}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=Source+Sans+3:wght@400;600&display=swap');

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: #f4f1ec;
    font-family: 'Source Sans 3', sans-serif;
    color: #1a1a1a;
    padding: 32px 16px;
  }}

  .wrapper {{
    max-width: 680px;
    margin: 0 auto;
    background: #fff;
    border-radius: 4px;
    overflow: hidden;
    box-shadow: 0 4px 32px rgba(0,0,0,0.08);
  }}

  .header {{
    background: #0f1117;
    color: #fff;
    padding: 40px 48px 32px;
    border-bottom: 4px solid #e8c547;
  }}

  .header .label {{
    font-size: 11px;
    letter-spacing: 3px;
    text-transform: uppercase;
    color: #e8c547;
    margin-bottom: 12px;
  }}

  .header h1 {{
    font-family: 'Playfair Display', serif;
    font-size: 32px;
    line-height: 1.2;
    margin-bottom: 8px;
  }}

  .header .date {{
    font-size: 14px;
    color: #aaa;
  }}

  .section {{
    padding: 40px 48px;
    border-bottom: 1px solid #f0ede8;
  }}

  .section h2 {{
    font-family: 'Playfair Display', serif;
    font-size: 20px;
    margin-bottom: 24px;
    color: #0f1117;
  }}

  .trends-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 24px;
  }}

  .country-block h3 {{
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: #666;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 2px solid #e8c547;
  }}

  .country-block ol {{ list-style: none; padding: 0; }}

  .country-block li {{
    display: flex;
    align-items: baseline;
    gap: 8px;
    font-size: 14px;
    padding: 5px 0;
    border-bottom: 1px solid #f5f2ee;
    color: #1a1a1a;
  }}

  .country-block li .rank {{
    font-size: 11px;
    font-weight: 600;
    color: #e8c547;
    min-width: 16px;
  }}

  .narrative p {{
    font-size: 15px;
    line-height: 1.75;
    color: #333;
    margin-bottom: 16px;
  }}

  .narrative p:last-child {{
    font-weight: 600;
    color: #0f1117;
    border-left: 3px solid #e8c547;
    padding-left: 16px;
    margin-top: 24px;
  }}

  .footer {{
    padding: 24px 48px;
    background: #faf8f5;
    font-size: 12px;
    color: #999;
    text-align: center;
  }}

  .no-data {{ font-size: 13px; color: #aaa; font-style: italic; }}
</style>
</head>
<body>
<div class="wrapper">

  <div class="header">
    <div class="label">Dzienny Raport Trendów</div>
    <h1>Trend Pulse</h1>
    <div class="date">{date_str} · Polska · Niemcy · USA</div>
  </div>

  <div class="section">
    <h2>Topowe wyszukiwania</h2>
    <div class="trends-grid">
      {country_blocks}
    </div>
  </div>

  <div class="section">
    <h2>Analiza</h2>
    <div class="narrative">
      {narrative_html}
    </div>
  </div>

  <div class="footer">
    Wygenerowano automatycznie przez Trend Intelligence Agent &nbsp;·&nbsp;
    Google Trends + Claude AI &nbsp;·&nbsp; {date_str}
  </div>

</div>
</body>
</html>"""


def send_email(subject: str, html_body: str) -> None:
    """Send HTML email to all recipients via Gmail SMTP."""
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        for recipient in RECIPIENT_EMAILS:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = SENDER_EMAIL
            msg["To"]      = recipient
            msg.attach(MIMEText(html_body, "html"))
            server.sendmail(SENDER_EMAIL, recipient, msg.as_string())
            print(f"  [ok] Email sent to {recipient}")


def run():
    date_str = datetime.date.today().strftime("%d %B %Y")
    print(f"\n=== Trend Intelligence Agent — {date_str} ===\n")

    # 1. Fetch trends
    print("1. Pobieranie trendów z Google...")
    trends_by_country = {}
    for country_name, geo_code in COUNTRIES.items():
        print(f"   • {country_name} ({geo_code})")
        trends_by_country[country_name] = fetch_trends(geo_code)

    # 2. Enrich top trends with web context
    print("\n2. Wyszukiwanie kontekstu dla topowych haseł...")
    context_map = enrich_trends(trends_by_country)

    # 3. Ask Claude for Polish narrative
    print("\n3. Generowanie analizy przez Claude...")
    prompt    = build_claude_prompt(trends_by_country, context_map)
    narrative = ask_claude(prompt)
    print("   Gotowe.")

    # 4. Build HTML report
    print("\n4. Renderowanie raportu HTML...")
    html = build_html_report(trends_by_country, narrative, date_str)

    # 5. Send email(s)
    subject = f"📊 Trend Pulse – {date_str}"
    print(f"\n5. Wysyłanie emaila: '{subject}'")
    send_email(subject, html)

    print("\n=== Gotowe ✓ ===\n")


if __name__ == "__main__":
    run()
