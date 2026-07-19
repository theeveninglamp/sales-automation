from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import re
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

USER_AGENT = "Mozilla/5.0 (compatible; SalesAutomationEngine/1.0; +https://example.com/bot)"
DEFAULT_TIMEOUT_SECONDS = 15
MAX_VISIBLE_TEXT_CHARS = 8000
MAX_META_DESCRIPTION_CHARS = 500
MAX_TITLE_CHARS = 250


@dataclass(frozen=True)
class ScrapedWebsite:
    title: str
    meta_description: str
    visible_text: str
    industry: str


INDUSTRY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Healthcare": ("patient", "clinic", "health", "medical", "care", "provider"),
    "Financial Services": ("bank", "finance", "loan", "wealth", "insurance", "payment"),
    "SaaS": ("software", "platform", "api", "cloud", "automation", "workflow"),
    "E-commerce": ("shop", "cart", "product", "shipping", "retail", "store"),
    "Education": ("student", "course", "learning", "school", "training", "university"),
    "Real Estate": ("property", "homes", "real estate", "broker", "listing", "mortgage"),
    "Manufacturing": ("manufacturing", "factory", "industrial", "supply chain", "equipment"),
    "Professional Services": ("consulting", "agency", "legal", "accounting", "advisory"),
}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.meta_description = ""
        self.text_parts: list[str] = []
        self._tag_stack: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self._tag_stack.append(tag)
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if tag == "meta" and not self.meta_description:
            attr_map = {key.lower(): value or "" for key, value in attrs}
            name = attr_map.get("name", "").lower()
            prop = attr_map.get("property", "").lower()
            if name == "description" or prop == "og:description":
                self.meta_description = attr_map.get("content", "")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._tag_stack and self._tag_stack[-1] == "title":
            self.title_parts.append(data)
        elif data.strip():
            self.text_parts.append(data)

    @property
    def title(self) -> str:
        return _truncate(" ".join(self.title_parts), MAX_TITLE_CHARS)

    @property
    def visible_text(self) -> str:
        return _truncate(" ".join(self.text_parts), MAX_VISIBLE_TEXT_CHARS)


def _truncate(text: str | None, max_chars: int) -> str:
    if not text:
        return ""
    clean = re.sub(r"\s+", " ", text).strip()
    return clean[: max_chars - 1] + "…" if len(clean) > max_chars else clean


def _load_optional_module(module_name: str) -> Any | None:
    if importlib.util.find_spec(module_name) is None:
        return None
    return importlib.import_module(module_name)


class WebsiteScraper:
    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds
        self._requests = _load_optional_module("requests")
        self._trafilatura = _load_optional_module("trafilatura")
        self._bs4 = _load_optional_module("bs4")

    def scrape(self, url: str) -> ScrapedWebsite:
        html = self.fetch_homepage(url)
        return self.scrape_html(html, url)

    def fetch_homepage(self, url: str) -> str:
        if self._requests is not None:
            response = self._requests.get(url, timeout=self.timeout_seconds, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            return response.text

        request = Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            raise RuntimeError(f"Failed to fetch {url}: HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"Failed to fetch {url}: {exc.reason}") from exc

    def scrape_html(self, html: str, url: str = "https://example.com") -> ScrapedWebsite:
        title, meta, visible = self._extract_with_beautifulsoup(html, url) if self._bs4 is not None else self._extract_with_stdlib(html, url)
        article_text = self._extract_with_trafilatura(html, url)
        text = _truncate(article_text or visible, MAX_VISIBLE_TEXT_CHARS)
        industry = self.infer_industry(" ".join([title, meta, text]))
        return ScrapedWebsite(title=title, meta_description=meta, visible_text=text, industry=industry)

    def _extract_with_beautifulsoup(self, html: str, url: str) -> tuple[str, str, str]:
        beautiful_soup = self._bs4.BeautifulSoup
        soup = beautiful_soup(html, "html.parser")
        title = self._extract_title_from_soup(soup, url)
        meta = self._extract_meta_from_soup(soup)
        for element in soup(["script", "style", "noscript", "svg"]):
            element.decompose()
        visible = _truncate(soup.get_text(" ", strip=True), MAX_VISIBLE_TEXT_CHARS)
        return title, meta, visible

    def _extract_with_trafilatura(self, html: str, url: str) -> str:
        if self._trafilatura is None:
            return ""
        extracted = self._trafilatura.extract(html, url=url, include_comments=False, include_tables=False)
        return _truncate(extracted or "", MAX_VISIBLE_TEXT_CHARS)

    @staticmethod
    def _extract_with_stdlib(html: str, url: str) -> tuple[str, str, str]:
        parser = _HTMLTextExtractor()
        parser.feed(html)
        return parser.title or urlparse(url).netloc, _truncate(parser.meta_description, MAX_META_DESCRIPTION_CHARS), parser.visible_text

    @staticmethod
    def _extract_title_from_soup(soup: Any, url: str) -> str:
        if soup.title and soup.title.string:
            return _truncate(str(soup.title.string), MAX_TITLE_CHARS)
        return urlparse(url).netloc

    @staticmethod
    def _extract_meta_from_soup(soup: Any) -> str:
        tag = soup.find("meta", attrs={"name": re.compile("description", re.I)})
        if not tag:
            tag = soup.find("meta", attrs={"property": "og:description"})
        return _truncate(str(tag.get("content", "")) if tag else "", MAX_META_DESCRIPTION_CHARS)

    @staticmethod
    def infer_industry(text: str) -> str:
        lowered = text.lower()
        scores = {industry: sum(lowered.count(keyword) for keyword in keywords) for industry, keywords in INDUSTRY_KEYWORDS.items()}
        best, score = max(scores.items(), key=lambda item: item[1])
        return best if score > 0 else "General Business"


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape a company homepage and print extracted metadata as JSON.")
    parser.add_argument("url", help="Homepage URL to scrape")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Request timeout in seconds")
    args = parser.parse_args()
    result = WebsiteScraper(timeout_seconds=args.timeout).scrape(args.url)
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
