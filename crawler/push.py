"""
Push notification via Firebase Cloud Messaging (free, unlimited).
Sends ONE message per topic: "all" plus one per region (r_africa, r_europe, ...).
The app subscribes each user to exactly one topic, so each crawl sends at most one push per user.
Runs after every crawl; only items first seen since the previous crawl (last 13 h) are counted.
Needs env FIREBASE_SERVICE_ACCOUNT = contents of the Firebase service-account JSON.
"""
import os, json, logging, re
from datetime import datetime, timezone, timedelta

log = logging.getLogger("push")
REGIONS = ["Africa", "Europe", "North America", "Asia", "Middle East", "Oceania", "Latin America"]
topic_of = lambda r: "r_" + re.sub(r"[^a-z]+", "_", r.lower())


def _token(sa):
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    creds = service_account.Credentials.from_service_account_info(sa, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
    creds.refresh(Request()); return creds.token


def _send(project, token, topic, title, body, data):
    import requests
    msg = {"message": {"topic": topic,
                       "notification": {"title": title, "body": body},
                       "data": {k: str(v) for k, v in data.items()},
                       "android": {"priority": "normal", "ttl": "43200s", "collapse_key": "daily",
                                   "notification": {"channel_id": "scholarhub_daily", "tag": "daily"}}}}
    r = requests.post(f"https://fcm.googleapis.com/v1/projects/{project}/messages:send",
                      headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, json=msg, timeout=20)
    if r.status_code != 200: log.warning("FCM %s -> %s %s", topic, r.status_code, r.text[:200])
    return r.status_code == 200


def send_daily(SB):
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
    if not raw: log.info("push: no FIREBASE_SERVICE_ACCOUNT, skipping"); return 0
    now = datetime.now(timezone.utc)
    sa = json.loads(raw); project = sa["project_id"]
    cutoff = (now - timedelta(hours=13)).isoformat()
    rows = SB.table("scholarships").select("title,regions,funding,deadline").gte("first_seen", cutoff)\
             .or_(f"deadline.is.null,deadline.gte.{now.date().isoformat()}").limit(2000).execute().data or []
    if not rows: log.info("push: nothing new since last crawl"); return 0
    tok = _token(sa); sent = 0

    def compose(items, where):
        n = len(items); ff = sum(1 for i in items if (i.get("funding") or "").startswith("fully"))
        title = f"🎓 {n} new scholarship{'s' if n != 1 else ''} just added" + (f" · {where}" if where else "")
        ex = next((i["title"] for i in items if (i.get("funding") or "").startswith("fully")), items[0]["title"])
        body = (f"{ff} fully funded. " if ff else "") + "e.g. " + ex[:70] + (" …" if len(ex) > 70 else "") + " — tap to see what's open."
        return title, body

    t, b = compose(rows, ""); sent += _send(project, tok, "all", t, b, {"newOnly": 1})
    for r in REGIONS:
        items = [i for i in rows if r in (i.get("regions") or "")]
        if items:
            t, b = compose(items, r); sent += _send(project, tok, topic_of(r), t, b, {"newOnly": 1, "region": r})
    log.info("push: sent %d topic messages (%d new items)", sent, len(rows)); return sent
