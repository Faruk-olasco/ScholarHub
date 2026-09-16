"""One-shot crawler: fetch every source, write new/updated scholarships to Supabase, exit.
Runs on GitHub Actions on a schedule (twice a day) — see .github/workflows/crawl.yml.

Env: SUPABASE_URL, SUPABASE_SERVICE_KEY (service_role key – never ship this in the app),
     optional MAX_WORKERS (default 8), SKIP_SEARCH=1 to skip web-search sources.
"""
import os, sys, time, logging, random
from datetime import datetime, timezone, date
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import scraper, discovery          # reuse the exact same extraction logic
from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("crawl")

SB = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "8"))
BRAVE_GAP = 240   # seconds between Brave queries (they rate-limit); Google News is fine at ~2s
_last_brave = [0.0]


def ensure_sources():
    """Insert default + discovery sources if missing; return enabled ones."""
    defaults = scraper.DEFAULT_SOURCES + ([] if os.environ.get("SKIP_SEARCH") else discovery.build_query_sources())
    existing = {r["name"] for r in SB.table("sources").select("name").execute().data}
    rows = [{"name": n, "url": u, "kind": k, "tier": t} for n, u, k, t in defaults if n not in existing]
    for i in range(0, len(rows), 200):
        SB.table("sources").insert(rows[i:i + 200]).execute()
    if rows:
        log.info("registered %d new sources", len(rows))
    return SB.table("sources").select("*").eq("enabled", True).execute().data


def known_urls_for(source_name):
    return {r["url"] for r in SB.table("scholarships").select("url").eq("source", source_name).limit(2000).execute().data}


def process(src):
    if src["kind"] == "brave":                       # be polite to Brave
        wait = _last_brave[0] + BRAVE_GAP - time.time()
        if wait > 0: time.sleep(wait)
        _last_brave[0] = time.time()
    known = known_urls_for(src["name"]) if src["kind"] != "rss" else set()
    res = scraper.fetch_source(src["name"], src["url"], src["kind"], src.get("etag"), src.get("last_modified"), known)
    items = []
    for it in res["items"]:
        items.append({k: v for k, v in it.items() if k not in ("found_links", "content_hash")})
    found = {}
    for it in res["items"]:
        found.update(it.get("found_links") or {})
    return src, res, items, found


def upsert(items):
    """Insert new rows; for existing rows refresh deadline/last_seen. Returns number of new ids."""
    if not items:
        return 0
    ids = [i["id"] for i in items]
    existing = set()
    for i in range(0, len(ids), 300):
        existing |= {r["id"] for r in SB.table("scholarships").select("id").in_("id", ids[i:i + 300]).execute().data}
    new = [i for i in items if i["id"] not in existing]
    old = [{"id": i["id"], "deadline": i["deadline"], "last_seen": datetime.now(timezone.utc).isoformat()} for i in items if i["id"] in existing and i["deadline"]]
    for i in range(0, len(new), 200):
        SB.table("scholarships").upsert(new[i:i + 200], on_conflict="id").execute()
    for i in range(0, len(old), 200):
        SB.table("scholarships").upsert(old[i:i + 200], on_conflict="id").execute()
    return len(new)


def add_discovered(found):
    if not found:
        return 0
    existing = {r["url"] for r in SB.table("sources").select("url").execute().data}
    rows = [{"name": f"🌐 {h}", "url": u, "kind": "html", "tier": "official"} for h, u in found.items()
            if not any(h in e for e in existing)]
    if rows:
        SB.table("sources").upsert(rows, on_conflict="name").execute()
    return len(rows)


def main():
    started = datetime.now(timezone.utc)
    run = SB.table("runs").insert({"started": started.isoformat()}).execute().data[0]
    sources = ensure_sources()
    random.shuffle(sources)
    # Brave queries are slow (4-min spacing) – cap how many we do per run so the job finishes in time
    brave = [s for s in sources if s["kind"] == "brave"][:int(os.environ.get("BRAVE_PER_RUN", "6"))]
    others = [s for s in sources if s["kind"] != "brave"]
    todo = others + brave
    log.info("checking %d sources (%d official, %d search)", len(todo),
             sum(s["tier"] == "official" for s in todo), sum(s["tier"] == "search" for s in todo))

    new_total, errors, discovered, all_new = 0, [], 0, []
    with ThreadPoolExecutor(MAX_WORKERS) as ex:
        futs = [ex.submit(process, s) for s in todo]
        for f in as_completed(futs):
            try:
                src, res, items, found = f.result()
            except Exception as e:
                log.warning("worker error: %s", e); continue
            try:
                n = upsert(items)
                new_total += n
                if n: all_new += items[:n]
                discovered += add_discovered(found)
                SB.table("sources").update({
                    "last_run": datetime.now(timezone.utc).isoformat(),
                    "last_status": res["error"] or ("ok" if res["changed"] else "not modified"),
                    "last_count": len(items), "etag": res["etag"], "last_modified": res["last_modified"],
                    "checks": (src.get("checks") or 0) + 1, "changes": (src.get("changes") or 0) + (1 if n else 0),
                }).eq("id", src["id"]).execute()
            except Exception as e:
                log.warning("db error for %s: %s", src["name"], e)
            if res["error"]:
                errors.append(f"{src['name']}: {res['error'][:80]}")
            log.info("%-45s %-14s items=%-3d new=%d", src["name"][:45], (res["error"] or "ok")[:14], len(items), n if not res["error"] else 0)

    try:
        SB.rpc("purge_expired").execute()
    except Exception as e:
        log.warning("purge failed: %s", e)
    total = SB.table("scholarships").select("id", count="exact").limit(1).execute().count
    SB.table("runs").update({"finished": datetime.now(timezone.utc).isoformat(), "new_items": new_total,
                             "total_items": total, "notes": "; ".join(errors)[:2000]}).eq("id", run["id"]).execute()
    log.info("DONE: %d new, %d total, %d new sources discovered, %d source errors, %.0fs",
             new_total, total, discovered, len(errors), (datetime.now(timezone.utc) - started).total_seconds())

    # optional alerts
    if all_new and (os.environ.get("SMTP_HOST") or os.environ.get("TELEGRAM_BOT_TOKEN")):
        try:
            from crawler.alerts import dispatch
            dispatch(SB, all_new)
        except Exception as e:
            log.warning("alerts failed: %s", e)


if __name__ == "__main__":
    main()
