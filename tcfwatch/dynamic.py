"""Dynamic site extraction: discover and monitor month-specific registration pages.

For sites marked as dynamic=True, this module fetches the hub page (e.g.,
registration-process), extracts links matching the pattern (e.g., month
registration pages), and yields Site objects for each.

December 2026 is always prioritized and monitored first.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .config import Site

log = logging.getLogger("tcfwatch.dynamic")


def extract_dynamic_sites(
    template_site: Site,
    user_agent: str,
    request_timeout: int,
    session: requests.Session | None = None,
) -> list[Site]:
    """Extract month-specific Site objects from a dynamic template site.

    Args:
        template_site: Site marked with dynamic=True
        user_agent: User agent string for requests
        request_timeout: Request timeout in seconds
        session: Optional requests.Session to reuse

    Returns:
        List of Site objects for each month found (December 2026 first if present)
    """
    if not template_site.dynamic or not template_site.link_pattern:
        return []

    s = session or requests.Session()
    sites = []

    try:
        r = s.get(
            template_site.url,
            headers={"User-Agent": user_agent},
            timeout=request_timeout,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning(
            "Failed to fetch dynamic template %s: %s",
            template_site.key,
            e,
        )
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    # Extract all links
    links = []
    if template_site.link_selector:
        for elem in soup.select(template_site.link_selector):
            href = elem.get("href")
            text = elem.get_text(strip=True)
            if href:
                links.append((href, text))

    # Filter by pattern and build Site objects
    pattern = re.compile(template_site.link_pattern, re.IGNORECASE)
    sep_key = template_site.key

    # First pass: collect all matches
    candidates = []
    for href, text in links:
        full_url = urljoin(template_site.url, href)
        if pattern.search(text) or pattern.search(href):
            # Extract month identifier from text or URL
            month_key = _extract_month_key(text, href)
            candidates.append((month_key, full_url, text))

    # Sort: December 2026 first, then others
    candidates.sort(key=lambda x: (
        not ("2026" in x[0] and ("dec" in x[0].lower() or "12" in x[0])),
        x[0]
    ))

    for month_key, url, text in candidates:
        child_key = f"{sep_key}_{month_key}".replace(" ", "_").replace("/", "_")
        child_name = f"{template_site.name} ({text[:40]})"

        sites.append(
            Site(
                key=child_key,
                name=child_name,
                url=url,
                selectors=template_site.selectors,
                keywords=template_site.keywords,
                parent_key=template_site.key,
            )
        )

    log.info(
        "Extracted %d month sites from %s (first: %s)",
        len(sites),
        template_site.key,
        sites[0].key if sites else "none",
    )
    return sites


def _extract_month_key(text: str, href: str) -> str:
    """Extract a sortable month key from link text or URL.

    Returns something like "2026_12" or "december_2026" or "10_2026".
    """
    # Try to extract from text first (e.g., "December 2026")
    match = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|décembre|novembre|octobre)\w*\s+(\d{4})", text, re.I)
    if match:
        month_str, year = match.groups()
        month_num = _month_name_to_num(month_str)
        return f"{year}_{month_num:02d}"

    # Try MM/YYYY format (e.g., "12/2026")
    match = re.search(r"(\d{1,2})/(\d{4})", text)
    if match:
        month, year = match.groups()
        return f"{year}_{int(month):02d}"

    # Fall back to text slug
    return text[:30].lower().replace(" ", "_").replace("/", "_")


def _month_name_to_num(month_str: str) -> int:
    """Convert month name (EN/FR) to number."""
    month_map = {
        "jan": 1, "janv": 1,
        "feb": 2, "févr": 2, "feb": 2,
        "mar": 3, "mars": 3,
        "apr": 4, "avr": 4,
        "may": 5, "mai": 5,
        "jun": 6, "juin": 6,
        "jul": 7, "juil": 7,
        "aug": 8, "août": 8,
        "sep": 9, "sept": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12, "déc": 12, "décembre": 12,
    }
    month_lower = month_str[:3].lower()
    return month_map.get(month_lower, 1)
