"""One-time repair: delete rows whose url is a Google image/asset (bug in early crawls).
The next crawl re-adds them with the correct article URLs.
Run via GitHub → Actions → "Fix bad URLs", or locally with SUPABASE_URL / SUPABASE_SERVICE_KEY set."""
import os, sys, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from supabase import create_client
from app.scraper import is_good_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
SB = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

bad, offset = [], 0
while True:
    rows = SB.table("scholarships").select("id,url").range(offset, offset + 999).execute().data
    if not rows:
        break
    bad += [r["id"] for r in rows if not is_good_url(r["url"])]
    offset += 1000
logging.info("scanned %d rows, %d with bad URLs", offset, len(bad))
for i in range(0, len(bad), 200):
    SB.table("scholarships").delete().in_("id", bad[i:i + 200]).execute()
logging.info("deleted %d bad rows – run 'Crawl scholarships' to refill them with correct links", len(bad))
