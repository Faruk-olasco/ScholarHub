"""
send_push.py — send ONE notification to everyone (or one region) right now, by hand.

Run from GitHub → Actions → "Send push" → Run workflow.  Env (all optional except TITLE or ITEM):
  TITLE   notification title            BODY   text line (max ~240 chars)
  IMAGE   https:// picture link         TOPIC  all (default) | r_africa | r_europe | r_north_america | r_asia | r_middle_east | r_oceania | r_latin_america
  ITEM    what opens when tapped: a scholarship id (e.g. 2d6644a4cefb372e) or  jobs:<id> | school_news:<id> | tech_news:<id>
          If ITEM is given and TITLE/BODY/IMAGE are empty, they are filled from that card automatically.
Looks exactly like the daily picks (same channel, same card tap-to-open) and is logged in notif_log as slot "manual".
"""
import os, json, logging
from notify import SB, _token, _send, _snippet, log

TABLE_COLS = {"scholarships": "id,title,summary,deadline,source,image,logo", "jobs": "id,title,summary,company,location,deadline,logo,source",
              "school_news": "id,title,summary,school,source,image,logo", "tech_news": "id,title,summary,source,image,logo"}


def main():
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
    if not raw: raise SystemExit("FIREBASE_SERVICE_ACCOUNT secret missing")
    sa = json.loads(raw); project = sa["project_id"]; token = _token(sa)
    title, body, image = os.environ.get("TITLE", "").strip(), os.environ.get("BODY", "").strip(), os.environ.get("IMAGE", "").strip()
    topic, item = (os.environ.get("TOPIC", "").strip() or "all"), os.environ.get("ITEM", "").strip()
    data = {"slot": "manual", "topic": topic}
    if item:
        table, _, rid = item.partition(":")
        if not rid: table, rid = "scholarships", table
        if table not in TABLE_COLS: raise SystemExit(f"unknown table in ITEM: {table}")
        rows = SB.table(table).select(TABLE_COLS[table]).eq("id", rid).limit(1).execute().data
        if not rows: raise SystemExit(f"no row {rid} in {table}")
        r = rows[0]
        data["s" if table == "scholarships" else "n"] = rid if table == "scholarships" else f"{table}:{rid}"
        who = r.get("school") or r.get("company") or r.get("source") or ""
        title = title or (("💼 " if table == "jobs" else "🏫 " if table == "school_news" else "💻 " if table == "tech_news" else "🎓 ") + r["title"])
        chip = (("⏰ Closes " if table == "jobs" else "⏰ Deadline ") + r["deadline"] + " · ") if r.get("deadline") else ""
        body = body or (chip + (who + " — " if who else "") + _snippet(r.get("summary") or "", 140))
        image = image or r.get("image") or r.get("logo") or ""
    if not title: raise SystemExit("TITLE is required when no ITEM is given")
    body = body or "Open ScholarHub to see more."
    if image and not image.startswith("https://"): image = ""
    ok = _send(project, token, topic, "manual", title, body, image or None, data)
    if ok: SB.table("notif_log").insert({"slot": "manual", "topic": topic, "item_id": item or title[:60]}).execute()
    log.info("manual push to %s -> %s | %s", topic, "SENT" if ok else "FAILED", title[:80])
    if not ok: raise SystemExit(1)


if __name__ == "__main__":
    main()
