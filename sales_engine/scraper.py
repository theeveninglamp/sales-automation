from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup
from loguru import logger

from sales_engine.utils import get_settings, truncate


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


class WebsiteScraper:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; SalesAutomationEngine/1.0; +https://example.com/bot)"
        })

    def scrape(self, url: str) -> ScrapedWebsite:
        logger.info("Scraping website: {}", url)
        response = self.session.get(url, timeout=self.settings.request_timeout_seconds)
        response.raise_for_status()
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        title = self._extract_title(soup, url)
        meta = self._extract_meta_description(soup)
        text = trafilatura.extract(html, url=url, include_comments=False, include_tables=False) or self._visible_text(soup)
        text = truncate(text, 8000)
        industry = self.infer_industry(" ".join([title, meta, text]))
        return ScrapedWebsite(title=title, meta_description=meta, visible_text=text, industry=industry)

    @staticmethod
    def _extract_title(soup: BeautifulSoup, url: str) -> str:
        if soup.title and soup.title.string:
            return truncate(soup.title.string, 250)
        return urlparse(url).netloc

    @staticmethod
    def _extract_meta_description(soup: BeautifulSoup) -> str:
        tag = soup.find("meta", attrs={"name": re.compile("description", re.I)})
        if not tag:
            tag = soup.find("meta", attrs={"property": "og:description"})
        return truncate(str(tag.get("content", "")) if tag else "", 500)

    @staticmethod
    def _visible_text(soup: BeautifulSoup) -> str:
        for element in soup(["script", "style", "noscript", "svg"]):
            element.decompose()
        return truncate(soup.get_text(" ", strip=True), 8000)

    @staticmethod
    def infer_industry(text: str) -> str:
        lowered = text.lower()
        scores = {industry: sum(lowered.count(keyword) for keyword in keywords) for industry, keywords in INDUSTRY_KEYWORDS.items()}
        best, score = max(scores.items(), key=lambda item: item[1])
        return best if score > 0 else "General Business"
