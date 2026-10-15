from __future__ import annotations

from email.message import EmailMessage
import os
import smtplib
from typing import Any


class SmtpMailer:
    @property
    def configured(self) -> bool:
        return bool(os.getenv("SMTP_HOST", "").strip() and os.getenv("SMTP_FROM", "").strip())

    def send(self, recipients: list[str], subject: str, text_body: str, html_body: str | None = None) -> dict[str, Any]:
        if not recipients:
            raise ValueError("No sentiment email recipients configured")
        if not self.configured:
            raise RuntimeError("SMTP_HOST and SMTP_FROM must be configured")
        message = EmailMessage()
        message["From"] = os.environ["SMTP_FROM"]
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        message.set_content(text_body)
        if html_body:
            message.add_alternative(html_body, subtype="html")

        host = os.environ["SMTP_HOST"]
        port = int(os.getenv("SMTP_PORT", "587"))
        username = os.getenv("SMTP_USERNAME", "").strip()
        password = os.getenv("SMTP_PASSWORD", "")
        starttls = os.getenv("SMTP_STARTTLS", "true").strip().lower() in {"1", "true", "yes", "on"}
        with smtplib.SMTP(host, port, timeout=20) as client:
            if starttls:
                client.starttls()
            if username:
                client.login(username, password)
            client.send_message(message)
        return {"status": "sent", "recipients": len(recipients)}
