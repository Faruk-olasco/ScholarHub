"""Fetches scholarship listings from configured sources and normalises them."""
import re, html, hashlib, logging
from datetime import datetime, timedelta, timezone
import feedparser, requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from dateutil import parser as dparser

log = logging.getLogger("scraper")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36 ScholarHub/1.0"

# (name, url, kind, tier)  tier: "official" = school/government, "aggregator" = news/blogs
DEFAULT_SOURCES = [
    # --- Government & university (official) ---
    ("UK Commonwealth Scholarship Commission", "https://cscuk.fcdo.gov.uk/scholarships/", "html", "official"),
    ("DAAD Germany", "https://www.daad.de/en/studying-in-germany/scholarships/", "html", "official"),
    ("Nuffic Netherlands", "https://www.nuffic.nl/en/subjects/scholarships", "html", "official"),
    ("Swedish Institute", "https://si.se/en/apply/scholarships/", "html", "official"),
    ("EduCanada (Government of Canada)", "https://www.educanada.ca/scholarships-bourses/non_can/index.aspx?lang=eng", "html", "official"),
    ("Study in Japan (MEXT)", "https://www.studyinjapan.go.jp/en/planning/scholarships/", "html", "official"),
    ("Erasmus+ (European Commission)", "https://erasmus-plus.ec.europa.eu/opportunities/opportunities-for-individuals/students/erasmus-mundus-joint-masters", "html", "official"),
    ("Australia Awards (DFAT)", "https://www.dfat.gov.au/people-to-people/australia-awards/australia-awards-scholarships", "html", "official"),
    ("Fulbright Program (US)", "https://www.fulbrightprogram.org/feed/", "rss", "official"),
    ("UK Government (GOV.UK)", "https://www.gov.uk/search/news-and-communications.atom?keywords=scholarship", "rss", "official"),
    ("University of Cambridge", "https://www.cam.ac.uk/news/feed", "rss", "official"),
    ("Nigeria PTDF", "https://ptdf.gov.ng/", "html", "official"),
    # --- Aggregators ---
    ("Opportunity Desk", "https://opportunitydesk.org/feed/", "rss", "aggregator"),
    ("Opportunities for Africans", "https://opportunitiesforafricans.com/feed/", "rss", "aggregator"),
    ("Opportunities Corners", "https://opportunitiescorners.com/feed/", "rss", "aggregator"),
    ("Scholarship Region", "https://www.scholarshipregion.com/feed/", "rss", "aggregator"),
    ("Scholarships Corner", "https://scholarshipscorner.website/feed/", "rss", "aggregator"),
    ("Scholarship Roar", "https://www.scholarshiproar.com/feed/", "rss", "aggregator"),
    ("Mladiinfo", "https://www.mladiinfo.eu/feed/", "rss", "aggregator"),
    ("Opportunity Portal", "https://www.opportunityportal.info/feed/", "rss", "aggregator"),
    ("FundsforNGOs", "https://www.fundsforngos.org/feed/", "rss", "aggregator"),
    ("Youth Opportunities Hub", "https://www.youthopportunitieshub.com/feed/", "rss", "aggregator"),
    ("OYAOP", "https://www.oyaop.com/feed/", "rss", "aggregator"),
    ("Opportunities Circle", "https://www.opportunitiescircle.com/feed/", "rss", "aggregator"),
    ("GreatYop", "https://greatyop.com/feed/", "rss", "aggregator"),
    ("Study Abroad Nations", "https://www.studyabroadnations.com/feed/", "rss", "aggregator"),
    ("Nigeria NUC", "https://www.nuc.edu.ng/feed/", "rss", "official"),
    ("South Africa Government", "https://www.gov.za/rss.xml", "rss", "official"),
    ("Gates Cambridge", "https://www.gatescambridge.org/", "html", "official"),
    ("Türkiye Bursları", "https://www.turkiyeburslari.gov.tr/", "html", "official"),
    ("Study in Australia (Gov)", "https://www.studyaustralia.gov.au/en/plan-your-studies/scholarships", "html", "official"),
    ("ScholarshipsAds", "https://www.scholarshipsads.com/", "html", "aggregator"),
    ("WeMakeScholars", "https://www.wemakescholars.com/", "html", "aggregator"),
    ("Studyportals", "https://www.studyportals.com", "html", "aggregator"),
]


LEVELS = {
    "phd": ["phd", "doctoral", "doctorate"],
    "masters": ["master", "msc", "mba", "graduate", "postgraduate"],
    "undergraduate": ["undergraduate", "bachelor", "bsc"],
    "postdoc": ["postdoc", "post-doctoral", "postdoctoral"],
    "fellowship": ["fellowship", "fellow"],
    "research": ["research grant", "research"],
    "short course": ["summer school", "short course", "training", "workshop", "bootcamp"],
}
REGIONS = {
    "Africa": ["Nigeria", "Ghana", "Kenya", "South Africa", "Rwanda", "Ethiopia", "Egypt", "Morocco", "Uganda", "Tanzania", "Cameroon",
               "Senegal", "Zambia", "Zimbabwe", "Botswana", "Namibia", "Malawi", "Mozambique", "Algeria", "Tunisia", "Sudan", "Africa", "African"],
    "Europe": ["UK", "United Kingdom", "Germany", "France", "Netherlands", "Sweden", "Norway", "Denmark", "Finland", "Switzerland", "Italy",
               "Spain", "Belgium", "Austria", "Ireland", "Hungary", "Poland", "Czech", "Portugal", "Turkey", "Russia", "Greece", "Romania",
               "Estonia", "Latvia", "Lithuania", "Slovakia", "Slovenia", "Croatia", "Luxembourg", "Iceland", "Europe", "European", "Erasmus", "Scotland", "England", "Wales"],
    "North America": ["USA", "United States", "U.S.", "America", "Canada", "Mexico", "North America"],
    "Asia": ["Japan", "China", "Korea", "Singapore", "India", "Malaysia", "Taiwan", "Hong Kong", "Thailand", "Indonesia", "Pakistan",
             "Bangladesh", "Vietnam", "Philippines", "Kazakhstan", "Brunei", "Sri Lanka", "Nepal", "Asia", "Asian"],
    "Middle East": ["Qatar", "UAE", "Saudi", "Kuwait", "Oman", "Bahrain", "Jordan", "Lebanon", "Israel", "Iran", "Middle East", "Gulf"],
    "Oceania": ["Australia", "New Zealand", "Fiji", "Pacific", "Oceania"],
    "Latin America": ["Brazil", "Argentina", "Chile", "Colombia", "Peru", "Latin America", "Caribbean", "Jamaica", "Cuba"],
}
COUNTRIES = sorted({c for v in REGIONS.values() for c in v if c not in ("African", "Asian", "European", "Erasmus", "Gulf", "U.S.", "America")})
FIELDS = {
    "STEM": ["engineering", "science", "technology", "math", "computer", "data", "ai ", "physics", "chemistry"],
    "Health": ["health", "medical", "medicine", "nursing", "public health"],
    "Business": ["business", "mba", "entrepreneur", "finance", "economics"],
    "Arts & Humanities": ["arts", "humanities", "journalism", "media", "design", "writing"],
    "Social Sciences": ["social", "policy", "law", "development", "leadership", "human rights"],
    "Environment": ["climate", "environment", "sustainab", "agricultur", "energy"],
}
FUNDING = {"fully funded": ["fully funded", "fully-funded", "full scholarship", "full funding"],
           "partially funded": ["partial", "tuition waiver", "stipend"]}

MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_FORMS = [
    rf"\d{{1,2}}(?:st|nd|rd|th)?\s*(?:of\s+)?{MONTH},?\s*\d{{4}}",     # 31 October 2026 / 31st of Oct, 2026
    rf"{MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s*\d{{4}}",              # October 31, 2026
    r"\d{1,2}[/.-]\d{1,2}[/.-]\d{4}",                                 # 31/10/2026
    r"\d{4}-\d{2}-\d{2}",                                             # 2026-10-31
    rf"\d{{1,2}}(?:st|nd|rd|th)?\s*{MONTH}(?!\s*\d{{4}})",            # 31 October (no year)
    rf"{MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?!,?\s*\d{{4}})",          # October 31 (no year)
]
STRONG_CUE = r"(?:application\s+)?(?:deadlines?|closing\s+date|closes?\s+on|close\s+on|will\s+close|applications?\s+close|due\s+date|apply\s+(?:by|before|until)|submit\s+(?:by|before)|last\s+date|not\s+later\s+than|no\s+later\s+than|closing)"
WEAK_CUE = r"(?:due|until|by)"
GAP = r"[^.!?\n]{0,90}?"
DATE_ALT = "(" + "|".join(DATE_FORMS) + r")(?!\s*\d)"      # (?!\s*\d) stops "September 20" matching inside "September 2027"
DEADLINE_RES = [re.compile(rf"\b{STRONG_CUE}{GAP}{DATE_ALT}", re.I), re.compile(rf"\b{WEAK_CUE}\s+{DATE_ALT}", re.I)]
ONGOING_RE = re.compile(r"deadline[^.\n]{0,20}(ongoing|rolling|open all year|varies|not specified)", re.I)


def extract_deadline(text):
    """Find the most plausible application deadline. Prefers dates that follow a cue word; returns ISO date or None."""
    now = datetime.now()
    candidates = []
    for rx in DEADLINE_RES:
        if candidates:  # strong cues found -> ignore weak ones
            break
        for m in rx.finditer(text[:60000]):
            raw = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", m.group(1)).replace(" of ", " ")
            try:
                d = dparser.parse(raw, fuzzy=True, dayfirst="/" in raw or "." in raw, default=now.replace(day=1))
            except Exception:
                continue
            if not re.search(r"\d{4}", raw) and d < now - timedelta(days=30):   # yearless date already passed -> next year
                d = d.replace(year=d.year + 1)
            if now - timedelta(days=365) < d < now + timedelta(days=730):
                candidates.append(d)
    if not candidates:
        return None
    future = [d for d in candidates if d >= now - timedelta(days=1)]
    return (min(future) if future else max(candidates)).date().isoformat()


def clean(text):
    return re.sub(r"\s+", " ", BeautifulSoup(html.unescape(text or ""), "html.parser").get_text(" ")).strip()


def find_any(text, mapping):
    t = text.lower()
    return [k for k, kws in mapping.items() if any(kw in t for kw in kws)]




TITLE_POS = re.compile(r"scholarship|fellowship|grant|bursar|studentship|fully.funded|funded|award|internship|exchange program|summer school|competition|challenge|contest|prize|traineeship|phd position|doctoral|postdoc", re.I)
# news about scholarships (not opportunities): someone received / donated / celebrated
NEWS_NEG = re.compile(r"\b(receives?|received|receiving|recipients?|awarded|awards?\s+(?:\$|\d|presented|go\s+to)|presents?|presented|donat\w*|gift|raises?|raised|"
                      r"honou?rs?|honored|celebrat\w*|names?\s+\w+\s+(?:scholars?|winners?)|named|selected\s+as|wins?|won|graduates\s+(?:with|from|under)|finishes|completes|"
                      r"launch\w*\s+(?:in\s+)?(?:memory|honou?r)|in\s+memory|memorial\s+fund|endow\w*|golf|gala|banquet|dinner|fundrais\w*|selfie|contest\s+\(|"
                      r"\bpays?\s+tribute|thank|congratulat\w*|gather\w*|conference|strengthening|reflect\w*|alumn\w*\s+(?:creates?|establish)|establish\w*\s+(?:a\s+)?scholarship\s+(?:in|to\s+honou?r))\b", re.I)
APPLY_POS = re.compile(r"\b(apply|applications?|call\s+for|now\s+open|open\s+for|deadline|eligib\w*|how\s+to|fully.?funded|funded|"
                       r"2026|2027|2028|scholarships?\s+for|fellowships?\s+for|for\s+(?:international|african|nigerian|women|developing)|"
                       r"opportunit\w*|program(?:me)?s?\b|announce\w*\s+(?:new\s+)?(?:scholarship|fellowship|programme|program)|offers?|available|opens?\b)\b", re.I)


LISTICLE_RE = re.compile(r"^\s*(top|best|list of|\d{2,}\+?\s+\w*\s*scholarships|\d+\s+(best|top|fully))|"
                         r"\b\d{2,4}\+?\s+(scholarships|opportunities|grants|fellowships)\b|\b(scholarships|opportunities)\s+\d{2,4}\+|scholarships?\s+(list|database|search|finder|directory)|"
                         r"\b(a-z|round-?up|guide to|everything you need|complete list|all scholarships|scholarships (in|for) \w+ \d{4}\s*[-–|]\s*\w+\.(com|org|net))", re.I)
SMALL = {"a","an","the","and","or","of","in","on","at","to","for","by","with","from","as","vs","via","de","la","du","des"}


def clean_title(t):
    """Normalise scraped titles: strip site suffixes/trailing junk, fix all-lowercase / ALL CAPS."""
    t = re.sub(r"\s+", " ", t).strip(" -–|:·»")
    t = re.sub(r"\s*[-–|]\s*[\w.&' ]{2,40}\.(com|org|net|edu|info|website|co\.\w+)\s*$", "", t, flags=re.I)  # " - site.com"
    t = re.sub(r"\s*[|»]\s*[^|»]{2,40}$", "", t)                                                              # " | Site Name"
    t = t.strip(" -–|:·")
    letters = re.sub(r"[^A-Za-z]", "", t)
    if letters and (sum(ch.isupper() for ch in letters) / len(letters) < 0.08 or (t == t.upper() and len(t) > 12)):
        words = t.lower().split()
        t = " ".join(w if (i and w in SMALL) else ({"phd":"PhD","msc":"MSc","bsc":"BSc"}.get(w) or (w.upper() if w in ("mba","uk","usa","eu","un","ai") else w.capitalize())) for i, w in enumerate(words))
    return t[:300]


def is_applyable(title, body=""):
    """Stricter gate for web-search results: is this an announcement students can act on?"""
    t = title.strip()
    if NEWS_NEG.search(t) or LISTICLE_RE.search(t):
        return False
    if TITLE_NEG.search(t):
        return False
    if not TITLE_POS.search(t):
        return False
    return bool(APPLY_POS.search(t) or APPLY_POS.search(body[:300]))


TITLE_NEG = re.compile(r"\bsample\b|how to|tips|guide|story|stories|interview|profile|alumni|webinar|recap|announced|winners?|awarded|awardees|recipients|congratulat|reflection|experience|journey|proposal template|what is|why you", re.I)


def is_scholarship_like(title, body):
    """Keep only actual opportunities (things you can apply to), drop news/articles/templates."""
    if TITLE_NEG.search(title):
        return False
    if TITLE_POS.search(title):
        return True
    # fall back to body only if it talks about applying
    return bool(re.search(r"(apply|application|eligib)", body[:800], re.I) and re.search(r"scholarship|fellowship|grant|funded", body[:800], re.I))


_gn_cache = {}
BAD_HOSTS = re.compile(r"googleusercontent\.com|gstatic\.com|google\.com/(?!url)|news\.google\.com|ggpht\.com", re.I)


def is_good_url(u):
    """A URL we are willing to store/show: http(s), not a Google asset, not an image."""
    if not u or not u.startswith("http"): return False
    if BAD_HOSTS.search(u): return False
    if re.search(r"\.(png|jpe?g|gif|webp|svg|ico)(\?|$)", u, re.I): return False
    return True


def resolve_link(link):
    """Decode a Google News RSS link into the real article URL (via Google's batchexecute endpoint).
    Returns the decoded URL, or None if it cannot be resolved."""
    if "news.google.com" not in link:
        return link if is_good_url(link) else None
    if link in _gn_cache:
        return _gn_cache[link]
    out = None
    try:
        import json as _json
        m = re.search(r"/(?:articles|read)/([^/?]+)", link)
        if m:
            gid = m.group(1)
            r = _session.get(f"https://news.google.com/articles/{gid}", headers=BROWSER_HEADERS, timeout=(5, 15))
            sig = re.search(r'data-n-a-sg="([^"]+)"', r.text); ts = re.search(r'data-n-a-ts="([^"]+)"', r.text)
            if sig and ts:
                req = [["Fbv4je", _json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
                        "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0], gid, ts.group(1), sig.group(1)]), None, "generic"]]
                resp = _session.post("https://news.google.com/_/DotsSplashUi/data/batchexecute",
                                     headers={**BROWSER_HEADERS, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
                                     data={"f.req": _json.dumps([req])}, timeout=(5, 15))
                mm = re.search(r'\\"(https?://[^\\"]+)\\"', resp.text)
                if mm and is_good_url(mm.group(1)):
                    out = mm.group(1).split("?utm")[0]
    except Exception as e:
        log.debug("gnews decode failed: %s", e)
    _gn_cache[link] = out
    return out


def normalise(entry, source_name, fetch_full=False):
    title = clean_title(clean(entry.get("title")))
    link = entry.get("link", "")
    publisher, pub_domain = "", ""
    if source_name.startswith("Search:"):   # Google News
        if " - " in title:
            title, publisher = title.rsplit(" - ", 1)
        src = entry.get("source") or {}
        pub_domain = urlparse(src.get("href", "") if isinstance(src, dict) else "").netloc.replace("www.", "")
        publisher = clean(publisher) or pub_domain or "web"
        source_name = f"🔎 {publisher}"
        link = resolve_link(link)          # decode to the real article URL
        if not link:
            return None                    # never store an unresolved / image URL
    elif source_name.startswith("Web:"):     # Brave
        pub_domain = urlparse(link).netloc.replace("www.", "")
        publisher = pub_domain
        source_name = f"🔎 {pub_domain}"
    raw = ""
    if entry.get("content"):
        raw = entry["content"][0].get("value", "")
    raw = raw or entry.get("summary", "") or entry.get("description", "")
    body = clean(raw)
    if not title or not is_good_url(link) or not is_scholarship_like(title, body):
        return None
    if publisher and not is_applyable(title, body):   # search results: must be an actionable opportunity, not news about one
        return None
    text = title + " " + body
    published = None
    for k in ("published_parsed", "updated_parsed"):
        if entry.get(k):
            published = datetime(*entry[k][:6], tzinfo=timezone.utc).isoformat()
            break
    deadline = extract_deadline(text)
    found_links = {}
    if fetch_full and link.startswith("http") and (deadline is None or publisher):
        full, raw = page_fetch(link)
        if full:
            deadline = deadline or extract_deadline(full)
            text = text + " " + full
            if len(body) < 200: body = full[:600]
            from .discovery import official_links
            found_links = official_links(raw, urlparse(link).netloc.replace("www.", ""))
    countries = [c for c in COUNTRIES if re.search(r"\b" + re.escape(c) + r"\b", text, re.I)]
    regions = [r for r, kws in REGIONS.items() if any(re.search(r"\b" + re.escape(k) + r"\b", text, re.I) for k in kws)]
    levels = find_any(text, LEVELS)
    return {
        "id": hashlib.sha1((re.sub(r"\W+", " ", title.lower()).strip() if publisher else link).encode()).hexdigest()[:16],
        "title": title[:300],
        "url": link,
        "source": source_name,
        "summary": body[:600],
        "published": published or datetime.now(timezone.utc).isoformat(),
        "deadline": deadline,
        "countries": ", ".join(dict.fromkeys(countries))[:200],
        "regions": ", ".join(regions),
        "levels": ", ".join(levels[:3]),
        "fields": ", ".join(find_any(text, FIELDS)[:3]),
        "funding": (find_any(text, FUNDING) or [""])[0],
        "tier": "official" if (publisher and re.search(r"\.(edu|ac|gov|go|gouv)\b|university|universit|college|ministry|embassy|council", pub_domain or publisher, re.I)) else ("web" if publisher else "aggregator"),
        "content_hash": hashlib.md5(body.encode()).hexdigest(),
        "found_links": {**found_links, **({pub_domain: f"https://{pub_domain}"} if pub_domain and OFFICIAL_DOMAIN.search(pub_domain) else {})},
    }


from urllib.parse import urljoin, urlparse
OFFICIAL_DOMAIN = re.compile(r"\.(edu|ac|gov|go|gouv|govt)(\.[a-z]{2,3})?$|\b(university|universit|college|institute|ministry|embassy)\b", re.I)

LINK_RE = re.compile(r"scholarship|fellowship|bursar|grant|award|stipend|studentship|funded", re.I)
SKIP_RE = re.compile(r"login|sign.?in|privacy|cookie|contact|about|faq|search|filter|overview|how to apply|information for|host organisations|"
                     r"^find (a|an|your) |^all |^browse|^view all|^more |^read more|^scholarships? and fellowships?$|^scholarships?$|conference|gather|"
                     r"strengthening|celebrat|impact|alumni|news|blog|stories|#", re.I)


def conditional_get(url, etag=None, last_modified=None):
    """HTTP GET with If-None-Match / If-Modified-Since. Returns (response|None if 304, etag, last_modified)."""
    h = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
    if etag: h["If-None-Match"] = etag
    if last_modified: h["If-Modified-Since"] = last_modified
    r = requests.get(url, headers=h, timeout=20)
    if r.status_code == 304:
        return None, etag, last_modified
    r.raise_for_status()
    return r, r.headers.get("ETag"), r.headers.get("Last-Modified")


BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/", "Upgrade-Insecure-Requests": "1",
}
_session = requests.Session()


def page_fetch(url):
    """Returns (text, raw_html) of an article."""
    try:
        r = _session.get(url, headers=BROWSER_HEADERS, timeout=(5, 10))
        if r.status_code in (403, 429, 503) or len(r.text) < 2000:
            r2 = _session.get(url, headers={**BROWSER_HEADERS, "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"}, timeout=(5, 10))
            if len(r2.text) > len(r.text): r = r2
        raw = r.text
        soup = BeautifulSoup(raw, "html.parser")
        for t in soup(["script", "style", "nav", "header", "footer"]): t.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        return clean(main.get_text(" "))[:15000], raw
    except Exception:
        return "", ""


def page_text(url):
    try:
        r = _session.get(url, headers=BROWSER_HEADERS, timeout=(5, 10))
        if r.status_code in (403, 429, 503) or len(r.text) < 2000:  # bot wall / challenge page -> try Googlebot UA once
            r2 = _session.get(url, headers={**BROWSER_HEADERS, "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"}, timeout=(5, 10))
            if len(r2.text) > len(r.text): r = r2
        soup = BeautifulSoup(r.text, "html.parser")
        for t in soup(["script", "style", "nav", "header", "footer"]): t.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        return clean(main.get_text(" "))[:15000]
    except Exception:
        return ""


def harvest_html(html_text, base_url, source_name, known_urls=(), detail_limit=6):
    """Generic scraper for official pages: harvest scholarship-looking links, enrich a few new ones with detail text."""
    soup = BeautifulSoup(html_text, "html.parser")
    seen, items, fetched = set(), [], 0
    host = urlparse(base_url).netloc.replace("www.", "")
    for a in soup.find_all("a", href=True):
        text = clean(a.get_text(" "))
        href = urljoin(base_url, a["href"]).split("#")[0]
        if len(text) < 12 or len(text) > 160 or not LINK_RE.search(text) or SKIP_RE.search(text):
            continue
        if href in seen or href.rstrip("/") == base_url.rstrip("/") or not is_good_url(href) or "gravatar.com" in href:
            continue
        seen.add(href)
        body = ""
        if href not in known_urls and fetched < detail_limit:
            body = page_text(href); fetched += 1
        entry = {"title": text, "link": href, "summary": body or f"Official listing from {source_name} ({host}). Open the link for eligibility, benefits and deadline."}
        it = normalise(entry, source_name)
        if it:
            it["tier"] = "official"
            if body and ONGOING_RE.search(body): it["deadline_note"] = "rolling"
            items.append(it)
    return items


def fetch_source(name, url, kind="rss", etag=None, last_modified=None, known_urls=()):
    """Returns dict(items, error, changed, etag, last_modified)."""
    out = {"items": [], "error": None, "changed": False, "etag": etag, "last_modified": last_modified}
    try:
        r, out["etag"], out["last_modified"] = conditional_get(url, etag, last_modified)
        if r is None:  # 304 Not Modified – nothing changed, request cost ~0
            return out
        out["changed"] = True
        if kind == "rss":
            entries = feedparser.parse(r.content).entries
            out["items"] = [i for i in (normalise(e, name, fetch_full=e.get("link") not in known_urls) for e in entries) if i]
        elif kind == "brave":
            from .discovery import parse_brave
            entries = [{"title": t, "link": u, "summary": sn} for t, u, sn in parse_brave(r.text)]
            out["items"] = [i for i in (normalise(e, name, fetch_full=e["link"] not in known_urls) for e in entries) if i]
        else:
            out["items"] = harvest_html(r.text, url, name, known_urls)
        log.info("%s: %d items", name, len(out["items"]))
    except Exception as e:
        log.warning("%s failed: %s", name, e)
        out["error"] = str(e)[:200]
    return out
