import os
import re
import sqlite3
import datetime as dt
import urllib.parse as urlparse
import scrapy
from w3lib.html import remove_tags, replace_escape_chars

try:
    from langdetect import detect, DetectorFactory 
    DetectorFactory.seed = 0
except Exception:
    detect = None  


STATE_DIR = os.environ.get("TM_STATE_DIR", ".state")
os.makedirs(STATE_DIR, exist_ok=True)
SEEN_DB_PATH = os.path.join(STATE_DIR, "themanufacturer_seen.sqlite")
TM_DOMAINS = {"themanufacturer.com", "www.themanufacturer.com"}

class SeenStore:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS seen (url TEXT PRIMARY KEY, first_seen TEXT)"
        )
        self.conn.commit()

    def has(self, url: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM seen WHERE url = ? LIMIT 1", (url,))
        return cur.fetchone() is not None

    def add(self, url: str):
        self.conn.execute(
            "INSERT OR IGNORE INTO seen(url, first_seen) VALUES(?, ?)",
            (url, dt.datetime.utcnow().isoformat(timespec="seconds")),
        )
        self.conn.commit()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


def to_plain_text(html: str) -> str:

    if not html:
        return ""
    text = replace_escape_chars(remove_tags(html), which_ones=("&nbsp;",)).strip()
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def strip_ordinals(s: str) -> str:
    return re.sub(r"(\d{1,2})(st|nd|rd|th)", r"\1", s, flags=re.IGNORECASE)


def parse_date(date_str: str):

    if not date_str:
        return None
    s = strip_ordinals(date_str.strip()).replace(",", "")
    fmts = [
        "%d %b %Y",  
        "%d %B %Y", 
        "%b %d %Y",
        "%B %d %Y", 
    ]
    for fmt in fmts:
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None



def absolutize(base_url: str, href: str) -> str:
    if not href:
        return None
    return urlparse.urljoin(base_url, href)

def is_internal(url: str) -> bool:
    try:
        netloc = urlparse.urlparse(url).netloc.lower()
        return any(netloc.endswith(d) for d in TM_DOMAINS)
    except Exception:
        return False


class TMSectionsSpider(scrapy.Spider):
    name = "tm_sections"
    allowed_domains = ["themanufacturer.com", "www.themanufacturer.com"]
    start_urls = ["https://www.themanufacturer.com/"]

    def __init__(self, cutoff=None, cutoff_year=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if cutoff:
            self.cutoff_date = dt.date.fromisoformat(cutoff)
        elif cutoff_year:
            self.cutoff_date = dt.date(int(cutoff_year), 1, 1)
        else:
            self.cutoff_date = dt.date(2025, 1, 1)

    custom_settings = {
        "ROBOTSTXT_OBEY": True,
        "DOWNLOAD_DELAY": 0.5,
        "DEFAULT_REQUEST_HEADERS": {
            "User-Agent": "Mozilla/5.0 (compatible; TMResearchBot/1.0; +https://example.org/contact)"
        },
    }

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.seen = SeenStore(SEEN_DB_PATH)
        return spider

    def closed(self, reason):
        if hasattr(self, "seen"):
            self.seen.close()

    def parse(self, response):
        section_links = set(response.css("#menu-channels a::attr(href)").getall())
        if not section_links:
            section_links.update(response.css("header a[href*='/channel/']::attr(href)").getall())

        section_links = {response.urljoin(u) for u in section_links if "/channel/" in u}
        if not section_links:
            self.logger.warning("No /channel/ links found on homepage; check selectors.")

        for url in sorted(section_links):
            yield scrapy.Request(url, callback=self.parse_section, meta={"section_url": url})

    def parse_section(self, response):
        section_url = response.meta.get("section_url")
        article_count = response.meta.get("article_count", 0)

        hrefs = set()
        hrefs.update(response.css("h3.item-title a::attr(href)").getall())
        hrefs.update(response.css("div.item-excerpt a::attr(href)").getall())
        hrefs.update(response.css("a[href*='/articles/']::attr(href)").getall())

        new_articles = []
        for href in sorted({response.urljoin(h) for h in hrefs if "/articles/" in h}):
            if not self.seen.has(href):
                new_articles.append(href)
        remaining = 5 - article_count
        for href in new_articles[:remaining]:
            yield response.follow(
                href,
                callback=self.parse_article,
                meta={"section_url": section_url, "article_count": article_count + 1},
            )
            article_count += 1

        if article_count < 5:
            next_page = (
                response.css("a.next.page-numbers::attr(href)").get()
                or response.css("a.next::attr(href)").get()
                or response.css("link[rel='next']::attr(href)").get()
            )
            if next_page:
                yield response.follow(
                    next_page,
                    callback=self.parse_section,
                    meta={"section_url": section_url, "article_count": article_count},
                )

    def parse_article(self, response):

        section_url = response.meta.get("section_url")
        title = (
            response.css("h1.page-title span::text").get()
            or response.css("h1.page-title::text").get()
        )
        title = title.strip() if title else None

        date_str = response.css("#single-article-date::text").get()
        date_str = date_str.strip() if date_str else None
        parsed_date = parse_date(date_str) if date_str else None

        if parsed_date and parsed_date < self.cutoff_date:
            self.logger.debug(f"SKIP old article {parsed_date} < {self.cutoff_date}: {response.url}")
            return

        companies = [t.strip() for t in response.css("div.article-company a::text").getall() if t.strip()]
        company = ", ".join(companies) if companies else None

        body_selectors = [
            "div.single-article-content",
            "div.entry-content",
            "div.article-content",
            "article",
        ]
        raw_html = ""
        body = None
        for sel in body_selectors:
            body = response.css(sel)
            if body:
                raw_html = body.get(default="")
                if raw_html:
                    break
        if not raw_html:
            body = response
            raw_html = "".join(response.css("p, li, h2, h3").getall())

        text = to_plain_text(raw_html)

        tags = [t.strip() for t in response.css("div.post-terms ul.post-tags a::text").getall() if t.strip()]

        internal_links = []
        for a in body.css("a::attr(href)").getall():
            u = absolutize(response.url, a)
            if u and is_internal(u):
                internal_links.append(u)
        seen_u = set()
        internal_links = [u for u in internal_links if not (u in seen_u or seen_u.add(u))]

        language = None
        if detect and text:
            try:
                language = detect(text)
            except Exception:
                language = None

        item = {
            "url": response.url,
            "section": section_url,
            "title": title,
            "date": date_str,
            "date_iso": parsed_date.isoformat() if parsed_date else None,
            "company": company,
            "text": text,
            "language": language,
            "tags": tags or None,
            "internal_links": internal_links or None,
        }

        self.seen.add(response.url)
        yield item
