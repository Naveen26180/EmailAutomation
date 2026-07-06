# AI Outreach Assistant — Prototype

A Streamlit app that drafts platform-aware, personalized outreach messages
using Grok (xAI), with local persistence for contacts, templates, voice
profiles, and send history.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in your keys
streamlit run app.py
```

You'll need:
- An xAI API key (console.groq.ai)
- A Gmail app password (myaccount.google.com/apppasswords — requires 2FA)

First run creates `outreach.db` (SQLite) in the project folder automatically.

## File map

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI — Compose / Contacts / Templates / Voice Profiles / History tabs |
| `ai.py` | Grok integration — the master system prompt + structured JSON generation call |
| `db.py` | SQLite persistence — contacts, templates, voice profiles, history |
| `checks.py` | Deterministic pre-send checks (word count, spam keywords, checklist) — no API cost |
| `mailer.py` | Gmail SMTP sending |
| `.env.example` | Template for your secrets |

## How Compose works

1. Pick a platform (Email, LinkedIn Connection, LinkedIn DM, X DM, Slack, Discord)
2. Optionally load a saved contact, or enter recipient details manually
3. Subject (email only) is a plain editable field with a small **AI assist** button beside it
4. AI assist opens a panel: preset, tone, purpose, key points, optional saved template, optional voice profile → one Grok call drafts the message, subject variants, CTA, and a short rationale
5. Body is always editable, AI-filled or hand-typed
6. **Regenerate with feedback** — quick buttons ("make it shorter," "more confident," etc.) or custom feedback, revises the existing draft instead of starting over
7. **Pre-send review** — instant, local, no API cost: word/char count, reading time, spam-keyword flags, platform length check, and a checklist (greeting, sign-off, subject, etc.)
8. **Send** — always a separate, explicit, manual action. Every attempt (success or failure) is logged to History.

## Known limitations (by design, for a prototype)

- Single user, local only — no auth, no multi-device sync
- SMTP + app password, not Gmail OAuth (fine locally, not for a shared/public deploy)
- No rate limiting on sends — be mindful of Gmail's ~500/day, ~20/hour informal limits if testing repeatedly
- No scheduling, no bulk/CSV sends, no open/click tracking — these need a real backend (see `PROJECT_OVERVIEW.md`)
