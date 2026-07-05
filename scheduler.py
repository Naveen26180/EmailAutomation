"""
scheduler.py — Background email sender for scheduled sends.

Runs as a daemon thread started once by app.py via st.cache_resource.
Every 60 seconds it:
  1. Queries the DB for any 'scheduled' rows whose scheduled_time <= now
  2. Sends each one using SENDER_EMAIL / APP_PASSWORD from the environment
  3. Marks the row as 'sent' or 'failed' in the DB
  4. Logs the send to the history table

Because it is a daemon thread it dies automatically when the Streamlit
process exits — no cleanup required.
"""

import os
import time
import threading
import logging
from datetime import datetime

import db
import mailer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [scheduler] %(message)s")
log = logging.getLogger("scheduler")

_started = False
_lock = threading.Lock()


def _run_loop(check_interval: int = 60):
    """Poll the database and fire off due emails."""
    log.info("Scheduler thread started. Checking every %ds.", check_interval)
    while True:
        try:
            sender_email = os.environ.get("SENDER_EMAIL", "")
            app_password = os.environ.get("APP_PASSWORD", "")

            if not sender_email or not app_password:
                log.warning("SENDER_EMAIL or APP_PASSWORD not set — skipping cycle.")
            else:
                due = db.get_due_scheduled_sends()
                if due:
                    log.info("%d email(s) due to send.", len(due))
                for row in due:
                    try:
                        ok, msg = mailer.send_email(
                            recipient_email=row["recipient_email"],
                            subject=row["subject"],
                            body=row["body"],
                            sender_email=sender_email,
                            app_password=app_password,
                            is_html=False,
                        )
                        status = "sent" if ok else "failed"
                        db.mark_scheduled_send(row["id"], status)
                        db.add_history(
                            recipient_email=row["recipient_email"],
                            recipient_name=row["recipient_name"] or "",
                            platform=row["platform"] or "Email",
                            subject=row["subject"],
                            body=row["body"],
                            purpose="Scheduled send",
                            tone="",
                            status=status,
                            error_message=None if ok else msg,
                        )
                        log.info(
                            "Scheduled send id=%d to %s → %s",
                            row["id"], row["recipient_email"], status,
                        )
                    except Exception as exc:
                        log.error("Error sending id=%d: %s", row["id"], exc)
                        db.mark_scheduled_send(row["id"], "failed")

        except Exception as exc:
            log.error("Scheduler loop error: %s", exc)

        time.sleep(check_interval)


def start(check_interval: int = 60):
    """Start the background scheduler thread (idempotent — safe to call multiple times)."""
    global _started
    with _lock:
        if _started:
            return
        t = threading.Thread(target=_run_loop, args=(check_interval,), daemon=True, name="email-scheduler")
        t.start()
        _started = True
        log.info("Scheduler daemon thread launched.")
