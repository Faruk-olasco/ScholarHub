"""ScholarHub details reader - organises each listing into standard sections (scholarships AND jobs).

Runs after the crawlers (free GitHub Actions). For every listing that has no `details` yet it:
  1. reads the listing page itself: headings (h1-h6, bold-only paragraphs, "Heading:" lines) and the bullets /
     paragraphs under each heading, renamed to ScholarHub's standard section names;
  2. if that page is an aggregator (not the provider's own site) and sections are missing, follows the
     "official / apply / website" link and reads that page too (only fills what is still missing);
  3. if sections are still missing, classifies the page's own sentences ("applicants must...", "covers tuition...");
  4. last resort (page down / empty) - a Brave web search of the title, reading the best-matching result.
Nothing is ever invented: every bullet is text found on a page. Listings with no such sections keep an empty
details record so the app simply shows the summary.

Standard keys (fixed order in the app):
  scholarships: about, benefits, eligibility ("Who can apply"), documents, how_to_apply
  jobs:         about, responsibilities, requirements, benefits, how_to_apply
Row written: details = {"<key>": [bullets...] | "text", "src": url read, "at": iso}

Env: SUPABASE_URL, SUPABASE_SERVICE_KEY; optional DETAILS_PER_RUN (default 80), DETAILS_JOBS_PER_RUN (60),
     DETAILS_BRAVE (max Brave searches per run, default 3), DETAILS_REFRESH_DAYS (re-read empty records, default 21).
"""
import os, re, sys, json, time, logging, html as htmlmod
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urljoin, quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from dateutil import parser as dparser
from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("details")

SB = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Mobile Safari/537.36 ScholarHub/1.5",
      "Accept-Language": "en"}
TIMEOUT = (8, 20)
PER_RUN = int(os.environ.get("DETAILS_PER_RUN", "80"))
JOBS_PER_RUN = int(os.environ.get("DETAILS_JOBS_PER_RUN", "60"))
BRAVE_MAX = int(os.environ.get("DETAILS_BRAVE", "3"))
REFRESH_DAYS = int(os.environ.get("DETAILS_REFRESH_DAYS", "21"))
WORKERS = int(os.environ.get("DETAILS_WORKERS", "6"))
MAX_BULLETS = 8
MAX_BULLET_LEN = 240

# ---------- heading names -> standard keys ----------
HEAD = [
    ("how_to_apply", r"how to apply|application (process|procedure|method|instructions?|steps|guide|link)|method of application|mode of application|apply (now|here|online)|to apply|submission|how do i apply|application form"),
    ("documents", r"documents?|what to submit|required materials?|supporting (materials?|documents?)|attachments?|application (materials|package|requirements)|checklist"),
    ("benefits", r"benefits?|what you(?:'ll| will)? (get|receive|gain)|award|value|worth|covers|coverage|funding|financial|stipend|perks|package|what (the|this) .{0,30}(covers|offers|provides|includes)|scholarship (details|amount|includes)|salary|remuneration|compensation|we offer|what we offer|entitlements?"),
    ("eligibility", r"eligib|who (can|should|may|is eligible to) apply|criteria|qualif|candidates?|open to|target (group|audience|applicants?)|applicant profile|who we('re| are) looking for|ideal candidate|person specification|requirements?|skills|experience|competenc|minimum|must have|you (will )?(have|bring|need)|what we('re| are) looking for|about you"),
    ("responsibilities", r"responsib|duties|what you(?:'ll| will) do|key tasks|job (description|summary|purpose)|about the (role|job|position)|accountab|the role|your role|role (overview|summary|purpose)|key functions|scope of work|tasks"),
    ("deadline", r"deadline|closing date|last date|due date|applications? clos|closes? on|dates?$|timeline|important dates"),
    ("about", r"^about|overview|description|introduction|summary|background|the (scholarship|programme|program|fellowship|opportunity|company|organisation|organization|employer)|purpose|objectives?|^who we are|about us"),
]
# scholarships merge job-style keys into eligibility; jobs merge eligibility into requirements
MERGE = {
    "scholarships": {"responsibilities": None},                  # drop for scholarships
    "jobs": {"eligibility": "requirements"},
}
ORDER = {"scholarships": ["about", "benefits", "eligibility", "documents", "how_to_apply"],
         "jobs": ["about", "responsibilities", "requirements", "benefits", "how_to_apply"]}

JUNK = re.compile(r"share (this|on)|whatsapp|telegram|facebook|twitter|linkedin|instagram|subscribe|newsletter|join (our|us)|click here|read more|advertis|cookie|sign in|log ?in|related (posts?|articles?|jobs|opportunit)|you may also like|leave a (reply|comment)|comments?$|tags?:|categor(y|ies):|posted (by|on)|^by |all rights reserved|privacy policy|terms (of|and)|disclaimer|see also|previous|next post|sponsored|^home$|^menu$|follow us|download (our )?app|^\W*$", re.I)
BOARD_HOSTS = re.compile(r"hotnigerianjobs|jobzilla|myjobmag|jobsinnigeria|ngcareers|opportunitiesforafricans|opportunityshape|talk2samafrica|scholars4dev|opportunitydesk|scholarshipregion|afterschoolafrica|scholarshipair|weworkremotely|scholarshipscafe|scholarshipsads|oyaop|youthop|opportunitiescorners|scholarshiptab|mladiinfo|developmentaid|heysuccess|advance-africa|nairaland|jobberman|linkedin|indeed|glassdoor|google\.|facebook|twitter|t\.me|whatsapp|youtube|instagram", re.I)
OFFICIAL_LINK = re.compile(r"official (website|page|link|site|announcement|call)|apply (here|now|online|via)|application (link|portal|page|form)|visit (the )?(official|website|page)|more (information|details)|learn more|website|here$|^apply$|click here to apply|for more|source", re.I)
SENT = {
    "eligibility": re.compile(r"\b(must be|must have|should be|should have|applicants? (must|should|need)|candidates? (must|should|need)|open to|eligible|eligibility|is required|are required|required to|nationals? of|citizens? of|aged? (between|under|\d))\b", re.I),
    "benefits": re.compile(r"\b(stipend|tuition|allowance|worth|valued at|fully funded|full funding|per (month|year|annum)|airfare|flights?|accommodation|health insurance|salary|benefits? (include|package)|will receive (a|an|the)? ?(scholarship|grant|award|funding|bursary|\$|\u20ac|\u00a3|N\d))\b", re.I),
    "how_to_apply": re.compile(r"\b(to apply|apply (online|via|through|by)|application form|submit (your|an|the)|send (your|a|an)|applications? (should|must|can|may) be|interested (candidates|applicants|persons))\b", re.I),
    "responsibilities": re.compile(r"\b(will be responsible|responsible for|duties include|you will|the role (involves|includes)|lead|manage|coordinate|support the|assist (in|with)|prepare|develop and)\b", re.I),
    "requirements": re.compile(r"\b(must have|must be|should have|degree in|bachelor|master'?s|years? of experience|experience in|proficien|knowledge of|ability to|strong|excellent|fluen)\b", re.I),
}
_brave_used = [0]
_brave_last = [0.0]


# ---------- fetching ----------
def fetch(url):
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT, allow_redirects=True)
        ct = r.headers.get("content-type", "text/html")
        if r.status_code == 200 and ("html" in ct or "xml" in ct):
            if "charset" not in ct.lower():
                r.encoding = r.apparent_encoding or "utf-8"
            return r.text, r.url
    except Exception as e:
        log.debug("fetch %s: %s", url, e)
    return None, url


def clean(t):
    t = htmlmod.unescape(str(t or ""))
    t = re.sub(r"[\u200b\u00a0]", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" \t\r\n-\u2013\u2022\u25cf\u00b7*:;")
    return t


def heading_key(text):
    t = clean(text).lower()
    if not t or len(t) > 90:
        return None
    t = re.sub(r"[\W_]+$", "", t)
    for key, rx in HEAD:
        if re.search(rx, t):
            return key
    return None


def main_root(soup):
    """The element that holds the listing text: the biggest of the usual content containers (not a 'related posts' box)."""
    best, best_len = None, 0
    for sel in ["article", "main", "[itemprop=articleBody]", "[itemprop=description]", ".entry-content", ".post-content", ".td-post-content",
                ".job-description", ".job_description", ".description", "[class*=job__content]", "[class*=job-content]", "[class*=jobDescription]",
                "[class*=listing-container]", ".content", "#content", ".post", ".single"]:
        for el in soup.select(sel):
            n = len(el.get_text(" ", strip=True))
            if n > best_len:
                best, best_len = el, n
    if best is not None and best_len > 300:
        return best
    return soup.body or soup


def strip_noise(root):
    for sel in ["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "iframe", "svg", "button",
                ".share", ".sharedaddy", ".related", ".comments", "#comments", ".sidebar", ".widget", ".breadcrumb", ".tags", ".post-tags", ".jp-relatedposts", ".wp-block-buttons"]:
        for el in root.select(sel):
            el.decompose()


def is_heading(el):
    """True for real headings and for paragraphs that are only bold text / end with a colon (how most blogs write sections)."""
    if not isinstance(el, Tag):
        return False
    if el.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        return True
    if el.name in ("p", "div", "span", "strong", "b") and len(el.get_text(strip=True)) <= 90:
        txt = el.get_text(" ", strip=True)
        if not txt:
            return False
        inner = [c for c in el.children if not (isinstance(c, NavigableString) and not str(c).strip())]
        if len(inner) == 1 and isinstance(inner[0], Tag) and inner[0].name in ("strong", "b", "u", "em", "span", "font") and len(txt) < 80:
            return True
        if txt.endswith(":") and len(txt) < 70 and txt.count(" ") <= 7:
            return True
    return False


def bullets_from(el):
    """Bullets inside a block: list items; else sentences of a short paragraph."""
    out = []
    if el.name in ("ul", "ol"):
        for li in el.find_all("li", recursive=False) or el.find_all("li"):
            t = clean(li.get_text(" ", strip=True))
            a = li.find("a")
            if a and clean(a.get_text(" ", strip=True)) == t:
                continue                  # a bare link (menu / related-page list), not a fact
            if t:
                out.append(t)
    elif el.name == "table":
        for tr in el.find_all("tr"):
            if tr.find("td") is None:
                continue                  # header row
            cells = [clean(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            cells = [c for c in cells if c]
            if cells:
                out.append(": ".join(cells[:2]) if len(cells) >= 2 else cells[0])
    else:
        t = clean(el.get_text(" ", strip=True))
        if not t:
            return out
        # "Tuition, stipend and flights" style lines separated by <br> often arrive as one paragraph: split on sentence ends
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\u2022\-])", t) if len(t) > MAX_BULLET_LEN else [t]
        out.extend(p.strip() for p in parts if p.strip())
    return out


def good_bullet(b):
    if not b or len(b) < 3 or len(b) > 600:
        return False
    if JUNK.search(b):
        return False
    if re.fullmatch(r"[\W\d]+", b):
        return False
    if len(b) <= 50 and not re.search(r"\d", b) and heading_key(b):
        return False                      # a sub-heading ("Who is eligible?", "APPLY NOW"), not a fact
    if re.search(r"job alerts?|email address|unblock|browser|javascript", b, re.I):
        return False
    return True


def tidy(bullets):
    seen, out = set(), []
    for b in bullets:
        b = clean(b)
        if len(b) > MAX_BULLET_LEN:
            b = b[:MAX_BULLET_LEN - 1].rsplit(" ", 1)[0] + "\u2026"
        k = re.sub(r"\W+", "", b.lower())[:80]
        if good_bullet(b) and k not in seen:
            seen.add(k)
            out.append(b)
        if len(out) >= MAX_BULLETS:
            break
    return out


def read_sections(html, table):
    """Walk the content in document order; every heading opens a section; blocks until the next heading belong to it."""
    soup = BeautifulSoup(html, "html.parser")
    strip_noise(soup)
    root = main_root(soup)
    sections, deadline_txt = {}, None
    cur = None
    # flatten: consider block-level elements in order
    blocks = root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol", "table", "div", "li"], recursive=True)
    for el in blocks:
        if el.name in ("div", "li") and el.find(["p", "ul", "ol", "h2", "h3", "h4", "div"]):
            continue                      # container - its children come next
        if el.name == "li" and el.find_parent(["ul", "ol"]) is not None and not is_heading(el):
            continue                      # handled through its list
        if el.find_parent(["ul", "ol"]) is not None and el.name == "p" and not is_heading(el):
            continue
        if is_heading(el):
            txt = el.get_text(" ", strip=True)
            key = heading_key(txt)
            inline = ""
            # "Deadline: 15 November 2026" (value on the heading line) vs "HEC Scholarships 2027: Financial Benefits" (sub-heading)
            if ":" in txt and len(txt.split(":", 1)[1].strip()) > 2:
                left, right = txt.split(":", 1)
                kl, kr = heading_key(left), heading_key(right)
                if kr and not kl:
                    key = kr
                elif kl:
                    key = kl
                    if not kr and (kl == "deadline" or len(right.strip()) > 14):
                        inline = clean(right)
            cur = key
            if key == "deadline" and inline:
                deadline_txt = deadline_txt or inline
            elif key and inline and key != "about":
                sections.setdefault(key, []).append(inline)
            continue
        if not cur:
            continue
        bl = bullets_from(el)
        if not bl:
            continue
        if cur == "deadline":
            deadline_txt = deadline_txt or bl[0]
            continue
        sections.setdefault(cur, []).extend(bl)
        if cur == "about" and sum(len(x) for x in sections["about"]) > 500:
            cur = None
    # standardise keys for the table
    for k, to in MERGE[table].items():
        if k in sections:
            v = sections.pop(k)
            if to:
                sections[to] = sections.get(to, []) + v
    if table == "jobs" and "requirements" not in sections and "eligibility" in sections:
        sections["requirements"] = sections.pop("eligibility")
    out = {}
    for k in ORDER[table]:
        if k in sections:
            b = tidy(sections[k])
            if b:
                out[k] = " ".join(b)[:420] if k == "about" else b
    if deadline_txt:
        out["_deadline_txt"] = deadline_txt
    return out, soup


def sentence_fallback(soup, table, have):
    """Only for still-missing keys: sentences on the page that clearly belong to a section."""
    root = main_root(soup)
    text = clean(root.get_text(" ", strip=True))
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    keys = [k for k in ORDER[table] if k not in have and k != "about" and k in SENT]
    out = {}
    for k in keys:
        rx = SENT[k]
        hits = [s for s in sents if 25 <= len(s) <= 260 and rx.search(s)]
        b = tidy(hits)[:4]
        if b:
            out[k] = b
    return out


def official_link(soup, page_url, title):
    """Outbound link an aggregator points to (apply / official website), never social or another aggregator."""
    host = urlparse(page_url).netloc.lower()
    cands = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("http"):
            continue
        h = urlparse(href).netloc.lower()
        if not h or h.endswith(host) or host.endswith(h) or BOARD_HOSTS.search(h) or re.search(r"\.(pdf|jpg|png|docx?)$", href, re.I):
            continue
        txt = a.get_text(" ", strip=True)
        score = 0
        if OFFICIAL_LINK.search(txt):
            score += 3
        if re.search(r"\.(edu|ac\.[a-z]{2}|gov|org|int)(/|$)", h):
            score += 2
        if re.search(r"apply|application|admission|scholarship|fellowship|careers?|jobs?|vacanc", href, re.I):
            score += 1
        if score:
            cands.append((score, href))
    cands.sort(reverse=True)
    return cands[0][1] if cands else None


def brave_lookup(title):
    if _brave_used[0] >= BRAVE_MAX:
        return None
    wait = _brave_last[0] + 240 - time.time()
    if wait > 0:
        time.sleep(min(wait, 240))
    _brave_last[0] = time.time()
    _brave_used[0] += 1
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from app.discovery import parse_brave
        r = requests.get(f"https://search.brave.com/search?q={quote_plus(title)}&source=web", headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        want = set(re.findall(r"[a-z]{4,}", title.lower()))
        for t, u, _ in parse_brave(r.text):
            got = set(re.findall(r"[a-z]{4,}", t.lower()))
            if want and len(want & got) / len(want) >= 0.6 and not BOARD_HOSTS.search(urlparse(u).netloc):
                return u
    except Exception as e:
        log.debug("brave: %s", e)
    return None


def parse_deadline(txt):
    try:
        m = re.search(r"\d{1,2}(st|nd|rd|th)?\s+[A-Za-z]{3,9},?\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2}(st|nd|rd|th)?,?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}", txt)
        if not m:
            return None
        d = dparser.parse(re.sub(r"(\d)(st|nd|rd|th)", r"\1", m.group(0)), dayfirst=True, fuzzy=True).date()
        if d > datetime.now(timezone.utc).date() and d.year <= datetime.now().year + 2:
            return d.isoformat()
    except Exception:
        pass
    return None


def read_item(row, table):
    """Return (details dict, deadline or None)."""
    found, src, soup = {}, None, None
    html, final = fetch(row["url"])
    if html:
        found, soup = read_sections(html, table)
        src = final
    missing = [k for k in ORDER[table] if k not in found and k != "about"]
    # follow the official link from aggregators when sections are missing
    if soup is not None and row.get("tier") != "official" and len(missing) >= 2:
        link = official_link(soup, final, row["title"])
        if link:
            h2, f2 = fetch(link)
            if h2:
                more, soup2 = read_sections(h2, table)
                for k, v in more.items():
                    if k not in found:
                        found[k] = v
                if more and not src:
                    src = f2
                if sum(1 for k in more if k in ORDER[table]) >= 2:
                    src = f2
                    soup = soup2 if soup is None else soup
    # sentence classification on the page we have
    if soup is not None:
        missing = [k for k in ORDER[table] if k not in found]
        if len(missing) >= 3:
            for k, v in sentence_fallback(soup, table, found).items():
                found.setdefault(k, v)
    # last resort: search the title
    if not any(k in found for k in ORDER[table]):
        link = brave_lookup(row["title"])
        if link:
            h3, f3 = fetch(link)
            if h3:
                more, soup3 = read_sections(h3, table)
                for k, v in more.items():
                    found.setdefault(k, v)
                if more:
                    src = f3
                    for k, v in sentence_fallback(soup3, table, found).items():
                        found.setdefault(k, v)
    deadline = parse_deadline(found.pop("_deadline_txt", "") or "") if not row.get("deadline") else None
    used = set()
    for k in ORDER[table]:                # the same sentence never appears under two headings
        if isinstance(found.get(k), list):
            keep = []
            for b in found[k]:
                sig = re.sub(r"\W+", "", b.lower())[:80]
                if sig not in used:
                    used.add(sig)
                    keep.append(b)
            if keep:
                found[k] = keep
            else:
                found.pop(k)
    details = {k: found[k] for k in ORDER[table] if k in found}
    details["at"] = datetime.now(timezone.utc).isoformat()
    if src:
        details["src"] = src
    return details, deadline


def pick_rows(table, limit):
    """Rows without details first (newest first), then empty records older than REFRESH_DAYS."""
    today = datetime.now(timezone.utc).date().isoformat()
    q = SB.table(table).select("id,title,url,tier,deadline,details").is_("details", "null").order("first_seen", desc=True).limit(limit)
    try:
        q = q.or_(f"deadline.is.null,deadline.gte.{today}")
    except Exception:
        pass
    rows = q.execute().data
    if len(rows) < limit:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=REFRESH_DAYS)).isoformat()
        try:
            more = SB.table(table).select("id,title,url,tier,deadline,details").not_.is_("details", "null") \
                .lt("details->>at", cutoff).order("first_seen", desc=True).limit(limit * 3).execute().data
            more = [r for r in more if not any(k in (r.get("details") or {}) for k in ORDER[table])]
            rows += more[: limit - len(rows)]
        except Exception as e:
            log.debug("refresh query: %s", e)
    return rows


def run_table(table, limit):
    rows = pick_rows(table, limit)
    if not rows:
        log.info("%s: nothing to read", table)
        return 0
    log.info("%s: reading %d listings", table, len(rows))
    done = filled = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(read_item, r, table): r for r in rows}
        for f in as_completed(futs):
            r = futs[f]
            try:
                details, deadline = f.result()
            except Exception as e:
                log.warning("%s %s: %s", table, r["id"], e)
                details, deadline = {"at": datetime.now(timezone.utc).isoformat(), "err": str(e)[:80]}, None
            upd = {"details": details}
            if deadline:
                upd["deadline"] = deadline
            try:
                SB.table(table).update(upd).eq("id", r["id"]).execute()
                done += 1
                if any(k in details for k in ORDER[table]):
                    filled += 1
            except Exception as e:
                log.warning("update %s %s: %s", table, r["id"], e)
    log.info("%s: %d read, %d with organised sections", table, done, filled)
    return filled


def main():
    t0 = time.time()
    a = run_table("scholarships", PER_RUN)
    b = run_table("jobs", JOBS_PER_RUN)
    log.info("details done in %ds (scholarships %d, jobs %d, brave used %d)", time.time() - t0, a, b, _brave_used[0])


if __name__ == "__main__":
    main()
