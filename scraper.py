#!/usr/bin/env python3
"""
Appellate Opinion Notification Tool

Scrapes configured websites for trigger words using a headless browser
(Playwright) to handle JavaScript-rendered content, and sends email
notifications to a list of recipients when matches are found.
"""

import os
import re
import sys
import ssl
import smtplib
import logging
import argparse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

GMAIL_SMTP_SERVER = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587
PAGE_LOAD_TIMEOUT = 60_000  # ms — generous for slow court sites
NETWORK_IDLE_TIMEOUT = 15_000  # ms — wait for AJAX to finish


def get_config():
    """Load configuration from environment variables."""
    email = os.environ.get("PERSONAL_EMAIL", "").strip()
    password = os.environ.get("PERSONAL_EMAIL_PASSWORD", "").strip()
    websites_raw = os.environ.get("WEBSITES_TO_SCRAPE", "").strip()
    triggers_raw = os.environ.get("TRIGGER_WORD", "").strip()
    recipients_raw = os.environ.get("RECIPIENT_LIST", "").strip()

    if not all([email, password, websites_raw, triggers_raw, recipients_raw]):
        missing = []
        if not email:
            missing.append("PERSONAL_EMAIL")
        if not password:
            missing.append("PERSONAL_EMAIL_PASSWORD")
        if not websites_raw:
            missing.append("WEBSITES_TO_SCRAPE")
        if not triggers_raw:
            missing.append("TRIGGER_WORD")
        if not recipients_raw:
            missing.append("RECIPIENT_LIST")
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)

    websites = [v.strip() for v in re.split(r"[,\n]+", websites_raw) if v.strip()]
    trigger_words = [v.strip() for v in re.split(r"[,\n]+", triggers_raw) if v.strip()]
    recipients = [v.strip() for v in re.split(r"[,\n]+", recipients_raw) if v.strip()]

    return {
        "email": email,
        "password": password,
        "websites": websites,
        "trigger_words": trigger_words,
        "recipients": recipients,
    }


def scrape_website(page, url):
    """Navigate to a URL in the headless browser and return visible text."""
    logger.info("Scraping: %s", url)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        try:
            page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT)
        except PlaywrightTimeout:
            logger.warning("Network-idle timeout on %s — proceeding with current content", url)

        text = page.inner_text("body")
        logger.info("Extracted %d characters from %s", len(text), url)
        return text
    except Exception as e:
        logger.error("Failed to scrape %s: %s", url, e)
        return None


def search_for_triggers(text, trigger_words):
    """Search text for trigger words (case-insensitive). Returns list of found words."""
    if not text:
        return []
    text_lower = text.lower()
    return [word for word in trigger_words if word.lower() in text_lower]


def build_email_body(results):
    """Build an HTML email body summarizing all matches found."""
    timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    html_parts = [
        "<html><body>",
        "<h2>Appellate Opinion Notification</h2>",
        f"<p>The following trigger words were detected during the scan on <strong>{timestamp}</strong>:</p>",
    ]

    for url, matched_words in results.items():
        domain = urlparse(url).netloc or url
        html_parts.append(f'<h3><a href="{url}">{domain}</a></h3>')
        html_parts.append("<ul>")
        for word in matched_words:
            html_parts.append(f"<li><strong>{word}</strong></li>")
        html_parts.append("</ul>")

    html_parts.extend([
        "<hr>",
        "<p style='color: #666; font-size: 12px;'>This is an automated notification from the Appellate Opinion Notification tool.</p>",
        "</body></html>",
    ])

    return "\n".join(html_parts)


def send_email(sender_email, sender_password, recipients, subject, html_body):
    """Send an HTML email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["From"] = sender_email
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    logger.info("Connecting to Gmail SMTP server...")
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(GMAIL_SMTP_SERVER, GMAIL_SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, recipients, msg.as_string())
        logger.info("Email sent successfully to: %s", ", ".join(recipients))
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail authentication failed. Make sure you are using an App Password. "
            "See: https://support.google.com/accounts/answer/185833"
        )
        raise
    except smtplib.SMTPException as e:
        logger.error("SMTP error: %s", e)
        raise


def run():
    """Main execution: scrape websites, check for triggers, send notifications."""
    config = get_config()
    logger.info(
        "Starting scan — %d website(s), %d trigger word(s), %d recipient(s)",
        len(config["websites"]),
        len(config["trigger_words"]),
        len(config["recipients"]),
    )

    all_matches = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        for url in config["websites"]:
            text = scrape_website(page, url)
            if text is None:
                continue
            matched = search_for_triggers(text, config["trigger_words"])
            if matched:
                logger.info("MATCH on %s — trigger(s): %s", url, ", ".join(matched))
                all_matches[url] = matched
            else:
                logger.info("No triggers found on %s", url)

        browser.close()

    if all_matches:
        total = sum(len(v) for v in all_matches.values())
        subject = f"Appellate Opinion Alert — {total} trigger(s) found on {len(all_matches)} site(s)"
        html_body = build_email_body(all_matches)
        send_email(
            config["email"],
            config["password"],
            config["recipients"],
            subject,
            html_body,
        )
        logger.info("Done — notifications sent.")
    else:
        logger.info("Done — no trigger words found on any website. No email sent.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape websites for trigger words and send email notifications."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and search but do not send email.",
    )
    args = parser.parse_args()

    if args.dry_run:
        logger.info("=== DRY RUN MODE — no emails will be sent ===")
        original_send = send_email
        send_email = lambda *a, **kw: logger.info("(dry-run) Email would be sent here.")

    run()
