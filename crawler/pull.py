"""Pull scholarships from one or more links on demand.

Usage (locally or via the 'Pull from a link' GitHub workflow):
    python crawler/pull.py "https://university.edu/scholarships" ["https://another/feed" ...]
Env: SUPABASE_URL, SUPABASE_SERVICE_KEY
     SAVE_AS_SOURCE=1  -> also register the link(s) as permanent sources for future crawls
     DEEP=1            -> follow links on the page one level down (finds more on big listing pages)

Also processes any rows queued in the `pull_requests` table by the app (Admin → Pull from link).
"""
import os, sys, re, logging
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import scraper
from supabase import create_client
import requests, feedparser
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pull")
SB = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


def detect_kind(url, resp):
    ct = (resp.headers.get("content-type") or "").lower()
    head = resp.text[:600].lower()
    if "xml" in ct or "<rss" in head or "<feed" in head or url.endswith((".xml", "/feed", "/feed/", "/rss")):
        return "rss"
    return "html"


def find_feed(url, html):
    """If a page advertises an RSS feed, prefer it (cleaner data)."""
    soup = BeautifulSoup(html, "html.parser")
    for l in soup.find_all("link", attrs={"type": re.compile("rss|atom", re.I)}):
        if l.get("href"):
            return urljoin(url, l["href"])
    return None


def pull_one(url, save_as_source=False, deep=False):
    name = f"🔗 {urlparse(url).netloc.replace('www.', '')}"
    r = requests.get(url, headers=scraper.BROWSER_HEADERS, timeout=(5, 20))
    r.raise_for_status()
    kind = detect_kind(url, r)
    known = {x["url"] for x in SB.table("scholarships").select("url").eq("source", name).limit(3000).execute().data}
    items = []
    if kind == "rss":
        entries = feedparser.parse(r.content).entries
        items = [i for i in (scraper.normalise(e, name, fetch_full=e.get("link") not in known) for e in entries) if i]
    else:
        items = scraper.harvest_html(r.text, url, name, known, detail_limit=40 if deep else 15)
        feed = find_feed(url, r.text)          # ALSO read the site's feed if it has one (latest posts)
        if feed:
            try:
                fr = requests.get(feed, headers=scraper.BROWSER_HEADERS, timeout=(5, 20))
                entries = feedparser.parse(fr.content).entries
                if entries:
                    log.info("also reading feed %s", feed)
                    items += [i for i in (scraper.normalise(e, name, fetch_full=e.get("link") not in known) for e in entries)
                              if i and scraper.is_applyable(i["title"], i["summary"])]
            except Exception:
                pass
        if deep:   # one level down: harvest each linked listing page too
            soup = BeautifulSoup(r.text, "html.parser")
            subpages = {urljoin(url, a["href"]).split("#")[0] for a in soup.find_all("a", href=True)
                        if scraper.LINK_RE.search(a.get_text(" ")) and urlparse(urljoin(url, a["href"])).netloc == urlparse(url).netloc}
            for sp in list(subpages)[:25]:
                try:
                    sr = requests.get(sp, headers=scraper.BROWSER_HEADERS, timeout=(5, 15))
                    items += scraper.harvest_html(sr.text, sp, name, known, detail_limit=5)
                except Exception:
                    pass
    # dedupe by id, strip crawler-only keys
    seen, rows = set(), []
    for it in items:
        if it["id"] in seen: continue
        seen.add(it["id"]); rows.append({k: v for k, v in it.items() if k not in ("found_links", "content_hash")})
    ids = [x["id"] for x in rows]
    existing = set()
    for i in range(0, len(ids), 300):
        existing |= {x["id"] for x in SB.table("scholarships").select("id").in_("id", ids[i:i + 300]).execute().data}
    new = [x for x in rows if x["id"] not in existing]
    for i in range(0, len(new), 200):
        SB.table("scholarships").upsert(new[i:i + 200], on_conflict="id").execute()
    if save_as_source:
        SB.table("sources").upsert({"name": name + " " + urlparse(url).path[:40], "url": url, "kind": kind, "tier": "official", "enabled": True}, on_conflict="name").execute()
    log.info("%s -> found %d, %d new%s", url, len(rows), len(new), " (saved as permanent source)" if save_as_source else "")
    return len(rows), len(new)


def process_queue():
    """Links queued from the app's admin screen."""
    q = SB.table("pull_requests").select("*").eq("status", "pending").execute().data
    for row in q:
        try:
            found, new = pull_one(row["url"], row.get("save_as_source", False), row.get("deep", False))
            SB.table("pull_requests").update({"status": "done", "found": found, "new_items": new, "processed": datetime.now(timezone.utc).isoformat()}).eq("id", row["id"]).execute()
        except Exception as e:
            SB.table("pull_requests").update({"status": "error", "error": str(e)[:300], "processed": datetime.now(timezone.utc).isoformat()}).eq("id", row["id"]).execute()
    return len(q)


if __name__ == "__main__":
    urls = [u for u in sys.argv[1:] if u.strip()]
    save = os.environ.get("SAVE_AS_SOURCE") == "1"
    deep = os.environ.get("DEEP") == "1"
    for u in urls:
        try:
            pull_one(u.strip(), save, deep)
        except Exception as e:
            log.error("%s failed: %s", u, e)
    n = process_queue()
    if n: log.info("processed %d queued link(s) from the app", n)
