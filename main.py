"""
GCP Cloud Function entry point
================================
Deploy this alongside trend_agent.py as a Cloud Function (2nd gen).

Environment variables to set in Cloud Function config:
  RECIPIENT_EMAIL   – email address to send the report to
  SENDER_EMAIL      – Gmail address used to send
  SENDER_PASSWORD   – Gmail App Password (not your main password!)
  ANTHROPIC_API_KEY – your Anthropic API key

Trigger: Cloud Scheduler → Pub/Sub or HTTP trigger
Example schedule: 0 22 * * *  (every day at 22:00 UTC = ~23:00 CET)
"""

import functions_framework
from trend_agent import run


@functions_framework.http
def trend_report(request):
    """HTTP Cloud Function entry point."""
    try:
        run()
        return ("Report sent successfully.", 200)
    except Exception as e:
        print(f"[error] {e}")
        return (f"Error: {e}", 500)
