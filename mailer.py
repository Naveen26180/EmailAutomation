"""
Gmail SMTP sending. Isolated so it's a one-file swap later when moving to
the Gmail API + OAuth in the full-stack version.
"""

import smtplib
import re
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(addr: str) -> bool:
    return bool(EMAIL_REGEX.match((addr or "").strip()))


def send_email(recipient_email, subject, body, sender_email, app_password, is_html=False, attachments=None):
    """
    Send email via Gmail SMTP.
    
    Args:
        recipient_email: target email
        subject: email subject
        body: email body (plain text or HTML)
        sender_email: from address
        app_password: Gmail app password
        is_html: if True, treat body as HTML
        attachments: list of file paths to attach
    """
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = recipient_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "html" if is_html else "plain"))

    # Attach files if provided
    if attachments:
        for filepath in attachments:
            if os.path.exists(filepath):
                try:
                    with open(filepath, "rb") as attachment:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(attachment.read())
                        encoders.encode_base64(part)
                        part.add_header("Content-Disposition", f"attachment; filename= {os.path.basename(filepath)}")
                        message.attach(part)
                except Exception as e:
                    return False, f"Failed to attach {filepath}: {e}"

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(sender_email, app_password)
            server.send_message(message)
        return True, "Email sent successfully!"
    except smtplib.SMTPAuthenticationError:
        return False, "Authentication failed — check your Gmail address / app password."
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"
