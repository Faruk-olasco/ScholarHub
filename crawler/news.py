"""
ScholarHub – School News (Nigerian universities) + Tech Updates crawler.

Completely separate from the scholarship crawler: writes ONLY to the `school_news` and `tech_news`
tables. Nothing here touches `scholarships`, so news can never appear in the scholarship feeds.

Env: SUPABASE_URL, SUPABASE_SERVICE_KEY   (same secrets as run.py)
Run:  python crawler/news.py             (called by .github/workflows/crawl.yml after run.py)
"""
import os, re, html, hashlib, logging, time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests, feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dparser
from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("news")
SB = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-NG,en;q=0.9"}
# retention per table: School News keeps a rolling 60 days; Tech Updates a rolling 14 days
KEEP_DAYS = {"school_news": 60, "tech_news": 14}      # delete once older than this
MAX_AGE_DAYS = {"school_news": 45, "tech_news": 14}   # never import anything older than this
ENRICH_PER_RUN = 120      # article pages opened per table per crawl to fill in missing snippets

# ---------------------------------------------------------------------------------------------
# Schools: code, full name, aliases (for matching outlet headlines), feed/page, kind
# ---------------------------------------------------------------------------------------------
SCHOOLS = [
    ("UI", "University of Ibadan", ["UI ", "University of Ibadan", "Ibadan varsity"], "https://ui.edu.ng/rss.xml", "rss"),
    ("UNILAG", "University of Lagos", ["UNILAG", "University of Lagos"], "https://unilag.edu.ng/feed/", "rss"),
    ("OAU", "Obafemi Awolowo University", ["OAU", "Obafemi Awolowo", "Ife varsity"], "https://oauife.edu.ng/feed/", "rss"),
    ("ABU", "Ahmadu Bello University", ["ABU Zaria", "Ahmadu Bello"], "https://abu.edu.ng/feed/", "rss"),
    ("UNN", "University of Nigeria, Nsukka", ["UNN", "University of Nigeria", "Nsukka"], "https://www.unn.edu.ng/feed/", "rss"),
    ("UNIBEN", "University of Benin", ["UNIBEN", "University of Benin"], "https://uniben.edu/", "html"),
    ("UNILORIN", "University of Ilorin", ["UNILORIN", "University of Ilorin"], "https://unilorin.edu.ng/feed/", "rss"),
    ("UNIPORT", "University of Port Harcourt", ["UNIPORT", "University of Port Harcourt"], "https://uniport.edu.ng/feed/", "rss"),
    ("UNICAL", "University of Calabar", ["UNICAL", "University of Calabar"], "https://unical.edu.ng/index.php/news", "html"),
    ("UNIJOS", "University of Jos", ["UNIJOS", "University of Jos"], "https://www.unijos.edu.ng/rss.xml", "rss"),
    ("UNIMAID", "University of Maiduguri", ["UNIMAID", "University of Maiduguri"], "https://unimaid.edu.ng/index.php/news", "html"),
    ("BUK", "Bayero University Kano", ["BUK", "Bayero University"], "https://buk.edu.ng/rss.xml", "rss"),
    ("UDUS", "Usmanu Danfodiyo University Sokoto", ["UDUS", "Usmanu Danfodiyo", "UDUSOK"], "https://udusok.edu.ng/feed/", "rss"),
    ("UNIUYO", "University of Uyo", ["UNIUYO", "University of Uyo"], "https://uniuyo.edu.ng/feed/", "rss"),
    ("UNIABUJA", "University of Abuja", ["UNIABUJA", "University of Abuja"], "https://www.uniabuja.edu.ng/news/", "html"),
    ("FUTMINNA", "Federal University of Technology Minna", ["FUTMINNA", "FUT Minna", "Federal University of Technology, Minna"], "https://futminna.edu.ng/feed/", "rss"),
    ("FUTO", "Federal University of Technology Owerri", ["FUTO", "FUT Owerri", "Federal University of Technology, Owerri"], "https://futo.edu.ng/news/", "html"),
    ("UNIZIK", "Nnamdi Azikiwe University", ["UNIZIK", "Nnamdi Azikiwe"], "https://unizik.edu.ng/news/", "html"),
    ("FUNAAB", "Federal University of Agriculture Abeokuta", ["FUNAAB", "Abeokuta"], "https://funaab.edu.ng/news/", "html"),
    ("MOUAU", "Michael Okpara University of Agriculture", ["MOUAU", "Michael Okpara"], "https://mouau.edu.ng/feed/", "rss"),
    ("FUDMA", "Federal University Dutsin-Ma", ["FUDMA", "Dutsin-Ma"], "https://fudutsinma.edu.ng/feed/", "rss"),
    ("FULOKOJA", "Federal University Lokoja", ["FULOKOJA", "Federal University Lokoja"], "https://fulokoja.edu.ng/index.php/news", "html"),
    ("NDA", "Nigerian Defence Academy", ["NDA", "Nigerian Defence Academy"], "https://nda.edu.ng/feed/", "rss"),
    ("LASU", "Lagos State University", ["LASU", "Lagos State University"], "https://lasu.edu.ng/index.php/news", "html"),
    ("UNIOSUN", "Osun State University", ["UNIOSUN", "Osun State University"], "https://uniosun.edu.ng/feed/", "rss"),
    ("AAUA", "Adekunle Ajasin University", ["AAUA", "Adekunle Ajasin"], "https://aaua.edu.ng/news/", "html"),
    ("EKSU", "Ekiti State University", ["EKSU", "Ekiti State University"], "https://eksu.edu.ng/feed/", "rss"),
    ("DELSU", "Delta State University", ["DELSU", "Delta State University"], "https://delsu.edu.ng/index.php/news", "html"),
    ("IMSU", "Imo State University", ["IMSU", "Imo State University"], "https://imsu.edu.ng/", "html"),
    ("KASU", "Kaduna State University", ["KASU", "Kaduna State University"], "https://kasu.edu.ng/feed/", "rss"),
    ("RSU", "Rivers State University", ["RSU", "Rivers State University"], "https://www.rsu.edu.ng/feed/", "rss"),
    ("AAU", "Ambrose Alli University", ["AAU Ekpoma", "Ambrose Alli"], "https://aauekpoma.edu.ng/feed/", "rss"),
    ("TASUED", "Tai Solarin University of Education", ["TASUED", "Tai Solarin"], "https://tasued.edu.ng/feed/", "rss"),
    ("COVENANT", "Covenant University", ["Covenant University"], "https://covenantuniversity.edu.ng/", "html"),
    ("BABCOCK", "Babcock University", ["Babcock"], "https://babcock.edu.ng/news/", "html"),
    ("ABUAD", "Afe Babalola University", ["ABUAD", "Afe Babalola"], "https://abuad.edu.ng/feed/", "rss"),
    ("BOWEN", "Bowen University", ["Bowen University"], "https://bowen.edu.ng/feed/", "rss"),
    ("BELLS", "Bells University of Technology", ["Bells University"], "https://bellsuniversity.edu.ng/feed/", "rss"),
    ("LCU", "Lead City University", ["Lead City"], "https://lcu.edu.ng/", "html"),
    ("NILE", "Nile University of Nigeria", ["Nile University"], "https://nileuniversity.edu.ng/feed/", "rss"),
    ("IUO", "Igbinedion University Okada", ["Igbinedion"], "https://iuokada.edu.ng/feed/", "rss"),
    # no reachable site – matched from outlets / Google News only
    ("FUTA", "Federal University of Technology Akure", ["FUTA", "FUT Akure"], None, None),
    ("MAUTECH", "Modibbo Adama University Yola", ["MAUTECH", "Modibbo Adama"], None, None),
    ("FUOYE", "Federal University Oye-Ekiti", ["FUOYE", "Oye-Ekiti"], None, None),
    ("KWASU", "Kwara State University", ["KWASU", "Kwara State University"], None, None),
    ("ESUT", "Enugu State University of Science and Technology", ["ESUT"], None, None),
    ("OOU", "Olabisi Onabanjo University", ["OOU", "Olabisi Onabanjo"], None, None),
    ("PAU", "Pan-Atlantic University", ["Pan-Atlantic", "Pan Atlantic"], None, None),
    ("LMU", "Landmark University", ["Landmark University"], None, None),
    ("RUN", "Redeemer's University", ["Redeemer's University", "Redeemers University"], None, None),
    ("UNIZIK", "Nnamdi Azikiwe University", ["Awka varsity"], None, None),
]
BODIES = [  # regulators / official bodies (tier official, no school code)
    ("JAMB", "https://jamb.gov.ng/news/", "html"),
    ("NUC", "https://nuc.edu.ng/feed/", "rss"),
    ("TETFund", "https://tetfund.gov.ng/news/", "html"),
    ("Federal Ministry of Education", "https://education.gov.ng/feed/", "rss"),
    ("NYSC", "https://www.nysc.gov.ng/", "html"),
    ("ASUU", "https://asuu.org.ng/news/", "html"),
]
OUTLETS = [  # education desks (tier press) – filtered by education keywords
    ("Premium Times", "https://www.premiumtimesng.com/category/news/education/feed"),
    ("Punch", "https://punchng.com/topics/education/feed/"),
    ("Vanguard", "https://www.vanguardngr.com/category/education/feed/"),
    ("Daily Trust", "https://dailytrust.com/topics/education/feed/"),
    ("Nigerian Tribune", "https://tribuneonlineng.com/category/education/feed/"),
    ("EduCeleb", "https://educeleb.com/feed/"),
]
GN = "https://news.google.com/rss/search?q={q}+when:7d&hl=en-NG&gl=NG&ceid=NG:en"
GOOGLE_NEWS = [GN.format(q=q) for q in [
    "%22post-UTME%22+OR+%22post+UTME%22+Nigeria", "%22admission+list%22+university+Nigeria",
    "ASUU+OR+%22academic+calendar%22+university+Nigeria", "%22school+fees%22+OR+convocation+OR+matriculation+university+Nigeria",
    "JAMB+OR+NUC+OR+TETFund+OR+%22Federal+Scholarship+Board%22",
]]
TECH = [
    ("TechCabal", "https://techcabal.com/feed/"), ("Technext", "https://technext24.com/feed/"), ("Nairametrics Tech", "https://nairametrics.com/category/tech-news/feed/"),
    ("TechCrunch", "https://techcrunch.com/feed/"), ("The Verge", "https://www.theverge.com/rss/index.xml"), ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ("Wired", "https://www.wired.com/feed/rss"), ("Engadget", "https://www.engadget.com/rss.xml"), ("BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("MIT Technology Review", "https://www.technologyreview.com/feed/"),
    # China (English-language)
    ("SCMP Tech", "https://www.scmp.com/rss/36/feed"), ("TechNode", "https://technode.com/feed/"), ("Pandaily", "https://pandaily.com/feed/"),
    ("Google News · China Tech", "https://news.google.com/rss/search?q=China+technology+OR+Huawei+OR+BYD+OR+DeepSeek+OR+Xiaomi+when:3d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News · AI & Robots", "https://news.google.com/rss/search?q=%28artificial+intelligence+OR+robots+OR+humanoid%29+%28jobs+OR+education+OR+economy%29+when:3d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News · Phones", "https://news.google.com/rss/search?q=smartphone+launch+OR+iPhone+OR+Samsung+OR+Tecno+OR+Infinix+when:3d&hl=en-NG&gl=NG&ceid=NG:en"),
    ("Google News · Chip investment", "https://news.google.com/rss/search?q=government+%28investment+OR+subsidy+OR+funding%29+%28semiconductor+OR+chips+OR+electronics+OR+AI%29+when:7d&hl=en-US&gl=US&ceid=US:en"),
    ("Google News · Tech Africa", "https://news.google.com/rss/search?q=technology+startup+Nigeria+OR+Africa+when:3d&hl=en-NG&gl=NG&ceid=NG:en"),
]

# Tech Updates keep ONLY these topics (robots, AI, phones, government investment in electronics/chips, and their impact)
TECH_RE = re.compile(
    r"\brobot|humanoid|drone|automation|\bAI\b|artificial intelligence|machine learning|deep ?learning|LLM|chatbot|ChatGPT|OpenAI|Gemini|DeepSeek|Copilot|neural|"
    r"smartphone|\bphones?\b|iPhone|Android|Samsung Galaxy|Pixel|Huawei|Xiaomi|Tecno|Infinix|Transsion|5G|6G|"
    r"semiconductor|\bchips?\b|chipmaker|TSMC|Nvidia|Intel|Qualcomm|AMD|foundry|"
    r"government (invest|fund|grant|subsid|polic|ban|regulat)|\bFG\b.*(tech|AI|digital)|ministry of (communications|innovation|science|digital)|"
    r"(invest|funding|subsid|stimulus|incentive|tariff|export control|sanction|CHIPS Act).*(electronic|semiconductor|chip|AI|robot|phone|tech)|"
    r"(electronic|semiconductor|chip|AI|robot|phone|tech).*(invest|funding|subsid|stimulus|incentive|tariff|export control|sanction|CHIPS Act)|"
    r"data cent(er|re)|digital economy|"
    r"(AI|robot|automation|technology).*(jobs?|employment|workers|education|students|school|teachers|economy|society|health)|"
    r"(jobs?|employment|workers|education|students|economy|society).*(AI|robot|automation)", re.I)
EDU_RE = re.compile(r"universit|polytechnic|college|campus|student|undergrad|postgrad|admission|post-?utme|jamb|utme|waec|neco|asuu|nasu|ssanu|"
                    r"vice.?chancellor|convocation|matriculation|lecturer|tuition|school fees|academic calendar|semester|tetfund|nuc\b|scholarship|bursary|nysc", re.I)
KIND_RULES = [
    ("admission", re.compile(r"admission|post-?utme|screening|cut.?off|jamb|direct entry|caps\b", re.I)),
    ("scholarship", re.compile(r"scholarship|bursar|grant|award(ed)? to students|fellowship", re.I)),
    ("fees", re.compile(r"school fees|tuition|fee (hike|increase|payment)|charges", re.I)),
    ("calendar", re.compile(r"academic calendar|resumption|resume|semester|registration (deadline|closes|opens)|exam(ination)?s? (timetable|start|begin)|lecture[s]? (begin|resume)", re.I)),
    ("notice", re.compile(r"strike|asuu|nasu|ssanu|shut|closure|suspend|protest|warning|notice|ultimatum", re.I)),
    ("convocation", re.compile(r"convocation|matriculation|graduat|inaugural lecture", re.I)),
]
NOISE_TITLE = re.compile(r"download|installer|template|manual|usage|browser for|click here|read more|home page|login|portal link", re.I)
SKIP_LINK = re.compile(r"login|sign.?in|privacy|cookie|contact|about|faq|search|category|tag/|author/|#|\.(pdf|jpg|png|docx?)$|facebook|twitter|instagram|youtube|whatsapp", re.I)
UTC = timezone.utc


def clean(t):
    t = html.unescape(re.sub(r"<[^>]+>", " ", t or ""))
    return re.sub(r"\s+", " ", t).strip()


def nid(url):
    return "n_" + hashlib.sha1(url.encode()).hexdigest()[:16]


def parse_date(s):
    try:
        d = dparser.parse(s, fuzzy=True)
        if not d.tzinfo: d = d.replace(tzinfo=UTC)
        return d.astimezone(UTC)
    except Exception:
        return None


def kind_of(text):
    for k, rx in KIND_RULES:
        if rx.search(text): return k
    return "news"


_ALIASES = []
for code, name, aliases, _, _ in SCHOOLS:
    for a in set(aliases + [name]):
        _ALIASES.append((re.compile(r"(?<![A-Za-z])" + re.escape(a.strip()) + r"(?![A-Za-z])", re.I), code, name))
_ALIASES.sort(key=lambda t: -len(t[0].pattern))  # longest alias first
def match_school(text):
    for rx, code, name in _ALIASES:
        if rx.search(text): return code, name
    return None, None


def get(url):
    r = requests.get(url, headers=UA, timeout=(8, 20))
    if r.status_code in (403, 429, 503):
        r = requests.get(url, headers={**UA, "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"}, timeout=(8, 20))
    r.raise_for_status()
    return r


def article_summary(url):
    """Opens an article and returns the first ~600 chars of its main text (best effort)."""
    try:
        r = get(url)
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "nav", "header", "footer", "aside", "form"]): t.decompose()
        og = soup.find("meta", property="og:description")
        if og and og.get("content") and len(og["content"]) > 80: return clean(og["content"])[:600]
        main = soup.find("article") or soup.find("main") or soup.body or soup
        paras = [clean(p.get_text(" ")) for p in main.find_all("p")]
        paras = [p for p in paras if len(p) > 60]
        return " ".join(paras)[:600]
    except Exception:
        return ""


def from_rss(url, source):
    out = []
    f = feedparser.parse(get(url).content)
    for e in f.entries[:25]:
        link = e.get("link") or ""
        title = clean(e.get("title"))
        if not link or len(title) < 10: continue
        summ = clean(e.get("summary") or (e.get("content") or [{}])[0].get("value", ""))
        pub = parse_date(e.get("published") or e.get("updated") or "")
        src = source
        if "news.google.com" in url:  # Google News: real publisher is in <source>
            try: src = e.source.title
            except Exception: pass
            title = re.sub(r"\s+-\s+[^-]+$", "", title)  # strip " - Publisher"
        row = {"title": title, "url": link, "summary": summ[:600], "published": pub, "source": src}
        try:
            from media import _entry_images
            imgs = _entry_images(e)
            if imgs: row["_entry_imgs"] = imgs[:4]
        except Exception: pass
        out.append(row)
    return out


def from_html(url, source):
    """Generic news-page scraper: article-looking links with a date nearby if possible."""
    r = get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "nav", "footer"]): t.decompose()
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        title = clean(a.get_text(" "))
        href = urljoin(url, a["href"]).split("#")[0]
        if len(title) < 25 or len(title) > 200 or SKIP_LINK.search(href) or NOISE_TITLE.search(title) or href in seen: continue
        if urlparse(href).netloc.replace("www.", "") != urlparse(url).netloc.replace("www.", ""): continue
        if href.rstrip("/") == url.rstrip("/"): continue
        # menu / section pages are not news: "College_of_MS.php", "/home/non-academic-staff/", "/faculties/..."
        path = urlparse(href).path.lower()
        if re.search(r"/(faculty|faculties|college|colleges|department|departments|school|schools|staff|about|contact|admission|admissions|programmes?|courses?|portal|login|gallery|downloads?|library|alumni|units?|centres?|centers?|directorates?|institutes?)(/|\.|$)", path) and not re.search(r"\d{4}|news|press|bulletin|announce", path): continue
        if path.count("/") <= 1 and not re.search(r"\d", path) and len(path) < 30: continue   # top-level section link
        seen.add(href)
        # try to find a date in the surrounding block
        blk = a.find_parent(["article", "li", "div"]) or a
        pub = None
        tm = blk.find("time")
        if tm: pub = parse_date(tm.get("datetime") or tm.get_text())
        if not pub:
            m = re.search(r"\b(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})\b", blk.get_text(" "))
            if m: pub = parse_date(m.group(1))
        summ = ""
        p = blk.find("p")
        if p: summ = clean(p.get_text(" "))[:600]
        out.append({"title": title, "url": href, "summary": summ, "published": pub, "source": source})
        if len(out) >= 25: break
    return out


def crawl_one(job):
    """job = (table, source, url, kind, tier, school_code, school_name, needs_edu_filter)"""
    table, source, url, kind, tier, scode, sname, edu_filter = job
    try:
        items = from_rss(url, source) if kind == "rss" else from_html(url, source)
    except Exception as e:
        log.warning("%s failed: %s", source, str(e)[:120]); return table, source, []
    now = datetime.now(UTC)
    rows = []
    for it in items:
        txt = it["title"] + " " + it["summary"]
        if edu_filter and not EDU_RE.search(txt): continue
        if table == "tech_news" and not TECH_RE.search(txt): continue
        if it["published"] and it["published"] < now - timedelta(days=MAX_AGE_DAYS[table]): continue
        code, name = (scode, sname) if scode else (match_school(txt) if table == "school_news" else (None, None))
        pub = it["published"]
        if pub and pub > now + timedelta(hours=12): pub = None   # event dates in the future are not publish dates
        row = {"id": nid(it["url"]), "title": it["title"][:220], "summary": it["summary"], "url": it["url"], "source": it["source"][:80], "tier": tier,
               "published": (pub or now).isoformat(), "last_seen": now.isoformat(), "_undated": pub is None}
        if table == "school_news":
            row.update({"school_code": code, "school": name, "kind": kind_of(txt)})
        rows.append(row)
    return table, source, rows


def main():
    t0 = time.time()
    jobs = []
    for code, name, _, url, kind in SCHOOLS:
        if url: jobs.append(("school_news", name, url, kind, "official", code, name, False))
    for name, url, kind in BODIES:
        jobs.append(("school_news", name, url, kind, "official", None, None, False))
    for name, url in OUTLETS:
        jobs.append(("school_news", name, url, "rss", "press", None, None, True))
    for i, url in enumerate(GOOGLE_NEWS):
        jobs.append(("school_news", "Google News", url, "rss", "press", None, None, True))
    for name, url in TECH:
        jobs.append(("tech_news", name, url, "rss", "press", None, None, False))

    results = {"school_news": [], "tech_news": []}
    with ThreadPoolExecutor(8) as ex:
        for fut in as_completed([ex.submit(crawl_one, j) for j in jobs]):
            table, source, rows = fut.result()
            log.info("%-28s %3d items", source, len(rows))
            results[table].extend(rows)

    for table, rows in results.items():
        # de-dupe by id, newest first; keep the official version when the same URL appears twice
        by_id = {}
        for r in sorted(rows, key=lambda r: (r["tier"] != "official", r["published"]), reverse=False):
            by_id.setdefault(r["id"], r)
        rows = list(by_id.values())
        if not rows: continue
        # which are new? (so first_seen stays at first insert and we can count new items)
        ids = [r["id"] for r in rows]
        existing = set()
        for i in range(0, len(ids), 200):
            res = SB.table(table).select("id").in_("id", ids[i:i + 200]).execute()
            existing |= {x["id"] for x in (res.data or [])}
        new_rows = [r for r in rows if r["id"] not in existing]
        entry_imgs = {r["id"]: r.pop("_entry_imgs", None) for r in rows}
        for r in rows:  # undated items keep the `published` of their first insert (otherwise they would float to the top every crawl)
            if r.pop("_undated", False) and r["id"] in existing: r.pop("published", None)
        # PostgREST needs identical keys within one batch -> upsert the two shapes separately
        for group in (lambda rs: [[r for r in rs if "published" in r], [r for r in rs if "published" not in r]])(rows):
            for i in range(0, len(group), 200):
                SB.table(table).upsert(group[i:i + 200], on_conflict="id").execute()
        cutoff = (datetime.now(UTC) - timedelta(days=KEEP_DAYS[table])).isoformat()
        SB.table(table).delete().lt("published", cutoff).execute()
        # fetch a summary for items that have none: newest first, up to ENRICH_PER_RUN per run (in parallel);
        # whatever is left is picked up by the next crawl, so after a day or two every item has a snippet
        need = SB.table(table).select("id,url").or_("summary.is.null,summary.eq.").order("published", desc=True).limit(ENRICH_PER_RUN).execute().data or []
        short = [r for r in rows if r["id"] in existing and 0 < len(r["summary"]) < 60][:20]
        todo = {r["id"]: r["url"] for r in need + short}
        fixed = 0
        with ThreadPoolExecutor(6) as ex:
            for rid, summ in zip(todo.keys(), ex.map(article_summary, todo.values())):
                if summ: SB.table(table).update({"summary": summ}).eq("id", rid).execute(); fixed += 1
        log.info("%s: %d items (%d new), %d summaries enriched", table, len(rows), len(new_rows), fixed)
        # pictures / school & publisher logos: new items now, older unchecked rows a batch per crawl
        try:
            from media import enrich, backfill
            entries = {rid: {"media_content": [{"url": u} for u in imgs]} for rid, imgs in entry_imgs.items() if imgs}
            enrich(SB, table, new_rows, entries=entries)
            backfill(SB, table, limit=int(os.environ.get("MEDIA_BACKFILL", "150")))
        except Exception as e:
            log.warning("%s: media step failed: %s", table, e)
    log.info("done in %.0fs", time.time() - t0)


if __name__ == "__main__":
    main()
