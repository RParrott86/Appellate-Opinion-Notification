#!/usr/bin/env python3
"""
Appellate Opinion Notification Tool

Scrapes configured websites for trigger words — including content loaded
inside iframes — and sends email notifications when matches are found.
Matching case captions are included as hyperlinks to the full opinion.
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
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup
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
REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


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


def fetch_page(url):
    """Fetch a URL and return the parsed BeautifulSoup tree."""
    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def extract_text(soup):
    """Extract visible text from a BeautifulSoup tree."""
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def extract_links(soup, base_url):
    """Extract all (caption, absolute_url) pairs from <a> tags."""
    links = []
    for a_tag in soup.find_all("a", href=True):
        caption = a_tag.get_text(strip=True)
        href = urljoin(base_url, a_tag["href"])
        if caption:
            links.append({"caption": caption, "url": href})
    return links


def scrape_website(url, depth=0):
    """
    Fetch a page, extract its text and links, and recursively follow
    iframes (up to 2 levels deep) to capture all embedded content.

    Returns a dict with 'text' (str) and 'links' (list of caption/url dicts),
    or None on failure.
    """
    if depth > 2:
        return {"text": "", "links": []}

    logger.info("Scraping: %s", url)
    try:
        soup = fetch_page(url)

        iframe_texts = []
        iframe_links = []
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src", "").strip()
            if not src:
                continue
            iframe_url = urljoin(url, src)
            logger.info("  Found iframe → %s", iframe_url)
            result = scrape_website(iframe_url, depth=depth + 1)
            if result:
                iframe_texts.append(result["text"])
                iframe_links.extend(result["links"])

        page_text = extract_text(soup)
        page_links = extract_links(soup, url)

        all_text = "\n".join([page_text] + iframe_texts)
        all_links = page_links + iframe_links

        logger.info(
            "Extracted %d characters, %d links from %s (depth=%d)",
            len(all_text), len(all_links), url, depth,
        )
        return {"text": all_text, "links": all_links}

    except requests.RequestException as e:
        logger.error("Failed to scrape %s: %s", url, e)
        return None


def search_for_triggers(text, trigger_words):
    """Search text for trigger words (case-insensitive). Returns list of found words."""
    if not text:
        return []
    text_lower = text.lower()
    return [word for word in trigger_words if word.lower() in text_lower]


def find_matching_links(links, trigger_words):
    """
    Find links whose caption contains any trigger word.
    Returns a list of dicts: {caption, url, matched_triggers}.
    """
    matching = []
    for link in links:
        caption_lower = link["caption"].lower()
        matched = [w for w in trigger_words if w.lower() in caption_lower]
        if matched:
            matching.append({
                "caption": link["caption"],
                "url": link["url"],
                "matched_triggers": matched,
            })
    return matching


def build_email_body(results):
    """
    Build an HTML email body. For each site with matches, list the
    trigger words found and the matching case captions as hyperlinks.
    """
    timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    html_parts = [
        "<html><body>",
        "<h2>Appellate Opinion Notification</h2>",
        f"<p>The following trigger words were detected during the scan on <strong>{timestamp}</strong>:</p>",
    ]

    for url, match_info in results.items():
        domain = urlparse(url).netloc or url
        html_parts.append(f'<h3><a href="{url}">{domain}</a></h3>')

        html_parts.append("<p><strong>Trigger words found:</strong> "
                          + ", ".join(match_info["trigger_words"]) + "</p>")

        if match_info["matching_links"]:
            html_parts.append("<p><strong>Matching case captions:</strong></p>")
            html_parts.append("<ul>")
            for link in match_info["matching_links"]:
                triggers_str = ", ".join(link["matched_triggers"])
                html_parts.append(
                    f'<li><a href="{link["url"]}">{link["caption"]}</a>'
                    f' &mdash; matched: <em>{triggers_str}</em></li>'
                )
            html_parts.append("</ul>")

    html_parts.extend([
        "<hr>",
        "<p style='color: #666; font-size: 12px;'>This is an automated notification "
        "from the Appellate Opinion Notification tool.</p>",
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

    for url in config["websites"]:
        result = scrape_website(url)
        if not result:
            continue

        matched_words = search_for_triggers(result["text"], config["trigger_words"])
        if matched_words:
            matching_links = find_matching_links(result["links"], config["trigger_words"])
            logger.info("MATCH on %s — trigger(s): %s", url, ", ".join(matched_words))
            for link in matching_links:
                logger.info("  Caption: %s → %s", link["caption"], link["url"])
            all_matches[url] = {
                "trigger_words": matched_words,
                "matching_links": matching_links,
            }
        else:
            logger.info("No triggers found on %s", url)

    if all_matches:
        total = sum(len(v["trigger_words"]) for v in all_matches.values())
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
