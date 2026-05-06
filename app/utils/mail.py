# Path: backend/app/utils/mail.py

import smtplib
from email.message import EmailMessage

from app.core.config import settings


def send_email(to_email: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    if not settings.SMTP_HOST:
        raise RuntimeError("SMTP_HOST is not configured")

    msg = EmailMessage()
    from_label = settings.MAIL_FROM_NAME.strip() if settings.MAIL_FROM_NAME else ""
    if from_label:
        msg["From"] = f"{from_label} <{settings.MAIL_FROM}>"
    else:
        msg["From"] = settings.MAIL_FROM

    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_body)

    if html_body:
        msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.ehlo()
        if settings.SMTP_USE_TLS:
            server.starttls()
            server.ehlo()

        if settings.SMTP_USERNAME:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)

        server.send_message(msg)