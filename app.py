"""
AI Outreach Assistant — full prototype with advanced features
---------------------------------------------------------------
Tabs: Compose | Contacts | Templates | Voice Profiles | History | Scheduled

Features:
- CSV import with person summaries
- Personalized or generic bulk sends
- HTML email support
- File attachments
- Schedule sends for later
- AI-powered drafting with Grok

Run with:  streamlit run app.py

Required environment variables (.env file next to this script):
    GROQ_API_KEY=your_groq_api_key
    SENDER_EMAIL=your_email@gmail.com
    APP_PASSWORD=your_16_char_gmail_app_password
"""

import os
import re
import time
import csv
import io
from datetime import datetime, timedelta

import streamlit as st
from dotenv import load_dotenv

import ai
import checks
import db
import mailer
import scheduler

load_dotenv()
db.init_db()

st.set_page_config(page_title="AI Outreach Assistant", page_icon="✉️", layout="wide")

# Start background scheduler once per server process (not on every Streamlit rerun)
@st.cache_resource
def _start_scheduler():
    scheduler.start(check_interval=60)  # checks every 60 seconds
    return True

_start_scheduler()

PLATFORMS = list(ai.PLATFORM_RULES.keys())
PRESETS = [
    "None", "Cold Outreach", "Referral Request", "Job Application",
    "Internship Application", "Networking", "Thank You", "Follow-up",
    "Client Proposal",
]
TONES = ["Professional", "Friendly", "Formal", "Casual", "Persuasive", "Warm", "Enthusiastic", "Confident"]
QUICK_FEEDBACK = ["Make it shorter", "More professional", "Friendlier", "More persuasive", "More confident"]

# ---------- Session state defaults ----------
defaults = {
    "subject": "",
    "body": "",
    "show_ai_panel": False,
    "show_schedule_panel": False,
    "sent_status": None,
    "result": None,
    "recipient_name_input": "",
    "recipient_email_input": "",
    "recipient_context_input": "",
    "recipient_summary_input": "",
    "review": None,
    "is_html_mode": False,
    "attachment_files": [],
    "csv_import_count": None,
    "multi_emails": [],          # Compose multi-recipient list
    "signature": "",              # E-signature appended to every send
    # CSV Campaign tab
    "bulk_csv_rows": [],
    "bulk_previews": [],
    "bulk_purpose": "",
    "bulk_sent": False,
    "bulk_show_schedule": False,
    "bulk_attachment_files": [],   # attachments for CSV campaign
    "bulk_signature": "",          # e-signature for CSV campaign
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


def toggle_ai_panel():
    st.session_state.show_ai_panel = not st.session_state.show_ai_panel


# ---------- Sidebar: sender settings ----------
with st.sidebar:
    st.header("Sender settings")
    sender_name = st.text_input("Your name (used in sign-off)")
    sender_email_input = st.text_input("Gmail address", value=os.environ.get("SENDER_EMAIL", ""))
    app_password_input = st.text_input(
        "Gmail app password", value=os.environ.get("APP_PASSWORD", ""), type="password",
        help="Generate one at myaccount.google.com/apppasswords (requires 2FA).",
    )
    st.divider()
    st.caption("Credentials are session-only. All data stored locally in outreach.db.")

st.title("✉️ AI Outreach Assistant")

tab_compose, tab_bulk, tab_contacts, tab_templates, tab_voices, tab_history, tab_scheduled = st.tabs(
    ["✍️ Compose", "📎 CSV Campaign", "📇 Contacts", "🗂️ Templates", "🎙️ Voice Profiles", "🕓 History", "📅 Scheduled"]
)

# =========================================================
# COMPOSE TAB
# =========================================================
with tab_compose:
    platform = st.selectbox("Platform", PLATFORMS, key="compose_platform")

    # --- Load from saved contact ---
    contacts = db.list_contacts()
    contact_options = ["— Manual entry —"] + [f"{c['name']} <{c['email']}>" for c in contacts]
    chosen = st.selectbox("Recipient", contact_options, key="contact_select")
    if chosen != "— Manual entry —":
        matched = contacts[contact_options.index(chosen) - 1]
        if st.button("Load this contact into the form"):
            st.session_state.recipient_name_input = matched["name"] or ""
            st.session_state.recipient_email_input = matched["email"] or ""
            st.session_state.recipient_context_input = matched["context"] or ""
            st.session_state.recipient_summary_input = matched["summary"] or ""

    recipient_email = st.text_input("Recipient's email", key="recipient_email_input")

    # --- Multi-recipient toggle (paste emails, no CSV upload) ---
    multi_mode = st.checkbox(
        "📧 Send same message to multiple recipients",
        help="Paste email addresses below — everyone gets the exact same composed message.",
        key="compose_multi_mode",
    )
    if multi_mode:
        multi_text = st.text_area(
            "Recipient emails — one per line or comma-separated",
            height=75,
            placeholder="alice@example.com\nbob@example.com\ncarol@example.com",
            key="compose_multi_text",
        )
        raw_multi = re.split(r"[,\n]", multi_text)
        st.session_state.multi_emails = [e.strip() for e in raw_multi if e.strip()]
        valid_multi = [e for e in st.session_state.multi_emails if mailer.is_valid_email(e)]
        invalid_multi = [e for e in st.session_state.multi_emails if e and not mailer.is_valid_email(e)]
        if st.session_state.multi_emails:
            st.caption(
                f"✅ {len(valid_multi)} valid email{'s' if len(valid_multi) != 1 else ''}"
                + (f" — ⚠️ {len(invalid_multi)} invalid" if invalid_multi else "")
            )

    # --- Subject + AI assist ---
    if platform == "Email":
        subj_col, btn_col = st.columns([5, 1])
        with subj_col:
            st.session_state.subject = st.text_input("Subject", value=st.session_state.subject)
        with btn_col:
            st.write("")
            st.write("")
            st.button("🤖 AI assist", on_click=toggle_ai_panel, use_container_width=True, key="ai_btn")

    # --- AI assist panel ---
    if st.session_state.show_ai_panel:
        with st.container(border=True):
            st.markdown("**Answer questions, Grok drafts the message**")

            recipient_name = st.text_input("Recipient's name", key="recipient_name_input")
            recipient_context = st.text_input("Who are they to you?", key="recipient_context_input")
            recipient_summary = st.text_area("Their summary/bio", key="recipient_summary_input", height=70)

            col_a, col_b = st.columns(2)
            with col_a:
                preset = st.selectbox("Preset type", PRESETS, key="compose_preset")
            with col_b:
                tone = st.selectbox("Tone", TONES, key="compose_tone")

            purpose = st.text_area("What's this message for?", height=80, key="compose_purpose")
            key_points = st.text_area("Key points to include", height=70, key="compose_keypoints")

            templates_for_platform = db.list_templates(platform)
            template_options = ["None"] + [t["name"] for t in templates_for_platform]
            template_choice = st.selectbox("Use a template?", template_options, key="compose_template")
            template_text = ""
            if template_choice != "None":
                template_text = next(t["body_template"] for t in templates_for_platform if t["name"] == template_choice)

            voice_profiles = db.list_voice_profiles()
            voice_options = ["None"] + [v["name"] for v in voice_profiles]
            voice_choice = st.selectbox("Match a voice profile?", voice_options, key="compose_voice")
            voice_sample = ""
            if voice_choice != "None":
                voice_sample = next(v["sample_text"] for v in voice_profiles if v["name"] == voice_choice)

            generate_clicked = st.button("✨ Generate", type="primary", use_container_width=True, key="gen_btn")

            if generate_clicked:
                if not purpose.strip():
                    st.warning("Describe the purpose.")
                else:
                    with st.spinner("Drafting..."):
                        try:
                            result = ai.generate_message(
                                platform=platform, sender_name=sender_name, purpose=purpose, tone=tone,
                                recipient_name=recipient_name, recipient_context=recipient_context,
                                key_points=key_points, email_type_preset=preset,
                                template_text=template_text, voice_profile_sample=voice_sample,
                            )
                            st.session_state.result = result
                            st.session_state.body = result["message"]
                            if result["subject_variants"] and platform == "Email":
                                st.session_state.subject = result["subject_variants"][0]
                            st.session_state.show_ai_panel = False
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed: {e}")

    # --- Result metadata ---
    result = st.session_state.result
    if result:
        if result.get("subject_variants") and platform == "Email":
            chosen_subject = st.radio("Subject options", result["subject_variants"], index=0)
            st.session_state.subject = chosen_subject
        if result.get("rationale"):
            st.caption(f"💡 {result['rationale']}")

    # --- Format options + Attachments ---
    fmt_col, attach_col = st.columns(2)
    with fmt_col:
        st.session_state.is_html_mode = st.checkbox("📄 HTML mode", value=st.session_state.is_html_mode)
    with attach_col:
        uploaded_files = st.file_uploader(
            "📎 Attach files (PDF, DOCX, images…)",
            accept_multiple_files=True, key="attachments",
            help="Attach your resume, portfolio, or any document.",
        )
        st.session_state.attachment_files = uploaded_files if uploaded_files else []

    # --- Body ---
    st.session_state.body = st.text_area(
        "Message", value=st.session_state.body, height=280,
    )

    # --- E-Signature ---
    with st.expander("✍️ E-Signature (appended to every email)"):
        sig = st.text_area(
            "Your signature",
            value=st.session_state.signature,
            height=100,
            placeholder="Best regards,\nYour Name\nPhone | LinkedIn | Portfolio URL",
            key="compose_signature_input",
        )
        st.session_state.signature = sig
        if sig:
            st.caption("Preview:")
            st.code(sig, language=None)

    # --- Regenerate ---
    if st.session_state.body:
        with st.expander("🔁 Regenerate with feedback"):
            cols = st.columns(len(QUICK_FEEDBACK))
            quick_pick = None
            for i, label in enumerate(QUICK_FEEDBACK):
                if cols[i].button(label, key=f"quick_{i}"):
                    quick_pick = label
            custom_feedback = st.text_input("Or describe changes")

            feedback = quick_pick or custom_feedback
            if st.button("Regenerate", disabled=not feedback):
                with st.spinner("Revising..."):
                    try:
                        result = ai.generate_message(
                            platform=platform, sender_name=sender_name,
                            purpose=result.get("cta_used", "") if result else "",
                            tone=TONES[0],
                            regenerate_feedback=feedback,
                            previous_draft=st.session_state.body,
                        )
                        st.session_state.result = result
                        st.session_state.body = result["message"]
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed: {e}")

    st.divider()

    # --- Pre-send review ---
    if st.button("🔍 Review before send"):
        st.session_state.review = checks.run_full_review(
            st.session_state.subject, st.session_state.body, sender_name, platform
        )

    if st.session_state.review:
        rev = st.session_state.review
        c1, c2, c3 = st.columns(3)
        c1.metric("Words", rev["word_count"])
        c2.metric("Characters", rev["char_count"])
        c3.metric("Read time", f"{rev['reading_time_seconds']}s")

    st.divider()

    # --- Send/Schedule ---
    col_send, col_schedule = st.columns(2)
    with col_send:
        if multi_mode:
            valid_multi = [e for e in st.session_state.multi_emails if mailer.is_valid_email(e)]
            send_label = f"📤 Send to {len(valid_multi)} recipient{'s' if len(valid_multi) != 1 else ''}"
        else:
            send_label = "📤 Send"
        send_clicked = st.button(send_label, type="primary", use_container_width=True)
    with col_schedule:
        if st.button("📅 Schedule", use_container_width=True, disabled=multi_mode,
                     help="Schedule is for single-recipient sends only." if multi_mode else ""):
            st.session_state.show_schedule_panel = not st.session_state.show_schedule_panel

    if st.session_state.show_schedule_panel:
        with st.container(border=True):
            st.markdown("**📅 Schedule send**")
            schedule_date = st.date_input("Date", value=datetime.now() + timedelta(days=1), key="sched_date")
            sched_time_str = st.text_input(
                "Time (e.g. 9:30 PM · 14:00 · 9AM)",
                value="9:00 PM",
                key="sched_time_str",
                placeholder="9:30 PM",
            )
            col_save, col_cancel = st.columns(2)
            with col_save:
                if st.button("💾 Save", type="primary", use_container_width=True):
                    from datetime import time as dtime
                    import re as _re
                    def _parse_time(s):
                        s = s.strip().upper()
                        m = _re.match(r'^(\d{1,2}):(\d{2})\s*(AM|PM)?$', s) or \
                            _re.match(r'^(\d{1,2})\s*(AM|PM)$', s)
                        if not m: return None
                        groups = m.groups()
                        if len(groups) == 3:  # HH:MM [AM/PM]
                            h, mi, period = int(groups[0]), int(groups[1]), groups[2]
                        else:                  # HH AM/PM
                            h, mi, period = int(groups[0]), 0, groups[1]
                        if period == 'PM' and h != 12: h += 12
                        if period == 'AM' and h == 12: h = 0
                        try: return dtime(h, mi)
                        except ValueError: return None
                    parsed = _parse_time(sched_time_str)
                    if parsed is None:
                        st.error("⚠️ Use a format like \"9:30 PM\", \"14:00\", or \"9AM\".")
                    elif not mailer.is_valid_email(recipient_email):
                        st.error("Invalid email.")
                    else:
                        scheduled_dt = datetime.combine(schedule_date, parsed).isoformat()
                        db.add_scheduled_send(
                            recipient_email=recipient_email,
                            recipient_name=st.session_state.recipient_name_input,
                            subject=st.session_state.subject,
                            body=st.session_state.body,
                            platform=platform,
                            scheduled_time=scheduled_dt,
                        )
                        st.session_state.show_schedule_panel = False
                        st.success(f"✅ Scheduled for {schedule_date} at {sched_time_str}")
            with col_cancel:
                if st.button("✖ Cancel", use_container_width=True):
                    st.session_state.show_schedule_panel = False
                    st.rerun()

    # --- Send logic ---
    if send_clicked:
        if not st.session_state.subject.strip() and platform == "Email":
            st.error("Subject required.")
        elif not st.session_state.body.strip():
            st.error("Message required.")
        elif not sender_email_input or not app_password_input:
            st.error("Fill in sender details in the sidebar.")
        elif multi_mode:
            valid_targets = [e for e in st.session_state.multi_emails if mailer.is_valid_email(e)]
            if not valid_targets:
                st.error("No valid emails in the list.")
            else:
                attachment_paths = []
                if st.session_state.attachment_files:
                    temp_dir = os.path.join(os.path.dirname(__file__), "_attachments_tmp")
                    os.makedirs(temp_dir, exist_ok=True)
                    for f in st.session_state.attachment_files:
                        temp_path = os.path.join(temp_dir, f.name)
                        with open(temp_path, "wb") as fp:
                            fp.write(f.read())
                        attachment_paths.append(temp_path)
                full_body = st.session_state.body
                if st.session_state.signature:
                    full_body += "\n\n--\n" + st.session_state.signature
                multi_progress = st.progress(0)
                multi_results = []
                for i, addr in enumerate(valid_targets):
                    ok, msg = mailer.send_email(
                        addr, st.session_state.subject, full_body,
                        sender_email_input, app_password_input,
                        is_html=st.session_state.is_html_mode,
                        attachments=attachment_paths if attachment_paths else None,
                    )
                    multi_results.append((addr, ok, msg))
                    db.add_history(
                        recipient_email=addr, recipient_name="",
                        platform=platform, subject=st.session_state.subject,
                        body=full_body,
                        purpose=(result.get("cta_used", "") if result else ""),
                        tone="", status="sent" if ok else "failed",
                        error_message=None if ok else msg,
                    )
                    multi_progress.progress((i + 1) / len(valid_targets))
                    if i < len(valid_targets) - 1:
                        time.sleep(2)
                sent_count = sum(1 for _, ok, _ in multi_results if ok)
                st.success(f"✅ Sent to {sent_count}/{len(valid_targets)} recipients.")
                for addr, err in [(a, m) for a, ok, m in multi_results if not ok]:
                    st.error(f"❌ {addr}: {err}")
        elif not mailer.is_valid_email(recipient_email):
            st.error("Invalid recipient email.")
        else:
            attachment_paths = []
            if st.session_state.attachment_files:
                temp_dir = os.path.join(os.path.dirname(__file__), "_attachments_tmp")
                os.makedirs(temp_dir, exist_ok=True)
                for f in st.session_state.attachment_files:
                    temp_path = os.path.join(temp_dir, f.name)
                    with open(temp_path, "wb") as fp:
                        fp.write(f.read())
                    attachment_paths.append(temp_path)
            full_body = st.session_state.body
            if st.session_state.signature:
                full_body += "\n\n--\n" + st.session_state.signature
            with st.spinner("Sending..."):
                ok, msg = mailer.send_email(
                    recipient_email, st.session_state.subject, full_body,
                    sender_email_input, app_password_input,
                    is_html=st.session_state.is_html_mode,
                    attachments=attachment_paths if attachment_paths else None,
                )
            st.session_state.sent_status = (ok, msg)
            db.add_history(
                recipient_email=recipient_email,
                recipient_name=st.session_state.recipient_name_input,
                platform=platform, subject=st.session_state.subject,
                body=full_body,
                purpose=(result.get("cta_used", "") if result else ""),
                tone="", status="sent" if ok else "failed",
                error_message=None if ok else msg,
            )

        if st.session_state.sent_status and not multi_mode:
            ok, msg = st.session_state.sent_status
            (st.success if ok else st.error)(msg)


# =========================================================
# CSV CAMPAIGN TAB
# =========================================================
with tab_bulk:
    st.subheader("📎 CSV Campaign — Personalized Emails at Scale")
    st.caption("Upload a CSV → AI writes a unique email for each person → review → send or schedule.")

    # --- Step 1: CSV Upload ---
    st.markdown("### Step 1 — Upload your CSV")
    st.caption("Required column: `email` | Optional: `name`, `context`, `summary`")

    bulk_csv_file = st.file_uploader(
        "Choose CSV file", type=["csv"], key="bulk_csv_upload",
    )

    if bulk_csv_file:
        try:
            content = bulk_csv_file.getvalue()
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = content.decode("latin-1")

            stream = io.StringIO(text)
            reader = csv.DictReader(stream)
            rows = list(reader)
            if not rows:
                st.warning("CSV appears empty — check the file.")
            else:
                rows = [{k.strip().lower(): v.strip() for k, v in row.items()} for row in rows]
                if "email" not in rows[0]:
                    st.error("CSV must have an `email` column.")
                else:
                    valid_rows = [r for r in rows if r.get("email") and mailer.is_valid_email(r["email"])]
                    invalid_rows = [r for r in rows if not (r.get("email") and mailer.is_valid_email(r.get("email", "")))]
                    st.session_state.bulk_csv_rows = valid_rows

                    col_v, col_i = st.columns(2)
                    col_v.metric("✅ Valid recipients", len(valid_rows))
                    if invalid_rows:
                        col_i.metric("⚠️ Skipped (bad email)", len(invalid_rows))

                    if valid_rows:
                        st.markdown("**Preview of recipients:**")
                        st.dataframe(
                            [{"Name": r.get("name", "—"), "Email": r["email"],
                              "Context": r.get("context", "")[:60],
                              "Summary": r.get("summary", "")[:80]} for r in valid_rows],
                            use_container_width=True,
                            hide_index=True,
                        )
        except Exception as e:
            st.error(f"Error reading CSV: {e}")

    # --- Step 2: Campaign settings (only if rows loaded) ---
    if st.session_state.bulk_csv_rows:
        st.divider()
        st.markdown("### Step 2 — Campaign settings")
        st.caption("Describe the campaign once — the AI adapts it for every person individually.")

        col_a, col_b = st.columns(2)
        with col_a:
            bulk_preset = st.selectbox("Preset type", PRESETS, key="bulk_preset")
            bulk_tone = st.selectbox("Tone", TONES, key="bulk_tone")
        with col_b:
            bulk_voice_profiles = db.list_voice_profiles()
            bulk_voice_options = ["None"] + [v["name"] for v in bulk_voice_profiles]
            bulk_voice_choice = st.selectbox("Voice profile", bulk_voice_options, key="bulk_voice")
            bulk_voice_sample = ""
            if bulk_voice_choice != "None":
                bulk_voice_sample = next(v["sample_text"] for v in bulk_voice_profiles if v["name"] == bulk_voice_choice)

        bulk_purpose = st.text_area(
            "What is this outreach for? (applies to everyone)",
            height=80, key="bulk_purpose_input",
            placeholder="e.g. Applying for software internship at their company",
        )
        bulk_key_points = st.text_area(
            "Key points to include (AI adapts these per person)",
            height=70, key="bulk_key_points",
            placeholder="e.g. I saw their recent project on GitHub, I'm a Python developer, link to my portfolio",
        )

        # --- Step 3: Generate personalized previews ---
        st.divider()
        st.markdown("### Step 3 — Generate personalized drafts")

        if st.button("✨ Generate Previews", type="primary", use_container_width=True, key="bulk_generate"):
            if not bulk_purpose.strip():
                st.error("Please describe the purpose of the outreach.")
            else:
                previews = []
                progress = st.progress(0, text="Generating personalized drafts…")
                errors = []
                rows = st.session_state.bulk_csv_rows
                for i, row in enumerate(rows):
                    try:
                        result = ai.generate_message(
                            platform="Email",
                            sender_name=sender_name,
                            purpose=bulk_purpose,
                            tone=bulk_tone,
                            recipient_name=row.get("name", ""),
                            recipient_context=row.get("context", ""),
                            key_points=f"{row.get('summary', '')} {bulk_key_points}".strip(),
                            email_type_preset=bulk_preset,
                            voice_profile_sample=bulk_voice_sample,
                        )
                        previews.append({
                            "row": row,
                            "result": result,
                            "subject": result["subject_variants"][0] if result.get("subject_variants") else "",
                            "body": result["message"],
                        })
                    except Exception as e:
                        errors.append((row.get("email", "?"), str(e)))
                        previews.append({"row": row, "result": None, "subject": "", "body": ""})

                    progress.progress((i + 1) / len(rows), text=f"✍️ {i+1}/{len(rows)} drafted…")

                st.session_state.bulk_previews = previews
                st.session_state.bulk_sent = False
                if errors:
                    st.warning(f"⚠️ {len(errors)} draft(s) failed. They will be skipped on send.")
                else:
                    st.success("All drafts ready! Review below, then send.")
                st.rerun()

        # --- Show previews ---
        if st.session_state.bulk_previews:
            st.divider()
            st.markdown("### Step 4 — Review drafts")
            for i, preview in enumerate(st.session_state.bulk_previews):
                row = preview["row"]
                label = f"{'✅' if preview['result'] else '❌'} {row.get('name') or row['email']} — {row['email']}"
                with st.expander(label, expanded=False):
                    if not preview["result"]:
                        st.error("Draft failed for this recipient — will be skipped.")
                        continue
                    new_subj = st.text_input(
                        "Subject", value=preview["subject"], key=f"bulk_subj_{i}"
                    )
                    new_body = st.text_area(
                        "Message", value=preview["body"].replace("\\n", "\n"), height=220, key=f"bulk_body_{i}"
                    )
                    # Write back edits
                    st.session_state.bulk_previews[i]["subject"] = new_subj
                    st.session_state.bulk_previews[i]["body"] = new_body
                    if preview["result"].get("rationale"):
                        st.caption(f"💡 {preview['result']['rationale']}")

            # --- Step 4: Attachments + Signature + Send / Schedule ---
            st.divider()
            ready = [p for p in st.session_state.bulk_previews if p["result"]]
            st.markdown(f"### Step 4 — Attachments, Signature & Send")

            # Attachments for the whole campaign
            bulk_uploads = st.file_uploader(
                "📎 Attach files to every email (PDF, DOCX, images…)",
                accept_multiple_files=True, key="bulk_attachments",
                help="Same file(s) sent to every recipient — e.g. your resume or portfolio.",
            )
            st.session_state.bulk_attachment_files = bulk_uploads if bulk_uploads else []

            # E-signature for the campaign
            with st.expander("✍️ E-Signature (appended to every email in this campaign)"):
                bulk_sig = st.text_area(
                    "Campaign signature",
                    value=st.session_state.bulk_signature,
                    height=100,
                    placeholder="Best regards,\nYour Name\nPhone | LinkedIn | Portfolio URL",
                    key="bulk_signature_input",
                )
                st.session_state.bulk_signature = bulk_sig
                if bulk_sig:
                    st.caption("Preview:")
                    st.code(bulk_sig, language=None)

            st.markdown(f"**{len(ready)} personalised emails ready to send**")

            if not sender_email_input or not app_password_input:
                st.warning("⚠️ Add your Gmail address and app password in the sidebar first.")
            elif not st.session_state.bulk_sent:
                col_bulk_send, col_bulk_sched = st.columns(2)

                with col_bulk_send:
                    if st.button(f"📤 Send all {len(ready)} now", type="primary", use_container_width=True):
                        # Prepare shared attachments
                        bulk_attach_paths = []
                        if st.session_state.bulk_attachment_files:
                            temp_dir = os.path.join(os.path.dirname(__file__), "_attachments_tmp")
                            os.makedirs(temp_dir, exist_ok=True)
                            for f in st.session_state.bulk_attachment_files:
                                temp_path = os.path.join(temp_dir, f.name)
                                with open(temp_path, "wb") as fp:
                                    fp.write(f.read())
                                bulk_attach_paths.append(temp_path)

                        send_progress = st.progress(0, text="Sending…")
                        send_results = []
                        for i, preview in enumerate(ready):
                            row = preview["row"]
                            idx = st.session_state.bulk_previews.index(preview)
                            subject = st.session_state.get(f"bulk_subj_{idx}", preview["subject"])
                            body = st.session_state.get(f"bulk_body_{idx}", preview["body"])
                            if st.session_state.bulk_signature:
                                body += "\n\n--\n" + st.session_state.bulk_signature
                            ok, msg_out = mailer.send_email(
                                row["email"], subject, body,
                                sender_email_input, app_password_input,
                                is_html=False,
                                attachments=bulk_attach_paths if bulk_attach_paths else None,
                            )
                            send_results.append((row["email"], ok, msg_out))
                            db.add_history(
                                recipient_email=row["email"],
                                recipient_name=row.get("name", ""),
                                platform="Email", subject=subject, body=body,
                                purpose=bulk_purpose, tone=bulk_tone,
                                status="sent" if ok else "failed",
                                error_message=None if ok else msg_out,
                            )
                            send_progress.progress((i + 1) / len(ready), text=f"📤 {i+1}/{len(ready)} sent…")
                            if i < len(ready) - 1:
                                time.sleep(2)

                        sent_count = sum(1 for _, ok, _ in send_results if ok)
                        failed = [(e, m) for e, ok, m in send_results if not ok]
                        st.session_state.bulk_sent = True
                        st.success(f"✅ Sent {sent_count}/{len(ready)} emails!")
                        for addr, err in failed:
                            st.error(f"❌ {addr}: {err}")

                with col_bulk_sched:
                    if st.button("📅 Schedule campaign", use_container_width=True):
                        st.session_state.bulk_show_schedule = not st.session_state.bulk_show_schedule

                if st.session_state.get("bulk_show_schedule"):
                    with st.container(border=True):
                        st.markdown("**📅 Schedule — all emails will be queued for this time**")
                        b_sched_date = st.date_input("Date", value=datetime.now() + timedelta(days=1), key="bulk_sched_date")
                        b_sched_time_str = st.text_input(
                            "Time (e.g. 9:30 PM · 14:00 · 9AM)",
                            value="9:00 PM",
                            key="b_sched_time_str",
                            placeholder="9:30 PM",
                        )
                        col_bs, col_bc = st.columns(2)
                        with col_bs:
                            if st.button("💾 Save schedule", type="primary", use_container_width=True):
                                from datetime import time as dtime
                                import re as _re
                                def _parse_time_b(s):
                                    s = s.strip().upper()
                                    m = _re.match(r'^(\d{1,2}):(\d{2})\s*(AM|PM)?$', s) or \
                                        _re.match(r'^(\d{1,2})\s*(AM|PM)$', s)
                                    if not m: return None
                                    groups = m.groups()
                                    if len(groups) == 3:
                                        h, mi, period = int(groups[0]), int(groups[1]), groups[2]
                                    else:
                                        h, mi, period = int(groups[0]), 0, groups[1]
                                    if period == 'PM' and h != 12: h += 12
                                    if period == 'AM' and h == 12: h = 0
                                    try: return dtime(h, mi)
                                    except ValueError: return None
                                b_parsed = _parse_time_b(b_sched_time_str)
                                if b_parsed is None:
                                    st.error("⚠️ Use a format like \"9:30 PM\", \"14:00\", or \"9AM\".")
                                else:
                                    scheduled_dt = datetime.combine(b_sched_date, b_parsed).isoformat()
                                    for preview in ready:
                                        row = preview["row"]
                                        idx = st.session_state.bulk_previews.index(preview)
                                        subject = st.session_state.get(f"bulk_subj_{idx}", preview["subject"])
                                        body = st.session_state.get(f"bulk_body_{idx}", preview["body"])
                                        if st.session_state.bulk_signature:
                                            body += "\n\n--\n" + st.session_state.bulk_signature
                                        db.add_scheduled_send(
                                            recipient_email=row["email"],
                                            recipient_name=row.get("name", ""),
                                            subject=subject, body=body,
                                            platform="Email",
                                            scheduled_time=scheduled_dt,
                                        )
                                    st.session_state.bulk_show_schedule = False
                                    st.session_state.bulk_sent = True
                                    st.success(f"✅ Scheduled {len(ready)} emails for {b_sched_date} at {b_sched_time_str}!")
                        with col_bc:
                            if st.button("✖ Cancel", use_container_width=True, key="bulk_sched_cancel"):
                                st.session_state.bulk_show_schedule = False
                                st.rerun()
            else:
                st.success("✅ Campaign done! Upload a new CSV to start another.")
                if st.button("🔄 Start a new campaign"):
                    st.session_state.bulk_csv_rows = []
                    st.session_state.bulk_previews = []
                    st.session_state.bulk_sent = False
                    st.session_state.bulk_show_schedule = False
                    st.rerun()


# =========================================================
# CONTACTS TAB
# =========================================================
with tab_contacts:
    st.subheader("Contacts")

    contact_tab1, contact_tab2 = st.tabs(["Add manually", "Import CSV"])

    with contact_tab1:
        with st.form("add_contact_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input("Name")
            email = c2.text_input("Email")
            context = st.text_input("Context")
            summary = st.text_area("Summary/bio (LinkedIn, notes)", height=80)
            if st.form_submit_button("Add"):
                db.add_contact(name, email, context, summary, "")
                st.rerun()

    with contact_tab2:
        st.caption("CSV columns: name, email, context, summary, notes (optional)")
        csv_file = st.file_uploader("CSV file", type=["csv"], key="csv_upload")
        if csv_file:
            try:
                content = csv_file.getvalue()
                # Try UTF-8, fall back to latin-1 for files with special characters
                try:
                    text = content.decode("utf-8")
                except UnicodeDecodeError:
                    text = content.decode("latin-1")
                stream = io.StringIO(text)
                reader = csv.DictReader(stream)
                rows = list(reader)
                if not rows:
                    st.warning("CSV appears to be empty or has no data rows.")
                else:
                    # Normalize column names (strip whitespace, lowercase)
                    rows = [{k.strip().lower(): v for k, v in row.items()} for row in rows]
                    cols = list(rows[0].keys())
                    st.write(f"Found **{len(rows)} rows** with columns: `{', '.join(cols)}`")
                    if "email" not in cols:
                        st.error("CSV must have an 'email' column.")
                    else:
                        if st.button("⬆️ Import", type="primary"):
                            imported = 0
                            for row in rows:
                                if row.get("email", "").strip():
                                    db.add_contact(
                                        name=row.get("name", "").strip(),
                                        email=row.get("email", "").strip(),
                                        context=row.get("context", "").strip(),
                                        summary=row.get("summary", "").strip(),
                                        notes=row.get("notes", "").strip(),
                                    )
                                    imported += 1
                            st.session_state.csv_import_count = imported
                            st.rerun()
            except Exception as e:
                st.error(f"Error reading CSV: {e}")

        if st.session_state.csv_import_count is not None:
            st.success(f"✅ Imported {st.session_state.csv_import_count} contacts!")
            st.session_state.csv_import_count = None

    st.divider()
    for c in db.list_contacts():
        with st.container(border=True):
            st.write(f"**{c['name']}** — {c['email']}")
            if c["summary"]:
                st.caption(c["summary"][:100])
            if st.button("Delete", key=f"del_contact_{c['id']}"):
                db.delete_contact(c["id"])
                st.rerun()


# =========================================================
# TEMPLATES TAB
# =========================================================
with tab_templates:
    st.subheader("Templates")
    with st.form("add_template_form", clear_on_submit=True):
        t_name = st.text_input("Template name")
        t_platform = st.selectbox("Platform", PLATFORMS, key="template_platform")
        t_body = st.text_area("Template body", height=150)
        if st.form_submit_button("Save"):
            db.add_template(t_name, t_platform, t_body)
            st.rerun()

    for t in db.list_templates():
        with st.container(border=True):
            st.write(f"**{t['name']}** — {t['platform']}")
            st.code(t["body_template"], language=None)
            if st.button("Delete", key=f"del_template_{t['id']}"):
                db.delete_template(t["id"])
                st.rerun()


# =========================================================
# VOICE PROFILES TAB
# =========================================================
with tab_voices:
    st.subheader("Voice Profiles")
    with st.form("add_voice_form", clear_on_submit=True):
        v_name = st.text_input("Profile name")
        v_sample = st.text_area("Sample writing", height=150)
        if st.form_submit_button("Save"):
            db.add_voice_profile(v_name, v_sample)
            st.rerun()

    for v in db.list_voice_profiles():
        with st.container(border=True):
            st.write(f"**{v['name']}**")
            st.caption(v["sample_text"][:200])
            if st.button("Delete", key=f"del_voice_{v['id']}"):
                db.delete_voice_profile(v["id"])
                st.rerun()


# =========================================================
# HISTORY TAB
# =========================================================
with tab_history:
    st.subheader("Analytics")
    s = db.stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sent", s["total_sent"])
    c2.metric("Failed", s["total_failed"])
    c3.metric("Top tone", s["top_tone"])
    c4.metric("Top recipient", s["top_recipient"])

    st.subheader("Recent sends")
    rows = db.list_history()
    if rows:
        st.dataframe(
            [{
                "Date": r["created_at"][:19],
                "To": r["recipient_email"],
                "Platform": r["platform"],
                "Subject": r["subject"][:40],
                "Status": r["status"],
            } for r in rows],
            use_container_width=True,
        )
    else:
        st.caption("No sends yet.")


# =========================================================
# SCHEDULED TAB
# =========================================================
with tab_scheduled:
    st.subheader("Scheduled sends")
    scheduled = db.list_scheduled_sends()
    if scheduled:
        for send in scheduled:
            with st.container(border=True):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"**To:** {send['recipient_email']}")
                    st.caption(f"When: {send['scheduled_time'][:19]}")
                with col2:
                    if st.button("Delete", key=f"del_scheduled_{send['id']}"):
                        db.delete_scheduled_send(send["id"])
                        st.rerun()
    else:
        st.caption("No scheduled sends.")

    st.info("💡 Actual send automation needs Phase 2 (backend worker).")