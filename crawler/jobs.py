"""
ScholarHub – Jobs crawler (entry-level / graduate / internship-NYSC / NGO / research-teaching / remote).

Completely separate from the scholarship and news crawlers: writes ONLY to the `jobs` table.

What it does, twice a day (called by .github/workflows/crawl.yml after news.py):
  1. reads public job-board feeds (Nigeria + remote + international graduate programmes)
  1b. EMPLOYER WATCH LIST (table `job_sources`, managed from Supabase – one row per university/employer):
      - WordPress sites: asks the site's own search for recruitment / vacancies / employment and keeps dated,
        vacancy-looking posts from the last 60 days (OAU, ABU, Unilorin, UNIPORT, ABUAD, NIMR, IITA, …)
      - plain careers/vacancies pages: keeps the vacancy links on that page (UI, FUNAAB, African Union, …)
      - a direct RSS feed url also works
      These land in Jobs as tier 'official' with the institution as company; no entry-level filter is applied
      (Lecturer, Technologist, Registrar … all welcome). Add an employer = add one row, no code change.
  2. keeps only the kinds of roles students/graduates want (WANT) and drops noise (drivers, sales agents,
     "(N positions)" roundups, …)
  3. de-duplicates by title+company and by URL
  4. opens each NEW job page to read the real Closing Date (and schema.org JobPosting data when present)
  5. finds the employer's logo through media.logo_for (Wikidata / employer website) – never a job-board logo,
     never a board's promo graphic, never a fake placeholder. No logo found -> card simply has no picture.
  6. expiry: a job disappears from the app the day after its closing date (app filter) and is deleted here
     1 day after the closing date, or 30 days after it was posted when no closing date is stated.

Env: SUPABASE_URL, SUPABASE_SERVICE_KEY. Optional: JOBS_PAGE_FETCH (job pages opened per run, default 120),
     TRY_INDEED=1 to attempt Indeed once (their RSS is usually blocked – harmless if it fails).
"""
import os, re, sys, html, json, hashlib, logging, time
from datetime import datetime, timezone, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests, feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dparser
from supabase import create_client

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import media

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("jobs")
SB = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
UTC = timezone.utc
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Mobile Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-NG,en;q=0.9"}
PAGE_FETCH = int(os.environ.get("JOBS_PAGE_FETCH", "120"))
KEEP_UNDATED_DAYS = 30

# ---------------------------------------------------------------------------------------------
# Sources: (name, feed url, kind)  – all public RSS/XML feeds that work from GitHub Actions
# ---------------------------------------------------------------------------------------------
FEEDS = [
    ("HotNigerianJobs", "https://www.hotnigerianjobs.com/feed/", "ng"),
    ("Jobzilla", "https://jobzilla.ng/feed/", "ng"),
    ("MyJobMag", "https://www.myjobmag.com/jobsxml.xml", "ng"),
    ("Jobs in Nigeria", "https://www.jobsinnigeria.careers/feed/", "ng"),
    ("NGCareers", "https://ngcareers.com/feed/", "ng"),
    ("Opportunities for Africans", "https://www.opportunitiesforafricans.com/category/jobs/feed/", "intl"),
    ("We Work Remotely", "https://weworkremotely.com/remote-jobs.rss", "remote"),
]
if os.environ.get("TRY_INDEED"):
    FEEDS.append(("Indeed Nigeria", "https://ng.indeed.com/rss?q=graduate+trainee&l=Nigeria&sort=date", "ng"))

WANT = re.compile(r"\b(graduate|trainee|intern(ship)?s?|nysc|siwes|entry[- ]level|fresh graduates?|junior|associate|assistant|officer|"
                  r"analyst|fellow(ship)?|research(er)?|teaching|teacher|lecturer|tutor|volunteer|ngo|programme|program|remote|"
                  r"developer|engineer|software|data|design(er)?|marketing|communications?|content|finance|account(ant|s)?|audit|"
                  r"hr|human resources|recruit(er|ment)|admin(istrative)?|customer (service|support|success)|front desk|"
                  r"nurse|pharmac\w*|medical|laboratory|lab |clinical|monitoring|evaluation|m&e|project|field officer|"
                  r"social media|writer|editor|legal|paralegal|economist|statistic|procurement|logistics|supply chain|"
                  r"operations?|business development|relationship|product|ux|ui|qa|quality|support|technician|it )", re.I)
NOISE = re.compile(r"\b(drivers?|dispatch riders?|riders?|cleaners?|janitor|security (guard|officer|personnel)|guards?|"
                   r"sales? (agents?|reps?|representatives?|girls?|boys?|executives?|canvassers?)|direct sales|field sales|"
                   r"cashiers?|waiters?|waitress(es)?|cooks?|chefs?|housekeep\w*|nann(y|ies)|stewards?|"
                   r"factory workers?|loaders?|forklift|trucks?|okada|tricycle|barbers?|hair\w*|tailors?|plumbers?|masons?|"
                   r"welders?|artisans?|bricklayer|carpenters?|electricians?|generator|domestic|gardener|laundry|"
                   r"job recruitment \(\d+ positions\)|\(\d+ positions\)|\(\d+ openings\)|ongoing recruitment|massive recruitment|"
                   r"latest (jobs|vacancies)|job vacancies at|jobs at |recruitment at |sugar mummy|forex|betting|pos agent|"
                   r"loan (officer|recovery)|debt recovery|marketer|network marketing|mlm|"
                   r"vp|vice president|head of|director|chief|cto|cfo|ceo|coo|senior manager|general manager|principal|lead )", re.I)

KIND_RULES = [("internship", r"\bintern(ship)?s?\b|\bnysc\b|\bsiwes\b|industrial training"), ("graduate", r"\bgraduate|\btrainee|entry[- ]level|fresh"),
              ("research", r"fellow|research|lecturer|teaching|teacher|tutor|academic|postdoc"),
              ("ngo", r"volunteer|ngo|foundation|initiative|unicef|undp|who\b|save the children|red cross|msf|chai\b|consortium|relief|humanitarian|non[- ]profit|charity"),
              ("remote", r"remote|work from home|anywhere")]

# ---------------------------------------------------------------------------------------------
# Employer watch list (table job_sources: name, url, type auto|page|feed, location, logo, active)
# ---------------------------------------------------------------------------------------------
OFFICIAL_MAX_AGE = 60       # an institution's advert older than this is treated as closed
SEARCH_WORDS = ["recruitment", "vacancies", "vacancy", "employment"]
OFFICIAL_WANT = re.compile(r"recruit|vacanc|advertis\w*\s+(for|of)|post(s)? of|applications? (are |is )?invited|employment opportunit|"
                           r"job (opening|vacanc|opportunit|advert|offer)|openings?\b|hiring|now recruiting|internship (programme|program|opportunit|position)|"
                           r"graduate trainee|trainee programme|lecturer|professor|technologist|bursar|registrar|librarian|research (assistant|officer|fellow)|wanted", re.I)
# links on a static careers page have no date, so they must carry an explicit "we are recruiting" word (a role word alone = a staff list)
PAGE_WANT = re.compile(r"recruit|vacanc|advertis\w*\s+(for|of)|post(s)? of|applications? (are |is )?invited|employment opportunit|"
                       r"job (opening|vacanc|opportunit|advert|offer)|openings?\b|hiring|internship (programme|program|opportunit|position)|graduate trainee", re.I)
OFFICIAL_SKIP = re.compile(r"screening|shortlist|scam|beware|fake|\bcbt\b|test schedule|aptitude test|results?\b|interview|invited applicants|"
                           r"mop[- ]up|congrat|privacy|policy|strateg|statistic|newsletter|accreditation|seminar|licen[cs]e|workshop|conference|"
                           r"\blectures?\b|inaugural|admission|matriculation|convocation|appointed|appoints|appointment of|inaugurat|visit|\bwins?\b|"
                           r"award|budget|partnership|celebrat|principal officers|tender|expression of interest|\breoi\b|consultan|procurement|\bbid|"
                           r"portal (is )?closed|closed\b|extension of|postpone|disclaimer|press release|our positions|^careers?$|^recruitment$|^vacanc(y|ies)$", re.I)


def load_sources():
    try:
        return SB.table("job_sources").select("*").eq("active", True).execute().data or []
    except Exception as e:
        log.warning("job_sources table not readable (run the SQL once): %s", e); return []


def official_row(s, title, link, pub, summ="", strict=False):
    title = clean(title)
    title = re.sub(r"\s*[-–|]\s*(" + re.escape(s["name"][:12]) + r"|home|news|welcome).*$", "", title, flags=re.I).strip() or title
    if not (10 <= len(title) <= 180) or not OFFICIAL_WANT.search(title) or OFFICIAL_SKIP.search(title): return None
    if strict and not PAGE_WANT.search(title): return None
    if re.match(r"https?://|www\.", title, re.I): return None     # anchor text that is just a web address
    if not link.startswith("http") or re.search(r"\.(jpe?g|png|gif|webp)(\?|$)", link, re.I): return None
    text = title + " " + (summ or "")[:400]
    return {"id": jid(link), "title": title[:160], "summary": clean(summ)[:600], "url": link, "source": s["name"], "tier": "official",
            "company": s["name"][:100], "location": (s.get("location") or "Nigeria")[:40], "kind": kind_of(text),
            "deadline": None, "published": pub.isoformat(), "industry": "Education" if re.search(r"universit|polytechnic|college|institute", s["name"], re.I) else None,
            "_logo": s.get("logo") or None}


def _rss(url):
    try:
        r = get(url)
        if re.search(rb"<(rss|feed)\b", r.content[:4000]): return feedparser.parse(r.content)
    except Exception:
        pass
    return None


def from_wp_search(s):
    """WordPress site: /search/<word>/feed/rss2/ (or ?s=<word>&feed=rss2). Returns (rows, feed_worked)."""
    out, seen, worked = [], set(), False
    root = s["url"].rstrip("/")
    for kw in SEARCH_WORDS:
        f = _rss(f"{root}/search/{kw}/feed/rss2/") or _rss(f"{root}/?s={kw}&feed=rss2")
        if not f: continue
        worked = True
        for e in f.entries[:40]:
            link = (e.get("link") or "").strip().split("#")[0]
            if not link or link in seen: continue
            seen.add(link)
            try: pub = datetime(*e.published_parsed[:6], tzinfo=UTC)
            except Exception: continue      # undated = a static page (e.g. "Registry") – can't tell if it is current, skip
            if pub < datetime.now(UTC) - timedelta(days=OFFICIAL_MAX_AGE): continue
            row = official_row(s, e.get("title"), link, pub, clean(e.get("summary") or ""))
            if row: out.append(row)
    return out, worked


def from_page(s):
    """A careers/vacancies page: every vacancy-looking link on it; if none, the page itself when its title is an advert."""
    out, ids = [], set()
    try:
        h = get(s["url"]).text
    except Exception as e:
        log.warning("%s: page failed: %s", s["name"], e); return out
    from urllib.parse import urljoin
    soup = BeautifulSoup(h, "html.parser"); now = datetime.now(UTC)
    for a in soup.find_all("a", href=True):
        t = clean(a.get_text(" "))
        link = urljoin(s["url"], a["href"]).split("#")[0]
        if link.rstrip("/") == s["url"].rstrip("/") or a["href"].startswith(("#", "javascript", "mailto")): continue
        row = official_row(s, t, link, now, "", strict=True)
        if row and row["id"] not in ids: ids.add(row["id"]); out.append(row)
    if soup.title and soup.title.string:          # the page itself may be the advert (funaab.edu.ng/recruitment = "Staff Recruitment – 2025")
        row = official_row(s, soup.title.string, s["url"], now, "", strict=True)
        if row and row["id"] not in ids: out.insert(0, row)
    return out[:30]


def from_source(s):
    kind = (s.get("type") or "auto").lower()
    try:
        if kind == "feed" or re.search(r"/feed/?$|\.(rss|xml)$|feed=rss", s["url"]):
            f = _rss(s["url"]); out = []
            for e in (f.entries if f else [])[:60]:
                try: pub = datetime(*e.published_parsed[:6], tzinfo=UTC)
                except Exception: pub = datetime.now(UTC)
                if pub < datetime.now(UTC) - timedelta(days=OFFICIAL_MAX_AGE): continue
                row = official_row(s, e.get("title"), (e.get("link") or "").strip(), pub, clean(e.get("summary") or ""))
                if row: out.append(row)
            return out
        if kind == "page": return from_page(s)
        rows, worked = from_wp_search(s)
        return rows if worked else from_page(s)
    except Exception as e:
        log.warning("%s: %s", s.get("name"), e); return []


def clean(t):
    t = html.unescape(re.sub(r"<[^>]+>", " ", t or ""))
    return re.sub(r"\s+", " ", t).strip()


def jid(url):
    return "j_" + hashlib.sha1(url.strip().encode()).hexdigest()[:16]


def kind_of(text):
    t = (text or "").lower()
    for k, rx in KIND_RULES:
        if re.search(rx, t): return k
    return "job"


def parse_day(s):
    """'2nd November, 2026' / '2026-11-03T00:00:00' / 'Nov 3, 2026' -> 'YYYY-MM-DD' or None (never a past year)."""
    if not s: return None
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", clean(str(s)))
    s = re.sub(r"\b(not specified|unspecified|n/?a|none|ongoing)\b.*", "", s, flags=re.I).strip(" .:-")
    if not s: return None
    try:
        m = re.match(r"(20\d\d)-(\d\d)-(\d\d)", s)
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else dparser.parse(s, dayfirst=True, fuzzy=True, default=datetime(datetime.now().year, 1, 1)).date()
    except Exception:
        return None
    today = datetime.now(UTC).date()
    if d < today - timedelta(days=2) or d > today + timedelta(days=400): return None
    return d.isoformat()


def get(url):
    r = requests.get(url, headers=UA, timeout=(8, 20), allow_redirects=True)
    r.raise_for_status()
    return r


def split_title(title, source):
    """-> (role, company). Boards write 'Role at Company' (Nigeria) or 'Company: Role' (WWR)."""
    title = clean(title)
    title = re.sub(r"\s*[-–|]\s*(hotnigerianjobs|jobzilla|myjobmag|jobs in nigeria|ngcareers).*$", "", title, flags=re.I)
    if source == "We Work Remotely":
        m = re.match(r"(.+?):\s*(.+)", title)
        if m: return m.group(2).strip(), m.group(1).strip()
        return title, ""
    m = re.match(r"(.+?)\s+(?:at|@)\s+(.+)$", title, re.I)
    if m: return m.group(1).strip(), re.sub(r"\s*\(.*?\)\s*$", "", m.group(2)).strip()
    return title, ""


def location_of(text, source, feed_kind):
    if feed_kind == "remote" or re.search(r"\bremote\b|work from home", text, re.I): return "Remote"
    m = re.search(r"\b(?:Location|Based in|Job Location)\s*:?\s*([A-Z][A-Za-z\- ]+(?:,\s*[A-Z][A-Za-z ]+)?)", text)
    if m:
        loc = re.split(r",| Employment| Job | Slots?| Type", m.group(1))[0].strip()
        if 2 < len(loc) <= 30 and not re.search(r"nigeria", loc, re.I): return loc
    if feed_kind == "ng": return "Nigeria"
    m = re.search(r"\b(Kenya|Ghana|South Africa|Rwanda|Uganda|Tanzania|Ethiopia|Egypt|UK|United Kingdom|USA|United States|Canada|Germany|Netherlands|Switzerland|Europe|Africa|Global|Worldwide)\b", text, re.I)
    return m.group(1) if m else "International"


def from_feed(name, url, feed_kind):
    out = []
    try:
        f = feedparser.parse(get(url).content)
    except Exception as e:
        log.warning("%s: feed failed: %s", name, e); return out
    for e in f.entries[:500]:
        link = (e.get("link") or "").strip()
        raw_title = clean(e.get("title"))
        if not link or len(raw_title) < 8: continue
        if NOISE.search(raw_title): continue
        if feed_kind != "remote" and not WANT.search(raw_title): continue
        role, company = split_title(raw_title, name)
        summ = clean(e.get("summary") or (e.get("content") or [{}])[0].get("value", "") or "")
        summ = re.sub(r"^(job (title|description)\s*:?\s*)", "", summ, flags=re.I)
        text = role + " " + company + " " + summ[:400]
        if feed_kind == "remote" and not re.search(r"junior|entry|associate|intern|graduate|support|assistant|analyst|coordinator|writer|designer|developer|engineer|marketing|customer", text, re.I):
            continue   # remote feed: skip senior/lead roles
        try: pub = datetime(*e.published_parsed[:6], tzinfo=UTC)
        except Exception: pub = datetime.now(UTC)
        if pub < datetime.now(UTC) - timedelta(days=KEEP_UNDATED_DAYS): continue
        dl = None
        m = re.search(r"(?:Application )?(?:Deadline|Closing Date|Apply before|Expires?)\s*:?\s*([0-9]{1,2}(?:st|nd|rd|th)?,?\s+[A-Za-z]+,?\s+20\d\d|[A-Za-z]+\s+[0-9]{1,2},?\s+20\d\d|20\d\d-\d\d-\d\d)", summ)
        if m: dl = parse_day(m.group(1))
        out.append({"id": jid(link), "title": role[:160], "summary": summ[:600], "url": link, "source": name, "tier": "board",
                    "company": company[:100], "location": location_of(text, name, feed_kind)[:40], "kind": kind_of(text),
                    "deadline": dl, "published": pub.isoformat(), "industry": clean(e.get("industry") or "")[:60] or None})
    return out


# ---------------------------------------------------------------------------------------------
# Job page: closing date + schema.org JobPosting (+ employer logo if the page carries one)
# ---------------------------------------------------------------------------------------------
GENERIC_LOGO = re.compile(r"/(company/|employer/|uploads/)?(logo|default|placeholder|no[-_]?logo|company|employer|blank)\.(png|jpe?g|webp)(\?|$)", re.I)
BOARD_HOSTS = re.compile(r"hotnigerianjobs|jobzilla|myjobmag|jobsinnigeria|ngcareers|weworkremotely|wwr|opportunitiesforafricans|indeed|"
                         r"wp-cookie|gravatar|share|facebook|twitter|whatsapp|linkedin|telegram|og-images", re.I)


def page_details(url):
    out = {}
    try:
        h = get(url).text
    except Exception:
        return out
    # 1) schema.org JobPosting
    for m in re.finditer(r"<script[^>]+ld\+json[^>]*>(.*?)</script>", h, re.S | re.I):
        try: d = json.loads(m.group(1).strip())
        except Exception: continue
        for x in (d if isinstance(d, list) else [d]):
            if not isinstance(x, dict): continue
            if x.get("@type") == "JobPosting" or (isinstance(x.get("@graph"), list) and any(isinstance(g, dict) and g.get("@type") == "JobPosting" for g in x["@graph"])):
                if x.get("@type") != "JobPosting": x = next(g for g in x["@graph"] if isinstance(g, dict) and g.get("@type") == "JobPosting")
                if x.get("validThrough"): out["deadline"] = parse_day(x["validThrough"][:10])
                org = x.get("hiringOrganization") or {}
                if isinstance(org, dict):
                    if org.get("name") and not BOARD_HOSTS.search(org["name"]): out["company"] = clean(org["name"])[:100]
                    lg = org.get("logo"); lg = lg.get("url") if isinstance(lg, dict) else lg
                    if lg and not BOARD_HOSTS.search(lg) and not GENERIC_LOGO.search(lg): out["logo"] = lg
                loc = x.get("jobLocation"); loc = loc[0] if isinstance(loc, list) and loc else loc
                if isinstance(loc, dict):
                    a = loc.get("address") or {}
                    city = a.get("addressLocality") if isinstance(a, dict) else None
                    if city and len(city) <= 30: out["location"] = clean(city)
                if x.get("description") and len(clean(x["description"])) > 80: out["summary"] = clean(x["description"])[:600]
    # 2) visible "Closing Date" text (HotNigerianJobs / Jobs in Nigeria style: <strong>Closing Date</strong><br/>2nd November, 2026.)
    if not out.get("deadline"):
        m = re.search(r"(?:Application )?(?:Closing Date|Deadline|Application Deadline)[^<]{0,20}(?:<[^>]+>\s*){0,4}([^<]{4,60})", h, re.I)
        if m: out["deadline"] = parse_day(m.group(1))
    # 2b) Nigerian institutions: "not later than six (6) weeks from the date of this advertisement" -> counted from the publish date
    if not out.get("deadline"):
        txt = clean(re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I))
        m = re.search(r"(?:within|not later than|closes? (?:in|within)|on or before|latest)\s+(?:a period of\s+)?(one|two|three|four|five|six|seven|eight|nine|ten|twelve|\d{1,2})\s*(?:\(\d+\)\s*)?(weeks?|days?|months?)\s+(?:from|of|after)", txt, re.I)
        if m:
            n = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12}.get(m.group(1).lower()) or int(m.group(1))
            out["deadline_days"] = n * (7 if m.group(2).lower().startswith("w") else 30 if m.group(2).lower().startswith("m") else 1)
    # 3) employer logo shown on the page (never the board's own branding)
    if not out.get("logo"):
        soup = BeautifulSoup(h, "html.parser")
        for im in soup.find_all("img"):
            src = im.get("data-src") or im.get("src") or ""
            blob = " ".join([src, im.get("alt") or "", str(im.get("class") or ""), str(im.get("id") or "")]).lower()
            if re.search(r"company|employer|organisation|organization|client|brand", blob) and not BOARD_HOSTS.search(blob) and not re.search(r"\.svg|\.gif|site-logo|header|footer|nav", blob):
                from urllib.parse import urljoin
                if GENERIC_LOGO.search(src): continue
                out["logo"] = urljoin(url, src); break
    return out


def finish_row(r):
    """Opens the job page for a new row, then looks for the employer's real logo."""
    d = page_details(r["url"])
    if not d.get("deadline") and d.get("deadline_days") and not r.get("deadline"):
        try: r["deadline"] = (dparser.parse(r["published"]).date() + timedelta(days=d["deadline_days"])).isoformat()   # may already be past -> hidden & purged
        except Exception: pass
    for k in ("deadline", "company", "location", "summary"):
        if d.get(k) and (not r.get(k) or k == "deadline"): r[k] = d[k]
    logo = r.pop("_logo", None) or d.get("logo")
    if not logo and r.get("company"):
        try:
            _, logo = media.logo_for(org_name=r["company"], SB=SB)
        except Exception as e:
            log.debug("logo %s: %s", r["company"], e)
    r["logo"] = logo
    r["image"] = None           # job pages never carry a genuine picture of the job; boards only have promo graphics
    r["media_checked"] = datetime.now(UTC).isoformat()
    return r


def main():
    t0 = time.time()
    rows = []
    with ThreadPoolExecutor(6) as ex:
        for fut in as_completed([ex.submit(from_feed, n, u, k) for n, u, k in FEEDS]):
            got = fut.result(); rows.extend(got)
            if got: log.info("%-26s %3d kept", got[0]["source"], len(got))
    # employer watch list (official adverts straight from the institution's own website)
    sources = load_sources()
    if sources:
        with ThreadPoolExecutor(6) as ex:
            for src, got in zip(sources, ex.map(from_source, sources)):
                rows.extend(got)
                if got: log.info("%-26s %3d kept (official)", src["name"][:26], len(got))
    # de-dupe: same URL, or same role+company (boards repost each other)
    by_id, seen_key = {}, set()
    for r in sorted(rows, key=lambda r: r["published"], reverse=True):
        key = re.sub(r"\W+", "", (r["title"] + "|" + r["company"]).lower())
        if r["id"] in by_id or key in seen_key: continue
        by_id[r["id"]] = r; seen_key.add(key)
    rows = list(by_id.values())
    if not rows: log.warning("no jobs found"); return
    ids = [r["id"] for r in rows]; existing = set()
    for i in range(0, len(ids), 200):
        res = SB.table("jobs").select("id").in_("id", ids[i:i + 200]).execute()
        existing |= {x["id"] for x in (res.data or [])}
    new_rows = [r for r in rows if r["id"] not in existing]
    old_rows = [r for r in rows if r["id"] in existing]
    # new rows: open the page (closing date, employer, logo) – a bounded number per run, the rest next crawl
    todo = sorted(new_rows, key=lambda r: r["published"], reverse=True)[:PAGE_FETCH]
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(finish_row, todo))
    now = datetime.now(UTC).isoformat()
    for r in new_rows: r["first_seen"] = now; r["last_seen"] = now; r.pop("_logo", None)
    # PostgREST needs identical keys per batch -> group by key-set
    groups = {}
    for r in new_rows: groups.setdefault(tuple(sorted(r.keys())), []).append(r)
    for g in groups.values():
        for i in range(0, len(g), 100): SB.table("jobs").upsert(g[i:i + 100], on_conflict="id").execute()
    # already-known rows: only touch last_seen (+ deadline when the feed now states one)
    for r in old_rows:
        upd = {"last_seen": now}
        if r.get("deadline"): upd["deadline"] = r["deadline"]
        if r.get("tier") == "official": upd["title"] = r["title"]   # e.g. a vacancies page whose heading changed to the new year
        try: SB.table("jobs").update(upd).eq("id", r["id"]).execute()
        except Exception: pass
    # rows inserted earlier without a page visit (over the per-run budget): finish a batch now
    try:
        pend = SB.table("jobs").select("id,title,summary,url,source,company,location,kind,deadline").is_("media_checked", "null").order("published", desc=True).limit(max(0, PAGE_FETCH - len(todo))).execute().data or []
        if pend:
            with ThreadPoolExecutor(6) as ex:
                for r in ex.map(finish_row, pend):
                    SB.table("jobs").update({k: r.get(k) for k in ("deadline", "company", "location", "summary", "logo", "image", "media_checked")}).eq("id", r["id"]).execute()
            log.info("finished %d pending rows", len(pend))
    except Exception as e:
        log.warning("pending step: %s", e)
    # expiry: day after the closing date; or 30 days after posting when no closing date is stated
    today = datetime.now(UTC).date()
    SB.table("jobs").delete().lt("deadline", (today - timedelta(days=1)).isoformat()).execute()
    SB.table("jobs").delete().is_("deadline", "null").neq("tier", "official").lt("published", (datetime.now(UTC) - timedelta(days=KEEP_UNDATED_DAYS)).isoformat()).execute()
    SB.table("jobs").delete().is_("deadline", "null").eq("tier", "official").lt("published", (datetime.now(UTC) - timedelta(days=OFFICIAL_MAX_AGE)).isoformat()).execute()
    with_logo = sum(1 for r in todo if r.get("logo")); with_dl = sum(1 for r in todo if r.get("deadline"))
    log.info("jobs: %d kept, %d new (%d pages opened: %d with logo, %d with closing date) in %.0fs", len(rows), len(new_rows), len(todo), with_logo, with_dl, time.time() - t0)


if __name__ == "__main__":
    main()
