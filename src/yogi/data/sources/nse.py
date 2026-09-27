"""Resilient NSE archive source adapter with multi-tier fallback.

Handles network acquisition, session handshake, retry across mirrors,
and returns raw string data for consumption by pure normalizers.
"""

import logging
from typing import Optional, Sequence
import requests

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/json,text/plain,*/*",
    "Referer": "https://www.nseindia.com/",
}

FNO_LOTS_URLS = (
    "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv",
    "https://archives.nseindia.com/content/fo/fo_mktlots.csv",
)

ETF_URLS = (
    "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv",
    "https://archives.nseindia.com/content/equities/eq_etfseclist.csv",
)

SME_URLS = (
    "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv",
    "https://archives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv",
)

SERIES_URLS = (
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
)


class NseSourceAdapter:
    """Acquires authoritative CSV listings from NSE archive endpoints.

    Provides multi-tier fallback between official mirrors and returns raw payload strings.
    """

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 20.0,
    ) -> None:
        self._session = session
        self._headers = dict(headers or DEFAULT_HEADERS)
        self._timeout = timeout
        self._warmed_up = False

    def _get_session(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            s.headers.update(self._headers)
            self._session = s
        return self._session

    def _warmup(self, session: requests.Session) -> None:
        if not self._warmed_up:
            try:
                session.get("https://www.nseindia.com/", timeout=min(self._timeout, 10.0))
            except Exception as exc:
                logger.debug("NSE session warmup request failed: %s", exc)
            self._warmed_up = True

    def _fetch_from_urls(self, urls: Sequence[str], use_network: bool = True) -> Optional[str]:
        if not use_network:
            return None

        s = self._get_session()
        self._warmup(s)

        for url in urls:
            try:
                resp = s.get(url, timeout=self._timeout)
                resp.raise_for_status()
                text = resp.text
                if text and len(text.strip()) > 50:
                    return text
            except Exception as exc:
                logger.debug("Failed to fetch from %s: %s", url, exc)
                continue

        logger.warning("All NSE archive mirrors failed for request: %s", urls)
        return None

    def fetch_fno_lots_raw(self, use_network: bool = True) -> Optional[str]:
        """Fetch raw fo_mktlots.csv content from NSE mirrors."""
        return self._fetch_from_urls(FNO_LOTS_URLS, use_network=use_network)

    def fetch_etf_list_raw(self, use_network: bool = True) -> Optional[str]:
        """Fetch raw eq_etfseclist.csv content from NSE mirrors."""
        return self._fetch_from_urls(ETF_URLS, use_network=use_network)

    def fetch_sme_list_raw(self, use_network: bool = True) -> Optional[str]:
        """Fetch raw SME_EQUITY_L.csv content from NSE mirrors."""
        return self._fetch_from_urls(SME_URLS, use_network=use_network)

    def fetch_series_list_raw(self, use_network: bool = True) -> Optional[str]:
        """Fetch raw EQUITY_L.csv content from NSE mirrors."""
        return self._fetch_from_urls(SERIES_URLS, use_network=use_network)
