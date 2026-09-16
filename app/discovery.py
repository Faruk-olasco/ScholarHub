"""Web-wide discovery layer.

1. QUERY sources: Google News RSS search across hundreds of rotating queries (country × level × field × language).
   Google indexes essentially every news / university / government site that publishes a scholarship announcement,
   so this is how we find opportunities on sites we have never heard of.
2. AUTO-DISCOVERY: every article we read is mined for outbound links to *.edu / *.ac.* / *.gov / *.go.* scholarship
   pages. Those domains are added as new HTML sources automatically, so the source list grows on its own.
"""
import itertools, re, random, logging
from urllib.parse import quote_plus, urlparse

log = logging.getLogger("discovery")

COUNTRIES = ["USA", "UK", "Canada", "Australia", "Germany", "France", "Netherlands", "Sweden", "Norway", "Denmark",
             "Finland", "Switzerland", "Italy", "Spain", "Belgium", "Austria", "Ireland", "Japan", "China", "South Korea",
             "Singapore", "Taiwan", "Hong Kong", "New Zealand", "Turkey", "Hungary", "Poland", "Czech Republic",
             "Portugal", "Russia", "India", "Malaysia", "Thailand", "Qatar", "UAE", "Saudi Arabia", "Egypt", "Morocco",
             "Nigeria", "Ghana", "Kenya", "South Africa", "Rwanda", "Ethiopia", "Brazil", "Mexico", "Argentina", "Chile",
             "Indonesia", "Pakistan", "Bangladesh", "Vietnam", "Philippines", "Europe", "Africa", "Asia", "Latin America"]
LEVELS = ["undergraduate", "masters", "PhD", "postdoctoral", "fellowship", "high school", "vocational", "MBA",
          "research grant", "summer school", "exchange program", "internship"]
FIELDS = ["engineering", "medicine", "computer science", "artificial intelligence", "law", "business", "agriculture",
          "climate", "public health", "economics", "education", "journalism", "arts", "nursing", "data science",
          "architecture", "social sciences", "women in STEM", "renewable energy", "mathematics", "physics"]
GENERIC = ["fully funded scholarship 2027", "fully funded scholarship 2026", "scholarship applications now open",
           "scholarship deadline extended", "government scholarship international students", "university announces scholarship",
           "scholarships for international students", "scholarship for African students", "scholarship for developing countries",
           "tuition free scholarship", "scholarship call for applications", "fellowship call for applications 2027",
           "bursary applications open", "studentship funded", "doctoral scholarship call", "erasmus mundus scholarship 2027",
           "scholarship for Nigerian students", "scholarship for women 2027", "scholarship for refugees", "disability scholarship",
           "sports scholarship international", "merit scholarship international students 2027", "need-based scholarship international",
           "scholarship without IELTS", "scholarship for online degree", "scholarship for teachers", "scholarship for journalists",
           "scholarship for entrepreneurs", "scholarship for artists", "scholarship for medical students international"]
LANGS = [("en-US", "US", "US:en"), ("en-GB", "GB", "GB:en"), ("en-NG", "NG", "NG:en"), ("en-IN", "IN", "IN:en"),
         ("en-ZA", "ZA", "ZA:en"), ("en-AU", "AU", "AU:en"), ("en-CA", "CA", "CA:en"), ("en-KE", "KE", "KE:en")]
FOREIGN = [("bourse d'études étudiants étrangers 2027", "fr", "FR", "FR:fr"), ("beca internacional 2027 convocatoria", "es-419", "MX", "MX:es-419"),
           ("Stipendium internationale Studierende 2027", "de", "DE", "DE:de"), ("bolsa de estudo internacional 2027", "pt-BR", "BR", "BR:pt-419"),
           ("منحة دراسية ممولة بالكامل 2027", "ar", "EG", "EG:ar"), ("borsa di studio studenti internazionali 2027", "it", "IT", "IT:it"),
           ("奨学金 留学生 2027 募集", "ja", "JP", "JP:ja"), ("장학금 외국인 유학생 2027", "ko", "KR", "KR:ko"), ("beasiswa luar negeri 2027", "id", "ID", "ID:id"),
           ("Türkiye bursları 2027 başvuru", "tr", "TR", "TR:tr")]


def brave(q):
    return f"https://search.brave.com/search?q={quote_plus(q)}&source=web"


def gnews(q, hl="en-US", gl="US", ceid="US:en"):
    return f"https://news.google.com/rss/search?q={quote_plus(q)}&hl={hl}&gl={gl}&ceid={ceid}"


def build_query_sources():
    """Returns list of (name, url, kind, tier) covering the whole search space. Rotated by the poller."""
    out = []
    for g in GENERIC:
        out.append((f"Search: {g}", gnews(g + " when:7d"), "rss", "search"))
    for c in COUNTRIES:
        out.append((f"Search: scholarship {c}", gnews(f"scholarship {c} international students when:14d"), "rss", "search"))
        out.append((f"Search: fully funded {c}", gnews(f'"fully funded" {c} 2027 when:30d'), "rss", "search"))
    for l in LEVELS:
        out.append((f"Search: {l} scholarship", gnews(f"{l} scholarship apply when:14d"), "rss", "search"))
    for f in FIELDS:
        out.append((f"Search: {f} scholarship", gnews(f"{f} scholarship international when:30d"), "rss", "search"))
    for c, l in itertools.product(["Nigeria", "Africa", "UK", "USA", "Canada", "Germany", "Japan", "China", "Australia", "Europe"],
                                  ["PhD", "masters", "undergraduate"]):
        out.append((f"Search: {l} {c}", gnews(f"{l} scholarship {c} when:30d"), "rss", "search"))
    for hl, gl, ceid in LANGS[1:]:
        out.append((f"Search: scholarships ({gl} edition)", gnews("scholarship apply deadline when:7d", hl, gl, ceid), "rss", "search"))
    for q, hl, gl, ceid in FOREIGN:
        out.append((f"Search: {q[:30]}", gnews(q + " when:14d"), "rss", "search"))
    # Brave web search: returns real URLs (so deadlines can be read) and covers pages that are not "news"
    brave_qs = GENERIC + [f"scholarship {c} international students 2027" for c in COUNTRIES] + \
               [f"{l} scholarship 2027 apply" for l in LEVELS] + [f"{f} scholarship 2027 international" for f in FIELDS] + \
               ["site:.edu scholarship international students 2027 apply", "site:.ac.uk scholarship international 2027",
                "site:.edu.au scholarship international 2027", "site:.ac.jp scholarship international 2027", "site:.edu.cn scholarship international 2027",
                "site:.ca scholarship international students 2027 university", "site:.gov scholarship international students",
                "site:.gov.ng scholarship 2027", "site:.edu.ng scholarship 2027", "site:.ac.za scholarship 2027", "site:.ac.ke scholarship 2027",
                "site:.edu.gh scholarship 2027", "site:.nl scholarship international 2027 university", "site:.de stipendium international students 2027",
                "site:.se scholarship international 2027", "site:.fr bourse étudiants internationaux 2027", "site:.it borsa di studio internazionali 2027"]
    for q in brave_qs:
        out.append((f"Web: {q}", brave(q), "brave", "search"))
    return out


def parse_brave(html_text):
    """Yield (title, url, snippet) from a Brave results page."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, "html.parser")
    seen = set()
    for a in soup.select("a[href^='http']"):
        href = a["href"].split("#")[0]
        host = urlparse(href).netloc
        if not host or "brave.com" in host or BLOCK.search(host) or href in seen:
            continue
        title = a.get_text(" ", strip=True)
        # Brave anchors read like "Site Name domain › path Actual Title" – keep the part after the breadcrumb
        if "›" in title:
            title = title.split("›")[-1]
            title = re.sub(r"^[\w.-]+\s+", "", title, count=1) if re.match(r"^[\w-]+(\.[\w-]+)*\s", title) else title
        title = title.strip(" -|")
        if len(title) < 15:
            continue
        seen.add(href)
        snippet_el = a.find_parent().find_next_sibling() if a.find_parent() else None
        snippet = snippet_el.get_text(" ", strip=True)[:500] if snippet_el else ""
        yield title[:200], href, snippet


# --------- auto-discovery of official sources from links ----------
OFFICIAL_HOST = re.compile(r"\.(edu|ac|gov|go|gouv|govt|edu\.[a-z]{2}|ac\.[a-z]{2}|gov\.[a-z]{2})(\.[a-z]{2})?$|"
                           r"\b(university|universit|college|institute|ministry|embassy|council|foundation|commission|daad|nuffic|fulbright|erasmus)\b", re.I)
SCHOL_PATH = re.compile(r"scholarship|fellowship|funding|bursar|financial-aid|award|grant|stipend|studentship|apply", re.I)
BLOCK = re.compile(r"google|facebook|twitter|x\.com|linkedin|youtube|instagram|whatsapp|telegram|t\.me|wikipedia|amazon|apple|"
                   r"pinterest|tiktok|reddit|medium\.com|wordpress|blogspot|feedburner|bit\.ly|doubleclick|cloudflare", re.I)


def official_links(html_text, base_host):
    """Extract candidate official scholarship pages linked from an article. Returns {domain: url}."""
    from bs4 import BeautifulSoup
    found = {}
    try:
        soup = BeautifulSoup(html_text, "html.parser")
    except Exception:
        return found
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            continue
        host = urlparse(href).netloc.lower().replace("www.", "")
        if not host or host == base_host or BLOCK.search(host):
            continue
        if OFFICIAL_HOST.search(host) and SCHOL_PATH.search(href):
            found.setdefault(host, href.split("#")[0].split("?")[0])
    return found
