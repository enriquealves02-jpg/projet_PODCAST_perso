"""
Email Sender - Envoie le digest HTML par email via SMTP.
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def send_email(html_content: str) -> bool:
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    email_user = os.environ.get("EMAIL_USER")
    email_password = os.environ.get("EMAIL_PASSWORD")
    email_to = os.environ.get("EMAIL_TO")

    if not all([email_user, email_password, email_to]):
        raise ValueError(
            "Missing email config. Set EMAIL_USER, EMAIL_PASSWORD, EMAIL_TO environment variables."
        )

    today = datetime.now().strftime("%d/%m/%Y")
    subject = f"Daily Digest - {today}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Daily Digest <{email_user}>"
    msg["To"] = email_to

    text_fallback = (
        f"Daily Digest du {today}\n\n"
        "Votre client mail ne supporte pas le HTML.\n"
        "Ouvrez ce mail dans un client compatible pour voir le digest."
    )
    msg.attach(MIMEText(text_fallback, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(email_user, email_password)
            server.sendmail(email_user, email_to.split(","), msg.as_string())

        logger.info(f"Email sent successfully to {email_to}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        raise


def run(html_content: str) -> bool:
    return send_email(html_content)


if __name__ == "__main__":
    test_html = "<html><body><h1>Test Digest</h1><p>Ceci est un test.</p></body></html>"
    send_email(test_html)
