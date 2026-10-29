"""
notify.py — six rich notifications per day, same card for everyone, Nigeria time.

Slots (Africa/Lagos time; the GitHub schedule runs twice an hour and sends whatever slot is due):
  07:30  morning   best scholarship (new ones first)
  10:30  news      School News top story
  12:30  jobs      best new job (graduate / internship / NGO / research / remote)
  13:30  tech      Tech Updates top story
  16:30  closing   a scholarship closing within 2–7 days
  19:30  evening   best scholarship (new ones first)  — deadline reminders for saved items are local on the phone

Audience topics = the ones the app subscribes to: "all" (no region chosen) and r_<region>.
Every slot ALWAYS sends: the item is the best one not sent before (notif_log), never the same source twice
in a row, pictures first. Payload = card: title, snippet (+ deadline chip), picture / institution logo, deep link to the card.

Env: SUPABASE_URL, SUPABASE_SERVICE_KEY, FIREBASE_SERVICE_ACCOUNT.  Optional: SLOT=<name> to force a slot, TOPIC=<topic> to force one topic.
"""
import os, re, json, logging
from datetime import datetime, timezone, timedelta, date
import requests
from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("notify")
SB = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

# topic -> (display region, UTC offset hours). Offsets are "typical" – a slot lands within an hour of target time.
TOPICS = {"all": ("", 1), "r_africa": ("Africa", 1), "r_europe": ("Europe", 1), "r_north_america": ("North America", -5),
          "r_asia": ("Asia", 8), "r_middle_east": ("Middle East", 3), "r_oceania": ("Oceania", 10), "r_latin_america": ("Latin America", -3)}
SLOT_HOUR = {7: "morning", 10: "news", 12: "jobs", 13: "tech", 16: "closing", 19: "evening"}
PLAY = "https://play.google.com/store/apps/details?id=com.scholarhub.app"


def _token(sa):
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    creds = service_account.Credentials.from_service_account_info(sa, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
    creds.refresh(Request()); return creds.token


def _send(project, token, topic, slot, title, body, image, data):
    msg = {"message": {"topic": topic,
                       "notification": {"title": title[:120], "body": body[:240], **({"image": image} if image else {})},
                       "data": {k: str(v) for k, v in data.items()},
                       "android": {"priority": "high", "ttl": "10800s", "collapse_key": slot,
                                   "notification": {"channel_id": "scholarhub_daily", "tag": slot, **({"image": image} if image else {}),
                                                    "notification_count": 1, "default_sound": True}}}}
    r = requests.post(f"https://fcm.googleapis.com/v1/projects/{project}/messages:send",
                      headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, json=msg, timeout=20)
    if r.status_code != 200: log.warning("FCM %s/%s -> %s %s", topic, slot, r.status_code, r.text[:200])
    return r.status_code == 200


def _sent_ids(topic, slot=None, days=45):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    q = SB.table("notif_log").select("item_id,slot,sent_at").eq("topic", topic).gte("sent_at", since)
    rows = q.order("sent_at", desc=True).limit(2000).execute().data or []
    return {r["item_id"] for r in rows}, (rows[0] if rows else None)


def _last_source(topic):
    r = SB.table("notif_log").select("item_id,slot").eq("topic", topic).order("sent_at", desc=True).limit(1).execute().data
    if not r: return None
    for t in ("scholarships", "school_news", "tech_news", "jobs"):
        x = SB.table(t).select("source").eq("id", r[0]["item_id"]).limit(1).execute().data
        if x: return x[0]["source"]
    return None


def _snippet(s, n=150):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def _days_left(d):
    try: return (date.fromisoformat(d) - datetime.now(timezone.utc).date()).days
    except Exception: return None


def pick_scholarship(topic, region, closing=False):
    today = datetime.now(timezone.utc).date()
    sent, _ = _sent_ids(topic); avoid_src = _last_source(topic)
    base_cols = "id,title,summary,deadline,source,regions,funding,image,logo,org,first_seen"

    def q():
        qq = SB.table("scholarships").select(base_cols)
        if region: qq = qq.ilike("regions", f"*{region}*")
        return qq

    cands = []
    if closing:
        cands = q().gte("deadline", (today + timedelta(days=2)).isoformat()).lte("deadline", (today + timedelta(days=7)).isoformat()) \
                   .order("has_img", desc=True).order("deadline").limit(60).execute().data or []
    else:
        fresh = (datetime.now(timezone.utc) - timedelta(hours=26)).isoformat()
        cands = q().gte("first_seen", fresh).or_(f"deadline.is.null,deadline.gte.{today.isoformat()}") \
                   .order("has_img", desc=True).order("deadline", nullsfirst=False).limit(60).execute().data or []
        if not [c for c in cands if c["id"] not in sent]:     # nothing new -> strongest open listing not yet sent
            cands = q().or_(f"deadline.is.null,deadline.gte.{(today + timedelta(days=3)).isoformat()}") \
                       .order("has_img", desc=True).order("first_seen", desc=True).limit(120).execute().data or []
    cands = [c for c in cands if c["id"] not in sent and c.get("summary")]
    pref = [c for c in cands if c["source"] != avoid_src and (c.get("funding") or "").startswith("fully")] or \
           [c for c in cands if c["source"] != avoid_src] or cands
    if not pref: return None
    c = pref[0]; dl = _days_left(c.get("deadline") or "")
    chip = (f"⏳ Closes in {dl} days · " if dl is not None and 0 <= dl <= 14 else (f"📅 Deadline {c['deadline']} · " if c.get("deadline") else ""))
    title = ("⏰ " if closing else ("🆕 " if c.get("first_seen", "") >= (datetime.now(timezone.utc) - timedelta(hours=26)).isoformat() else "🎓 ")) + c["title"]
    return {"id": c["id"], "title": title, "body": chip + _snippet(c["summary"]), "image": c.get("image") or c.get("logo"), "data": {"s": c["id"], "slot": "closing" if closing else "scholarship"}}


def pick_news(topic, table):
    sent, _ = _sent_ids(topic); avoid_src = _last_source(topic)
    since = (datetime.now(timezone.utc) - timedelta(days=3 if table == "tech_news" else 7)).isoformat()
    cols = "id,title,summary,source,image,logo,published" + (",school,kind" if table == "school_news" else "")
    rows = SB.table(table).select(cols).gte("published", since).order("has_img", desc=True).order("published", desc=True).limit(80).execute().data or []
    rows = [r for r in rows if r["id"] not in sent and r.get("summary")]
    pref = [r for r in rows if r["source"] != avoid_src] or rows
    if not pref: return None
    r = pref[0]
    if table == "school_news":
        tag = {"admission": "🎓 Admission", "fees": "💳 Fees", "scholarship": "🏅 Scholarship", "calendar": "📅 Calendar", "convocation": "🎓 Convocation", "notice": "📣 Notice"}.get(r.get("kind") or "", "🏫 School News")
        title = f"{tag} · {r.get('school') or r['source']}"
    else:
        title = "🤖 Tech Update · " + r["source"]
    return {"id": r["id"], "title": title, "body": r["title"] + " — " + _snippet(r["summary"], 110), "image": r.get("image") or r.get("logo"),
            "data": {"n": f"{table}:{r['id']}", "slot": "news" if table == "school_news" else "tech"}}


def pick_job(topic):
    sent, _ = _sent_ids(topic); today = datetime.now(timezone.utc).date().isoformat()
    since = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    rows = SB.table("jobs").select("id,title,summary,source,company,location,kind,deadline,logo,published").gte("published", since) \
             .or_(f"deadline.is.null,deadline.gte.{today}").order("has_img", desc=True).order("published", desc=True).limit(80).execute().data or []
    rows = [r for r in rows if r["id"] not in sent and r.get("summary")]
    pref = [r for r in rows if r.get("kind") in ("graduate", "internship", "ngo", "research")] or rows
    if not pref: return None
    r = pref[0]
    tag = {"internship": "🎒 Internship", "graduate": "🎓 Graduate role", "research": "🔬 Research / Teaching", "ngo": "🤝 NGO job", "remote": "🌍 Remote job"}.get(r.get("kind") or "", "💼 Job")
    title = f"{tag} · {r.get('company') or r['source']}" + (f" · {r['location']}" if r.get("location") else "")
    dl = _days_left(r.get("deadline") or "")
    chip = f"⏳ Closes in {dl} days · " if dl is not None and 0 <= dl <= 14 else (f"📅 Closes {r['deadline']} · " if r.get("deadline") else "")
    return {"id": r["id"], "title": title, "body": r["title"] + " — " + chip + _snippet(r["summary"], 100), "image": r.get("logo"),
            "data": {"n": f"jobs:{r['id']}", "slot": "jobs"}}


def run_slot(project, token, topic, slot, region):
    item = {"morning": lambda: pick_scholarship(topic, region), "evening": lambda: pick_scholarship(topic, region),
            "closing": lambda: pick_scholarship(topic, region, closing=True) or pick_scholarship(topic, region),
            "news": lambda: pick_news(topic, "school_news") or pick_scholarship(topic, region),
            "tech": lambda: pick_news(topic, "tech_news") or pick_scholarship(topic, region),
            "jobs": lambda: pick_job(topic) or pick_scholarship(topic, region)}[slot]()
    if not item: log.info("%s/%s: nothing to send", topic, slot); return False
    ok = _send(project, token, topic, slot, item["title"], item["body"], item.get("image"), {**item["data"], "topic": topic})
    if ok: SB.table("notif_log").insert({"slot": slot, "topic": topic, "item_id": item["id"]}).execute()
    log.info("%s/%s -> %s | %s", topic, slot, "sent" if ok else "FAILED", item["title"][:70])
    return ok


def main():
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
    if not raw: log.info("no FIREBASE_SERVICE_ACCOUNT – skipping"); return
    sa = json.loads(raw); project = sa["project_id"]; token = _token(sa)
    now = datetime.now(timezone.utc)
    force_slot, force_topic = os.environ.get("SLOT"), os.environ.get("TOPIC")
    # ONE schedule for everybody (Nigeria time, UTC+1): the same card reaches every audience at the same moment,
    # whichever region a user picked in the app. Regional topics are kept only so older app versions still receive it.
    off = 1
    local_hour = (now + timedelta(hours=off)).hour
    if not force_slot and not (7 <= local_hour < 22): log.info("quiet hours (local %02d:00)", local_hour); return
    # GitHub's schedule is often delayed or skipped, so instead of requiring an exact hour we send the LATEST slot
    # that is already due today and has not been sent yet (one per run – no bursts).
    day_start = (now + timedelta(hours=off)).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=off)
    done = {r["slot"] for r in SB.table("notif_log").select("slot").eq("topic", "all").gte("sent_at", day_start.isoformat()).execute().data}
    due = [SLOT_HOUR[h] for h in sorted(SLOT_HOUR) if h <= local_hour and SLOT_HOUR[h] not in done]
    slot = force_slot or (due[-1] if due else None)
    if not slot: log.info("nothing due (local %02d:00)", local_hour); return
    item = {"morning": lambda: pick_scholarship("all", ""), "evening": lambda: pick_scholarship("all", ""),
            "closing": lambda: pick_scholarship("all", "", closing=True) or pick_scholarship("all", ""),
            "news": lambda: pick_news("all", "school_news") or pick_scholarship("all", ""),
            "tech": lambda: pick_news("all", "tech_news") or pick_scholarship("all", ""),
            "jobs": lambda: pick_job("all") or pick_scholarship("all", "")}[slot]()
    if not item: log.info("%s: nothing to send", slot); return
    sent = 0
    for topic in TOPICS:
        if force_topic and topic != force_topic: continue
        try:
            ok = _send(project, token, topic, slot, item["title"], item["body"], item.get("image"), {**item["data"], "topic": topic})
            if ok: SB.table("notif_log").insert({"slot": slot, "topic": topic, "item_id": item["id"]}).execute(); sent += 1
        except Exception as e: log.warning("%s/%s failed: %s", topic, slot, e)
    log.info("%s -> %s | sent to %d audiences", slot, item["title"][:70], sent)


if __name__ == "__main__":
    main()
