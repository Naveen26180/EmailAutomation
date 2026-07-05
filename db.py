"""
SQLite persistence layer.
Everything lives in one local file: outreach.db (created on first run).
No server, no auth — this is the prototype's local-only data store.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_PATH = "outreach.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT NOT NULL,
                context TEXT,
                summary TEXT,
                notes TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voice_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sample_text TEXT NOT NULL,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                platform TEXT NOT NULL,
                body_template TEXT NOT NULL,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_email TEXT,
                recipient_name TEXT,
                platform TEXT,
                subject TEXT,
                body TEXT,
                purpose TEXT,
                tone TEXT,
                status TEXT,
                error_message TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_sends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_email TEXT,
                recipient_name TEXT,
                subject TEXT,
                body TEXT,
                platform TEXT,
                scheduled_time TEXT,
                status TEXT,
                created_at TEXT
            )
        """)


# ---------- Contacts ----------

def add_contact(name, email, context, summary, notes):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO contacts (name, email, context, summary, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name, email, context, summary, notes, datetime.now().isoformat()),
        )


def list_contacts():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM contacts ORDER BY name COLLATE NOCASE").fetchall()


def delete_contact(contact_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))


# ---------- Voice profiles ----------

def add_voice_profile(name, sample_text):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO voice_profiles (name, sample_text, created_at) VALUES (?, ?, ?)",
            (name, sample_text, datetime.now().isoformat()),
        )


def list_voice_profiles():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM voice_profiles ORDER BY name COLLATE NOCASE").fetchall()


def delete_voice_profile(profile_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM voice_profiles WHERE id = ?", (profile_id,))


# ---------- Templates ----------

def add_template(name, platform, body_template):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO templates (name, platform, body_template, created_at) VALUES (?, ?, ?, ?)",
            (name, platform, body_template, datetime.now().isoformat()),
        )


def list_templates(platform=None):
    with get_conn() as conn:
        if platform:
            return conn.execute(
                "SELECT * FROM templates WHERE platform = ? ORDER BY name COLLATE NOCASE", (platform,)
            ).fetchall()
        return conn.execute("SELECT * FROM templates ORDER BY name COLLATE NOCASE").fetchall()


def delete_template(template_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))


# ---------- History ----------

def add_history(recipient_email, recipient_name, platform, subject, body,
                 purpose, tone, status, error_message=None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO history
               (recipient_email, recipient_name, platform, subject, body, purpose, tone,
                status, error_message, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (recipient_email, recipient_name, platform, subject, body, purpose, tone,
             status, error_message, datetime.now().isoformat()),
        )


def list_history(limit=100):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM history ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()


# ---------- Scheduled sends ----------

def add_scheduled_send(recipient_email, recipient_name, subject, body, platform, scheduled_time):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO scheduled_sends
               (recipient_email, recipient_name, subject, body, platform, scheduled_time, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (recipient_email, recipient_name, subject, body, platform, scheduled_time, "scheduled", datetime.now().isoformat()),
        )


def list_scheduled_sends():
    with get_conn() as conn:
        return conn.execute("SELECT * FROM scheduled_sends WHERE status = 'scheduled' ORDER BY scheduled_time ASC").fetchall()


def delete_scheduled_send(send_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM scheduled_sends WHERE id = ?", (send_id,))


def get_due_scheduled_sends():
    """Return all 'scheduled' rows whose scheduled_time <= now (ready to send)."""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM scheduled_sends WHERE status = 'scheduled' AND scheduled_time <= ?",
            (now,),
        ).fetchall()


def mark_scheduled_send(send_id, status):
    """Update a scheduled send row after a send attempt."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE scheduled_sends SET status = ? WHERE id = ?",
            (status, send_id),
        )


def stats():
    """Basic local analytics used on the History tab."""
    with get_conn() as conn:
        total_sent = conn.execute(
            "SELECT COUNT(*) c FROM history WHERE status = 'sent'"
        ).fetchone()["c"]
        total_failed = conn.execute(
            "SELECT COUNT(*) c FROM history WHERE status = 'failed'"
        ).fetchone()["c"]
        top_tone = conn.execute(
            "SELECT tone, COUNT(*) c FROM history GROUP BY tone ORDER BY c DESC LIMIT 1"
        ).fetchone()
        top_recipient = conn.execute(
            """SELECT recipient_email, COUNT(*) c FROM history
               GROUP BY recipient_email ORDER BY c DESC LIMIT 1"""
        ).fetchone()
        return {
            "total_sent": total_sent,
            "total_failed": total_failed,
            "top_tone": top_tone["tone"] if top_tone else "—",
            "top_recipient": top_recipient["recipient_email"] if top_recipient else "—",
        }
