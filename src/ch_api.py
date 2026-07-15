"""
Thin client for the Companies House REST API + Document API.

Docs:
  - Main API:       https://developer-specs.company-information.service.gov.uk/
  - Document API:   https://developer-specs.company-information.service.gov.uk/document-api/reference

Auth: HTTP Basic auth, API key as username, empty password.
Rate limit: 600 requests / 5-minute rolling window per key (as of 2026).
"""

from __future__ import annotations

import os
import time
import logging
from typing import Any, Iterator

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

API_BASE = "https://api.company-information.service.gov.uk"
DOCUMENT_API_BASE = "https://document-api.company-information.service.gov.uk"

DEFAULT_TIMEOUT = int(os.environ.get("CH_REQUEST_TIMEOUT", "30"))


class CompaniesHouseError(RuntimeError):
    pass


class CompaniesHouseClient:
    def __init__(self, api_key: str | None = None, timeout: int = DEFAULT_TIMEOUT):
        self.api_key = api_key or os.environ.get("COMPANIES_HOUSE_API_KEY")
        if not self.api_key:
            raise CompaniesHouseError(
                "No API key found. Set COMPANIES_HOUSE_API_KEY in your .env file. "
                "Get a free key at https://developer.companieshouse.gov.uk/"
            )
        self.timeout = timeout
        self.session = requests.Session()
        self.session.auth = (self.api_key, "")

    # ------------------------------------------------------------------ #
    # Low-level request helper with retry/backoff on rate limiting
    # ------------------------------------------------------------------ #
    def _get(self, url: str, params: dict | None = None, max_retries: int = 5) -> requests.Response:
        for attempt in range(max_retries):
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 429:
                # Companies House returns a reset timestamp in this header
                reset = resp.headers.get("X-Ratelimit-Reset")
                wait = 10
                if reset:
                    try:
                        wait = max(1, int(float(reset) - time.time()))
                    except (ValueError, TypeError):
                        pass
                log.warning("Rate limited, waiting %ss (attempt %d/%d)", wait, attempt + 1, max_retries)
                time.sleep(min(wait, 60))
                continue
            if resp.status_code == 404:
                return resp  # let callers decide how to handle "not found"
            if resp.status_code >= 500:
                wait = 2 ** attempt
                log.warning("Server error %s, retrying in %ss", resp.status_code, wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        raise CompaniesHouseError(f"Failed after {max_retries} retries: {url}")

    # ------------------------------------------------------------------ #
    # Advanced search — used to discover companies by SIC code
    # ------------------------------------------------------------------ #
    def advanced_search_companies(
        self,
        sic_codes: list[str],
        company_status: str = "active",
        size: int = 100,
    ) -> Iterator[dict[str, Any]]:
        """
        Yields company summary dicts for every company matching the given
        SIC code(s) and status. Handles pagination automatically.

        Advanced search docs:
        https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference/advanced-company-search
        """
        start_index = 0
        seen = 0
        total = None
        while total is None or seen < total:
            params = {
                "sic_codes": ",".join(sic_codes),
                "company_status": company_status,
                "size": size,
                "start_index": start_index,
            }
            resp = self._get(f"{API_BASE}/advanced-search/companies", params=params)
            payload = resp.json()
            total = payload.get("hits", 0)
            items = payload.get("items", [])
            if not items:
                break
            for item in items:
                yield item
            seen += len(items)
            start_index += size
            time.sleep(0.15)  # be polite even within rate limit

    # ------------------------------------------------------------------ #
    # Company profile / filing history / PSC
    # ------------------------------------------------------------------ #
    def company_profile(self, company_number: str) -> dict[str, Any] | None:
        resp = self._get(f"{API_BASE}/company/{company_number}")
        if resp.status_code == 404:
            return None
        return resp.json()

    def filing_history(
        self, company_number: str, category: str | None = None, items_per_page: int = 100
    ) -> Iterator[dict[str, Any]]:
        start_index = 0
        while True:
            params = {"items_per_page": items_per_page, "start_index": start_index}
            if category:
                params["category"] = category
            resp = self._get(f"{API_BASE}/company/{company_number}/filing-history", params=params)
            if resp.status_code == 404:
                return
            payload = resp.json()
            items = payload.get("items", [])
            if not items:
                return
            for item in items:
                yield item
            start_index += items_per_page
            if start_index >= payload.get("total_count", 0):
                return

    def persons_with_significant_control(self, company_number: str) -> list[dict[str, Any]]:
        resp = self._get(f"{API_BASE}/company/{company_number}/persons-with-significant-control")
        if resp.status_code == 404:
            return []
        return resp.json().get("items", [])

    # ------------------------------------------------------------------ #
    # Document API — used to pull the actual accounts document (iXBRL)
    # ------------------------------------------------------------------ #
    def latest_accounts_filing(self, company_number: str) -> dict[str, Any] | None:
        """
        Returns the most recent 'accounts' category filing-history item
        (type AA or AAMD — full or amended full accounts), or None if the
        company has never filed full accounts (e.g. micro-entity / dormant
        filers that use abridged accounts with no P&L).
        """
        candidates = []
        for item in self.filing_history(company_number, category="accounts"):
            if item.get("type") in ("AA", "AAMD"):
                candidates.append(item)
        if not candidates:
            return None
        candidates.sort(key=lambda x: x.get("date", ""), reverse=True)
        return candidates[0]

    def download_document(self, document_id: str, content_type: str = "application/xhtml+xml") -> bytes:
        """
        Downloads a filed document via the Document API.
        content_type: 'application/xhtml+xml' for iXBRL (preferred — machine
        readable), or 'application/pdf' for the human-readable PDF.
        """
        meta_resp = self._get(f"{DOCUMENT_API_BASE}/document/{document_id}")
        meta_resp.raise_for_status()
        meta = meta_resp.json()
        available = [r.get("content_type") for r in meta.get("resources", {}).values()] \
            if isinstance(meta.get("resources"), dict) else []
        content_resp = self.session.get(
            f"{DOCUMENT_API_BASE}/document/{document_id}/content",
            headers={"Accept": content_type},
            timeout=self.timeout,
            allow_redirects=True,
        )
        content_resp.raise_for_status()
        return content_resp.content
