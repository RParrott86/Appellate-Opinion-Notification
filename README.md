# Appellate Opinion Notification

Automatically scrapes configured websites daily for trigger words and sends email alerts when matches are found.

## How It Works

1. At 9:15 AM ET every day, a GitHub Actions workflow runs the scraper.
2. The scraper visits each configured website and searches the page text for trigger words (case-insensitive).
3. If any trigger words are found, an HTML email is sent to all configured recipients via Gmail.
4. If no triggers are found, no email is sent.

## Setup

### 1. Gmail App Password

Google requires an **App Password** for programmatic SMTP access:

1. Go to [Google Account Security](https://myaccount.google.com/security).
2. Enable **2-Step Verification** if not already enabled.
3. Go to [App Passwords](https://myaccount.google.com/apppasswords).
4. Generate a new App Password (select "Mail" and "Windows Computer" or "Other").
5. Copy the 16-character password — this is your `PERSONAL_EMAIL_PASSWORD`.

### 2. GitHub Secrets & Variables

In your repository, go to **Settings > Secrets and variables > Actions**.

**Secrets** (encrypted, for sensitive data):

| Name | Value |
|------|-------|
| `PERSONAL_EMAIL` | Your Gmail address |
| `PERSONAL_EMAIL_PASSWORD` | The App Password from step 1 |

**Variables** (plain text, for configuration):

| Name | Value | Format |
|------|-------|--------|
| `WEBSITES_TO_SCRAPE` | URLs to scrape | Comma-separated (e.g. `https://site1.com,https://site2.com`) |
| `TRIGGER_WORD` | Words to search for | Comma-separated (e.g. `opinion,ruling,decision`) |
| `RECIPIENT_LIST` | Email recipients | Comma-separated (e.g. `user1@example.com,user2@example.com`) |

### 3. Schedule

The workflow runs daily at **9:15 AM US Eastern Time** (14:15 UTC during EST). During daylight saving time (EDT, March–November), it will fire at 10:15 AM local time. Adjust the cron expression in `.github/workflows/scrape-and-notify.yml` if needed.

## Running Manually

### From GitHub

Go to the **Actions** tab in the repository, select the "Appellate Opinion Scraper" workflow, and click **Run workflow**.

### From Your Computer

```bash
# 1. Clone the repository
git clone https://github.com/RParrott86/Appellate-Opinion-Notification.git
cd Appellate-Opinion-Notification

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create a .env file (see .env.example)
cp .env.example .env
# Edit .env with your actual values

# 4. Run the scraper
python scraper.py

# 5. Or do a dry run (scrapes but doesn't send email)
python scraper.py --dry-run
```

## Project Structure

```
├── .github/workflows/
│   └── scrape-and-notify.yml   # GitHub Actions scheduled workflow
├── .env.example                # Template for local environment variables
├── .gitignore
├── requirements.txt            # Python dependencies
├── scraper.py                  # Main scraper and notification script
└── README.md
```
