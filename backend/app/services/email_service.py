import os
import smtplib
from email.message import EmailMessage


def send_email(to_email: str, subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM_EMAIL", username or "no-reply@localhost")

    if not host:
        return

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(host, port) as smtp:
        smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)
