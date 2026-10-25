"""
media.py — pictures and institution logos for scholarships, School News and Tech Updates.

Picture chain  (per item, stored in `image`):
  1. image carried inside the RSS entry (media:content / enclosure / <img> in the description)
  2. og:image / twitter:image of the article page
  3. largest real image inside the article body (lazy-load attributes understood)
  Stock/placeholder pictures (unsplash, pexels, generic theme images, tiny files) are rejected.

Logo chain  (per item, stored in `logo` + `org`, only when there is no picture):
  a. organisation named in the title / known provider list     -> CURATED -> Wikidata (by name)
  b. official / source domain                                   -> CURATED -> Wikidata (by official website)
  c. the website's own header logo (apple-touch-icon, <img class="logo">)
  Each lookup is cached in the `logos` table (key = lower-case name or root domain) and never repeated.

Public:
  find_image(url, entry=None, html=None) -> str | None
  logo_for(org_name=None, domain=None, SB=None) -> (name, url) | (None, None)
  org_from_title(title) -> str | None
  enrich(SB, table, rows)        : fills image/logo for the given freshly-inserted rows
  backfill(SB, table, limit=120) : fills older rows that were never checked (a batch per crawl)
"""
import os, re, io, json, time, struct, logging
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, quote
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup

log = logging.getLogger("media")
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Mobile Safari/537.36"}
WD_UA = {"User-Agent": "ScholarHub/1.4 (https://faruk-olasco.github.io/ScholarHub/; francoprinciple1@gmail.com)"}
TIMEOUT = 15

# ----------------------------------------------------------------------------- picture rules
BAD_IMG = re.compile(r"logo|icon|avatar|placeholder|default|blank|spinner|pixel|badge|favicon|wp-content/themes|emoji|advert|banner-ad|"
                     r"share|button|arrow|loading|gravatar|^data:|\.svg(\?|$)|\.gif(\?|$)|/flags?/|counter|tracking|1x1|spacer", re.I)
STOCK = re.compile(r"unsplash\.com|pexels\.com|pixabay\.com|shutterstock|istockphoto|gettyimages\.com/detail|stock\.adobe|freepik|"
                   r"placeholder\.com|via\.placeholder|dummyimage|picsum\.photos|loremflickr", re.I)
MIN_W, MIN_H = 300, 160


def _dims(url):
    """(width, height) from the first bytes of a PNG/JPEG/WebP; (0,0) if unreadable."""
    try:
        r = requests.get(url, headers={**UA, "Range": "bytes=0-131071"}, timeout=10, stream=True)
        ct = r.headers.get("content-type", "")
        if not (ct.startswith("image") or ct == "application/octet-stream" or ct == ""): return 0, 0
        b = r.raw.read(131072)
        if b[:8] == b"\x89PNG\r\n\x1a\n": return struct.unpack(">II", b[16:24])
        if b[:2] == b"\xff\xd8":
            i = 2
            while i < len(b) - 9:
                if b[i] != 0xFF: i += 1; continue
                m = b[i + 1]
                if m in (0xC0, 0xC1, 0xC2): h, w = struct.unpack(">HH", b[i + 5:i + 9]); return w, h
                i += 2 + struct.unpack(">H", b[i + 2:i + 4])[0]
        if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
            if b[12:16] == b"VP8 ": w, h = struct.unpack("<HH", b[26:30]); return w & 0x3FFF, h & 0x3FFF
            if b[12:16] == b"VP8L": bits = struct.unpack("<I", b[21:25])[0]; return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
            if b[12:16] == b"VP8X": return 1 + int.from_bytes(b[24:27], "little"), 1 + int.from_bytes(b[27:30], "little")
        if b[:12].find(b"ftypavif") >= 0: return 800, 450          # AVIF (The Verge etc.) – assume large
        return 0, 0
    except Exception:
        return 0, 0


def _ok_picture(url, w=0, h=0):
    if not url or not url.startswith("http") or BAD_IMG.search(url) or STOCK.search(url): return False
    if not w: w, h = _dims(url)
    return w >= MIN_W and h >= MIN_H and (w / max(h, 1)) < 4


def _entry_images(entry):
    """Image URLs inside an RSS/Atom entry (feedparser dict)."""
    out = []
    try:
        for m in (entry.get("media_content") or []) + (entry.get("media_thumbnail") or []):
            if m.get("url"): out.append(m["url"])
        for e in entry.get("enclosures") or entry.get("links") or []:
            if (e.get("type") or "").startswith("image") and e.get("href"): out.append(e["href"])
        html = ""
        if entry.get("content"): html = entry["content"][0].get("value", "")
        html = html or entry.get("summary", "") or entry.get("description", "")
        for m in re.finditer(r"<img[^>]+(?:data-src|src)=[\"']([^\"']+)", html or "", re.I): out.append(m.group(1))
    except Exception:
        pass
    return out


def _page_images(url, html):
    """Candidate pictures from an article page, best first."""
    soup = BeautifulSoup(html, "html.parser"); out = []
    for sel in ({"property": "og:image"}, {"property": "og:image:secure_url"}, {"name": "twitter:image"}, {"name": "twitter:image:src"}, {"itemprop": "image"}):
        m = soup.find("meta", attrs=sel)
        if m and m.get("content"): out.append(urljoin(url, m["content"].strip()))
    l = soup.find("link", rel="image_src")
    if l and l.get("href"): out.append(urljoin(url, l["href"]))
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "form"]): t.decompose()
    root = soup.find("article") or soup.find("main") or soup.find(attrs={"class": re.compile(r"entry-content|post-content|article|content-body|single|news-detail", re.I)}) or soup.body or soup
    for im in root.find_all("img"):
        u = im.get("data-src") or im.get("data-lazy-src") or im.get("data-original") or im.get("src") or ""
        ss = im.get("data-srcset") or im.get("srcset") or ""
        if ss and not u: u = ss.split(",")[-1].strip().split(" ")[0]
        if not u: continue
        w = int(re.sub(r"\D", "", str(im.get("width") or "0")) or 0); h = int(re.sub(r"\D", "", str(im.get("height") or "0")) or 0)
        if (w and w < MIN_W) or (h and h < MIN_H): continue
        out.append(urljoin(url, u))
    seen, uniq = set(), []
    for u in out:
        if u not in seen: seen.add(u); uniq.append(u)
    return uniq[:8]


def fetch_html(url):
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code == 200 and "text/html" in r.headers.get("content-type", "text/html"): return r.text
    except Exception:
        pass
    return None


def find_image(url, entry=None, html=None):
    """Best real picture for an item, or None."""
    cands = []
    if entry: cands += [urljoin(url, u) for u in _entry_images(entry)]
    if html is None and (not cands or not any(_ok_picture(c) for c in cands[:2])):
        html = fetch_html(url)
    if html: cands += _page_images(url, html)
    seen = set()
    for c in cands:
        if c in seen: continue
        seen.add(c)
        if _ok_picture(c): return c[:800]
    return None


# ----------------------------------------------------------------------------- organisation detection
# Hand-checked logos for the providers that appear most. Wikimedia URLs are stable and free to hot-link.
WM = "https://commons.wikimedia.org/w/index.php?title=Special:Redirect/file/{}&width=500"
CURATED = {  # verified 2026-10-25: every URL returned an image. None = name known, logo resolved from Wikidata/site at runtime.
    "daad": ("DAAD", WM.format("Deutscher_Akademischer_Austauschdienst_logo.svg")),
    "german academic exchange service": ("DAAD", WM.format("Deutscher_Akademischer_Austauschdienst_logo.svg")),
    "chevening": ("Chevening", None),
    "fulbright": ("Fulbright Program", WM.format("Fulbright_Program.svg")),
    "erasmus": ("Erasmus+", WM.format("Erasmus%2B_Logo.svg")),
    "erasmus mundus": ("Erasmus+", WM.format("Erasmus%2B_Logo.svg")),
    "commonwealth scholarship": ("Commonwealth Scholarship Commission", None),
    "mastercard foundation": ("Mastercard Foundation", None),
    "swedish institute": ("Swedish Institute", WM.format("Svenska_Institutet_Logo.svg")),
    "australia awards": ("Australia Awards", None),
    "türkiye burslari": ("Türkiye Scholarships", None),
    "turkiye burslari": ("Türkiye Scholarships", None),
    "mext": ("MEXT Japan", WM.format("Go-shichi_no_kiri_crest.svg")),
    "gates cambridge": ("Gates Cambridge", None),
    "rhodes scholarship": ("Rhodes Trust", None),
    "schwarzman": ("Schwarzman Scholars", None),
    "knight-hennessy": ("Knight-Hennessy Scholars", None),
    "anthropic": ("Anthropic", WM.format("Anthropic_logo.svg")),
    "google": ("Google", WM.format("Google_2015_logo.svg")),
    "microsoft": ("Microsoft", WM.format("Microsoft_logo_%282012%29.svg")),
    "nvidia": ("NVIDIA", WM.format("NVIDIA_logo.svg")),
    "openai": ("OpenAI", WM.format("OpenAI_Logo.svg")),
    "meta": ("Meta", WM.format("Meta_Platforms_Inc._logo.svg")),
    "amazon": ("Amazon", WM.format("Amazon_logo.svg")),
    "apple": ("Apple", WM.format("Apple_logo_black.svg")),
    "world bank": ("World Bank", WM.format("The_World_Bank_logo.svg")),
    "african development bank": ("African Development Bank", WM.format("Logo_Afrikanische_Entwicklungsbank.svg")),
    "afdb": ("African Development Bank", WM.format("Logo_Afrikanische_Entwicklungsbank.svg")),
    "asian development bank": ("Asian Development Bank", WM.format("Asian_Development_Bank_logo.svg")),
    "unesco": ("UNESCO", WM.format("UNESCO_logo.svg")),
    "unicef": ("UNICEF", WM.format("UNICEF_Logo.svg")),
    "undp": ("UNDP", WM.format("UNDP_logo.svg")),
    "unhcr": ("UNHCR", None),
    "un women": ("UN Women", None),
    "world health organization": ("World Health Organization", WM.format("World_Health_Organization_Logo.svg")),
    "who": ("World Health Organization", WM.format("World_Health_Organization_Logo.svg")),
    "ilo": ("International Labour Organization", WM.format("ILO_logo.svg")),
    "fao": ("FAO", WM.format("FAO_logo.svg")),
    "iaea": ("IAEA", WM.format("International_Atomic_Energy_Agency_Logo.svg")),
    "imf": ("International Monetary Fund", WM.format("IMF-Seal_ENG_RGB.svg")),
    "oecd": ("OECD", WM.format("OECD_logo.svg")),
    "nato": ("NATO", WM.format("NATO_OTAN_landscape_logo.svg")),
    "cern": ("CERN", WM.format("CERN_logo_badge.svg")),
    "nasa": ("NASA", WM.format("NASA_logo.svg")),
    "european space agency": ("European Space Agency", WM.format("ESA_logo.svg")),
    "british council": ("British Council", WM.format("British_Council_logo.svg")),
    "campus france": ("Campus France", WM.format("Campus-france.svg")),
    "nuffic": ("Nuffic", None),
    "jica": ("JICA", WM.format("Japan_International_Cooperation_Agency_logo.svg")),
    "koica": ("KOICA", WM.format("KOICA_official_logo_in_english.png")),
    "china scholarship council": ("China Scholarship Council", None),
    "chinese government scholarship": ("China Scholarship Council", None),
    "global korea scholarship": ("Global Korea Scholarship", None),
    "rotary": ("Rotary International", WM.format("Rotary_International_Logo.svg")),
    "aga khan": ("Aga Khan Foundation", None),
    "ford foundation": ("Ford Foundation", WM.format("Logo_of_the_Ford_Foundation.png")),
    "wellcome": ("Wellcome Trust", WM.format("Wellcome_Trust_logo.svg")),
    "humboldt": ("Alexander von Humboldt Foundation", None),
    "heinrich böll": ("Heinrich Böll Foundation", WM.format("Heinrich-b%C3%B6ll-stiftung-schriftzug.svg")),
    "heinrich boll": ("Heinrich Böll Foundation", WM.format("Heinrich-b%C3%B6ll-stiftung-schriftzug.svg")),
    "konrad adenauer": ("Konrad Adenauer Foundation", WM.format("Konrad-Adenauer-Stiftung_logo.svg")),
    "friedrich ebert": ("Friedrich Ebert Foundation", WM.format("Logo_Friedrich_Ebert_Stiftung.svg")),
    "médecins sans frontières": ("Médecins Sans Frontières", None),
    "msf": ("Médecins Sans Frontières", None),
    "vfs global": ("VFS Global", WM.format("Logo_of_VFS_Global_%282019%29.svg")),
    "nnpc": ("NNPC", WM.format("Nigerian_National_Petroleum_Company_logo.svg")),
    "ptdf": ("PTDF", None),
    "petroleum technology development fund": ("PTDF", None),
    "totalenergies": ("TotalEnergies", None),
    "shell": ("Shell", WM.format("Shell_wordmark_2019.svg")),
    "chevron": ("Chevron", WM.format("Chevron_Logo.svg")),
    "agbami": ("Chevron", WM.format("Chevron_Logo.svg")),
    "mtn": ("MTN", WM.format("MTN_Logo.svg")),
    "nlng": ("Nigeria LNG", None),
    "dangote": ("Dangote Group", None),
    "seplat": ("Seplat Energy", None),
    "access bank": ("Access Bank", None),
    "first bank": ("First Bank of Nigeria", None),
    "zenith bank": ("Zenith Bank", None),
    "gtbank": ("GTBank", WM.format("GTBank_logo.svg")),
    "uba": ("UBA", None),
    "flutterwave": ("Flutterwave", WM.format("Flutterwave_Logo.png")),
    "jamb": ("JAMB", "https://jamb.gov.ng/assets/layouts/layout3/img/banner.png"),
    "nysc": ("NYSC", "https://www.nysc.gov.ng/img/nysclogo.png"),
    "tetfund": ("TETFund", None),
    "nuc": ("National Universities Commission", None),
    "asuu": ("ASUU", "https://asuu.org.ng/wp-content/uploads/2021/09/logo-removebg.png"),
    "federal government of nigeria": ("Government of Nigeria", WM.format("Coat_of_arms_of_Nigeria.svg")),
    "nigerian government": ("Government of Nigeria", WM.format("Coat_of_arms_of_Nigeria.svg")),
    "bilateral education agreement": ("Government of Nigeria", WM.format("Coat_of_arms_of_Nigeria.svg")),
    "lagos state": ("Lagos State Government", None),
    "university of oxford": ("University of Oxford", WM.format("Oxford-University-Circlet.svg")),
    "oxford": ("University of Oxford", WM.format("Oxford-University-Circlet.svg")),
    "university of cambridge": ("University of Cambridge", WM.format("University_of_Cambridge_logo.png")),
    "cambridge": ("University of Cambridge", WM.format("University_of_Cambridge_logo.png")),
    "harvard": ("Harvard University", WM.format("Harvard_University_logo.svg")),
    "stanford": ("Stanford University", WM.format("Stanford_wordmark_%282012%29.svg")),
    "mit": ("MIT", WM.format("MIT_logo.svg")),
    "yale": ("Yale University", WM.format("Yale_University_logo.svg")),
    "princeton": ("Princeton University", WM.format("Princeton_text_logo.svg")),
    "columbia university": ("Columbia University", WM.format("Coat_of_Arms_of_Columbia_University.svg")),
    "imperial college": ("Imperial College London", WM.format("Imperial_College_London_new_logo.png")),
    "ucl": ("UCL", WM.format("UCL_Crest.svg")),
    "university of edinburgh": ("University of Edinburgh", None),
    "university of manchester": ("University of Manchester", None),
    "university of toronto": ("University of Toronto", None),
    "mcgill": ("McGill University", WM.format("Mcgill_univ_ca_logo.png")),
    "university of melbourne": ("University of Melbourne", WM.format("Arms_of_the_University_of_Melbourne.svg")),
    "university of sydney": ("University of Sydney", None),
    "eth zurich": ("ETH Zurich", WM.format("ETH_Z%C3%BCrich_Logo_black.svg")),
    "epfl": ("EPFL", WM.format("Logo_EPFL_2019.svg")),
    "kaist": ("KAIST", WM.format("KAIST_logo.svg")),
    "national university of singapore": ("NUS", None),
    "university of tokyo": ("University of Tokyo", WM.format("University_of_Tokyo_logo_%282024%29.svg")),
    "university of lagos": ("University of Lagos", None),
    "unilag": ("University of Lagos", None),
    "university of ibadan": ("University of Ibadan", None),
    "obafemi awolowo university": ("Obafemi Awolowo University", None),
    "ahmadu bello university": ("Ahmadu Bello University", None),
    "university of nigeria": ("University of Nigeria, Nsukka", None),
    "covenant university": ("Covenant University", "https://covenantuniversity.edu.ng/images/logos/covenant-university-logo-desktop.png"),
}
# multi-word keys first so "university of oxford" wins over "oxford"
_CUR = sorted(CURATED.items(), key=lambda kv: -len(kv[0]))
_CUR_RE = [(re.compile(r"(?<![\w-])" + re.escape(k) + r"(?![\w-])", re.I), v) for k, v in _CUR]

ORG_RE = re.compile(r"\b((?:University|College|Institute|Foundation|Trust|Academy|Polytechnic|Bank|Council|Ministry|Government|Embassy|Agency|Fund|Society|Association|Centre|Center|School)"
                    r"\s+(?:of|for|de|du|di)\s+(?:[A-Z][\w'&.-]+\s*){1,4}|"
                    r"(?:[A-Z][\w'&.-]+\s+){1,4}(?:University|College|Institute|Foundation|Trust|Academy|Polytechnic|Bank|Council|Ministry|Embassy|Agency|Fund|Society|Association|Group|Corporation|Company|Ltd|Limited|Inc|Plc|Energy|Petroleum))\b")
STOP = {"international", "global", "fully", "funded", "summer", "scholarship", "scholarships", "fellowship", "fellowships", "program", "programme", "online", "new", "the",
        "full", "free", "call", "apply", "applications", "application", "open", "opens", "get", "hot", "study", "top", "best", "latest", "undergraduate", "graduate",
        "masters", "phd", "doctoral", "postdoctoral", "internship", "internships", "grant", "grants", "award", "awards", "exchange", "research", "training", "paid"}


def org_from_title(title):
    """Organisation named in a title, or None."""
    if not title: return None
    for rx, (name, _) in _CUR_RE:
        if rx.search(title): return name
    m = ORG_RE.search(title)
    if m:
        s = re.sub(r"\s+(for|in|at|to|and|of|by)$", "", m.group(1).strip(" -–:,"))
        words = s.split()
        if not words or words[0].lower() in STOP or len(s) < 6: return None
        return s[:80]
    return None


def root_domain(host):
    p = (host or "").lower().replace("www.", "").split(".")
    if len(p) >= 3 and p[-2] in ("ac", "edu", "gov", "co", "com", "org", "net", "or", "go") and len(p[-1]) == 2: return ".".join(p[-3:])
    return ".".join(p[-2:]) if len(p) >= 2 else host


# ----------------------------------------------------------------------------- Wikidata
_WD = requests.Session(); _WD.headers.update(WD_UA)


def _wd(params):
    for a in range(4):
        try:
            r = _WD.get("https://www.wikidata.org/w/api.php", params=params, timeout=20)
            if r.status_code == 200: return r.json()
            if r.status_code == 429: time.sleep(3 * (a + 1)); continue
            return {}
        except Exception:
            time.sleep(2)
    return {}


def _wd_logo_from_ids(ids):
    ents = _wd({"action": "wbgetentities", "ids": "|".join(ids[:5]), "props": "claims|labels", "languages": "en", "format": "json"}).get("entities", {})
    for prop in ("P154", "P94", "P8972"):           # logo image, coat of arms, small logo – real logos only, never campus photos
        for i in ids[:5]:
            cl = ents.get(i, {}).get("claims", {})
            if prop in cl and "datavalue" in cl[prop][0]["mainsnak"]:
                f = cl[prop][0]["mainsnak"]["datavalue"]["value"]
                return ents[i]["labels"].get("en", {}).get("value"), WM.format(quote(f.replace(" ", "_")))
    return None, None


def wikidata_by_name(name):
    s = _wd({"action": "wbsearchentities", "search": name, "language": "en", "limit": 5, "format": "json"}).get("search", [])
    if not s: return None, None
    # keep only hits whose label/alias really contains the main words of the name (avoids "American Swedish Institute")
    kw = [w for w in re.findall(r"[a-z0-9]{3,}", name.lower()) if w not in ("the", "and", "for")]
    ids = [x["id"] for x in s if all(w in (x.get("label", "") + " " + " ".join(x.get("aliases", []) or []) + " " + x.get("description", "")).lower() for w in kw[:3])] or [s[0]["id"]]
    return _wd_logo_from_ids(ids)


def wikidata_by_domain(domain):
    for v in (f"https://www.{domain}/", f"https://{domain}/", f"http://www.{domain}/", f"http://{domain}/", f"https://www.{domain}", f"https://{domain}"):
        hits = _wd({"action": "query", "list": "search", "srsearch": f"haswbstatement:P856={v}", "srlimit": 3, "format": "json"}).get("query", {}).get("search", [])
        if hits: return _wd_logo_from_ids([h["title"] for h in hits])
    return None, None


def site_logo(domain):
    """The website's own header logo / touch icon (used for aggregators and publishers)."""
    for home in (f"https://www.{domain}/", f"https://{domain}/"):
        html = fetch_html(home)
        if not html: continue
        soup = BeautifulSoup(html, "html.parser"); c = []
        m = soup.find("meta", attrs={"property": "og:logo"})
        if m and m.get("content"): c.append(urljoin(home, m["content"]))
        for im in soup.find_all("img"):
            u = im.get("data-src") or im.get("src") or ""
            blob = " ".join([u, im.get("alt") or "", str(im.get("class") or ""), str(im.get("id") or "")]).lower()
            if ("logo" in blob or "brand" in blob) and u and not u.startswith("data:") and not re.search(r"footer|partner|ipso|regulat|award|sponsor|payment|visa|mastercard|verisign|trust|badge|app-?store|google-?play|member", blob): c.append(urljoin(home, u))
        for l in soup.find_all("link", rel=lambda v: v and "apple-touch-icon" in " ".join(v)): c.append(urljoin(home, l.get("href", "")))
        for u in c:
            if not u.startswith("http"): continue
            w, h = _dims(u)
            if (w >= 100 and h >= 40) or u.lower().endswith(".svg"): return u[:800]
    return None


# ----------------------------------------------------------------------------- cached logo lookup
_mem = {}


def _cache_get(SB, key):
    if key in _mem: return _mem[key]
    if SB:
        try:
            r = SB.table("logos").select("name,url").eq("key", key).limit(1).execute().data
            if r: _mem[key] = (r[0]["name"], r[0]["url"]); return _mem[key]
        except Exception as e:
            log.debug("logos read %s", e)
    return None


def _cache_put(SB, key, name, url, kind):
    _mem[key] = (name, url)
    if SB:
        try: SB.table("logos").upsert({"key": key, "name": name, "url": url, "kind": kind, "checked": datetime.now(timezone.utc).isoformat()}).execute()
        except Exception as e: log.debug("logos write %s", e)


def logo_for(org_name=None, domain=None, SB=None):
    """(display name, logo url) for an organisation name and/or a domain; (None, None) if nothing real is found."""
    if org_name:
        key = "n:" + org_name.lower().strip()
        hit = _cache_get(SB, key)
        if hit is None:
            name, url = None, None
            for rx, (nm, u) in _CUR_RE:
                if rx.search(org_name): name, url = nm, u; break
            if not url:
                n2, url = wikidata_by_name(name or org_name)
                name = name or n2
            _cache_put(SB, key, name or org_name, url, "curated" if url and any(url == v[1] for v in CURATED.values()) else ("wikidata" if url else "none"))
            hit = (name or org_name, url)
        if hit[1]: return hit
    if domain:
        d = root_domain(domain)
        if not d or "." not in d: return None, None
        key = "d:" + d
        hit = _cache_get(SB, key)
        if hit is None:
            name, url = None, None
            for rx, (nm, u) in _CUR_RE:
                if rx.search(d.split(".")[0]) and len(d.split(".")[0]) > 4: name, url = nm, u; break
            if not url: name, url = wikidata_by_domain(d)
            kind = "wikidata" if url else None
            if not url:
                url = site_logo(d); kind = "site" if url else "none"
            _cache_put(SB, key, name or d, url, kind)
            hit = (name or d, url)
        if hit[1]: return hit
    return None, None


# ----------------------------------------------------------------------------- per-table enrichment
def _domain_of(row):
    try: return urlparse(row.get("url") or "").netloc
    except Exception: return ""


def _resolve(SB, table, row, entry=None):
    """-> dict of fields to store for this row."""
    url = row.get("url") or ""
    img = None
    try: img = find_image(url, entry=entry)
    except Exception as e: log.debug("image %s: %s", url[:60], e)
    out = {"image": img, "media_checked": datetime.now(timezone.utc).isoformat()}
    if img: return out
    name = logo_url = None
    if table == "school_news" and row.get("school"):
        name, logo_url = logo_for(org_name=row["school"], domain=_domain_of(row), SB=SB)
    else:
        org = org_from_title(row.get("title"))
        src = re.sub(r"^[🔎🌐]\s*|^Web:\s*|\s*\(\.(gov|edu)\)$", "", row.get("source") or "").strip()
        found = {}
        try: found = json.loads(row.get("found_links") or "{}") if isinstance(row.get("found_links"), str) else (row.get("found_links") or {})
        except Exception: found = {}
        official = next(iter(found.keys()), None) if isinstance(found, dict) else None
        for nm, dm in ((org, None), (None, official), (src if "." not in src else None, src if "." in src else None), (None, _domain_of(row))):
            if not nm and not dm: continue
            name, logo_url = logo_for(org_name=nm, domain=dm, SB=SB)
            if logo_url: break
    if logo_url:
        out["logo"] = logo_url
        if table == "scholarships": out["org"] = (name or "")[:120]
    return out


def enrich(SB, table, rows, entries=None, workers=6):
    """Fill image/logo for freshly inserted rows. `entries` = optional {row_id: feedparser entry}."""
    rows = [r for r in rows if r.get("id") and r.get("url")]
    if not rows: return 0
    entries = entries or {}
    done = 0
    with ThreadPoolExecutor(workers) as ex:
        for row, fields in zip(rows, ex.map(lambda r: _resolve(SB, table, r, entries.get(r["id"])), rows)):
            try:
                SB.table(table).update(fields).eq("id", row["id"]).execute(); done += 1 if fields.get("image") or fields.get("logo") else 0
            except Exception as e:
                log.warning("media update %s: %s", row["id"], e)
    log.info("%s: media for %d/%d new items", table, done, len(rows))
    return done


def backfill(SB, table, limit=120):
    """Older rows never checked for a picture: a batch per crawl, newest first, until the whole table is covered."""
    cols = "id,url,title,source,school" if table == "school_news" else "id,url,title,source"
    try:
        rows = SB.table(table).select(cols).is_("media_checked", "null").order("published", desc=True).limit(limit).execute().data or []
    except Exception as e:
        log.warning("backfill select %s: %s", table, e); return 0
    if not rows: return 0
    n = enrich(SB, table, rows)
    log.info("%s: backfilled %d rows (%d with media)", table, len(rows), n)
    return n
