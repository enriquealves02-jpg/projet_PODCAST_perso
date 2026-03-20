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
    subject = f"Journal personnalisé d'Enrique - {today}"

    # Detect GitHub Pages URL from GITHUB_REPOSITORY env var
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo:
        owner = repo.split("/")[0]
        repo_name = repo.split("/")[1]
        pages_url = f"https://{owner}.github.io/{repo_name}/"
    else:
        pages_url = ""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Journal d'Enrique <{email_user}>"
    msg["To"] = email_to

    text_fallback = (
        f"Journal personnalisé d'Enrique - {today}\n\n"
        f"Lire ton digest : {pages_url}\n"
    )

    email_html = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#0d1117;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
<div style="max-width:500px;margin:40px auto;text-align:center;padding:40px 24px;">
    <h1 style="color:#f0f6fc;font-size:24px;margin-bottom:8px;">Journal personnalisé d'Enrique</h1>
    <p style="color:#8b949e;font-size:14px;margin-bottom:32px;">{today}</p>
    <a href="{pages_url}" style="display:inline-block;padding:14px 32px;background:#1f6feb;color:#ffffff;text-decoration:none;border-radius:8px;font-size:16px;font-weight:600;">Lire mon digest</a>
    <p style="color:#484f58;font-size:12px;margin-top:24px;">Clique pour ouvrir dans ton navigateur</p>
</div>
</body>
</html>"""

    msg.attach(MIMEText(text_fallback, "plain", "utf-8"))
    msg.attach(MIMEText(email_html, "html", "utf-8"))

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
