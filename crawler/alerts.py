"""Alert delivery: email (SMTP) and Telegram. Both are no-ops unless configured via env vars."""
import os, smtplib, logging, requests
from email.mime.text import MIMEText

log = logging.getLogger("notify")
SMTP_HOST = os.environ.get("SMTP_HOST"); SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER"); SMTP_PASS = os.environ.get("SMTP_PASS")
FROM = os.environ.get("SMTP_FROM", SMTP_USER or "alerts@scholarhub.local")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")


def matches(sub, item):
    text = (item["title"] + " " + item["summary"]).lower()
    if sub["keywords"] and not any(k.strip().lower() in text for k in sub["keywords"].split(",") if k.strip()):
        return False
    if sub["level"] and sub["level"].lower() not in (item["levels"] or "").lower():
        return False
    if sub["country"] and sub["country"].lower() not in (item["countries"] or "").lower():
        return False
    return True


def render(items):
    lines = ["New scholarship opportunities matching your profile:\n"]
    for it in items:
        dl = f" | Deadline: {it['deadline']}" if it.get("deadline") else ""
        lines.append(f"• {it['title']}{dl}\n  {it['url']}\n")
    return "\n".join(lines)


def send_email(to, body):
    if not SMTP_HOST:
        return "skipped (SMTP not configured)"
    msg = MIMEText(body); msg["Subject"] = "ScholarHub: new scholarships for you"; msg["From"] = FROM; msg["To"] = to
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
        s.starttls()
        if SMTP_USER: s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
    return "sent"


def send_telegram(chat_id, body):
    if not TG_TOKEN:
        return "skipped (Telegram not configured)"
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      json={"chat_id": chat_id, "text": body[:4000], "disable_web_page_preview": True}, timeout=20)
    return "sent" if r.ok else f"error {r.status_code}"


def dispatch(sb, new_items):
    """sb = supabase client. Sends each subscriber the new items matching their profile."""
    if not new_items:
        return 0
    sent = 0
    for sub in sb.table("subscribers").select("*").execute().data:
        hits = [i for i in new_items if matches(sub, i)]
        if not hits:
            continue
        body = render(hits[:15])
        try:
            status = send_email(sub["address"], body) if sub["channel"] == "email" else send_telegram(sub["address"], body)
        except Exception as e:
            status = f"error: {e}"[:200]
        sent += 1
        log.info("notify %s:%s -> %s (%d items)", sub["channel"], sub["address"], status, len(hits))
    return sent
