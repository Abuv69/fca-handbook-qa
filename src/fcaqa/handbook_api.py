"""Client for the FCA Handbook API.

IMPORTANT: the API reference sits behind the Handbook sign-in, so the endpoint
path and response shape here are configuration, not facts. Before the first real
ingest:

1. Sign in at handbook.fca.org.uk, open the Handbook API page and read the docs.
2. Put the base URL, your token and the provisions path in .env.
3. Run `python -m fcaqa probe "<path>"` to see the shape of one response.
4. Adjust FIELD_MAP in parse.py and `next_page` below if they do not match.

Use the API only. The FCA's site terms do not allow scraping the website.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from .config import Settings, get_settings

RETRY_STATUSES = {429, 500, 502, 503, 504}


class HandbookApiError(RuntimeError):
    pass


class HandbookClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        auth_header: str = "Authorization",
        auth_prefix: str = "Bearer",
        delay_seconds: float = 1.0,
        max_retries: int = 5,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ) -> None:
        if not base_url or not token:
            raise HandbookApiError("Set FCA_API_BASE_URL and FCA_API_TOKEN in your .env file first.")
        value = f"{auth_prefix} {token}".strip() if auth_prefix else token
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={auth_header: value, "Accept": "application/json"},
            timeout=30.0,
            transport=transport,
        )
        self._delay = delay_seconds
        self._max_retries = max_retries
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "HandbookClient":
        s = settings or get_settings()
        return cls(
            base_url=s.fca_api_base_url,
            token=s.fca_api_token,
            auth_header=s.fca_api_auth_header,
            auth_prefix=s.fca_api_auth_prefix,
            delay_seconds=s.fca_api_delay_seconds,
        )

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET one URL. Retries politely on rate limits and server errors."""
        for attempt in range(self._max_retries + 1):
            response = self._client.get(path, params=params)
            if response.status_code in RETRY_STATUSES and attempt < self._max_retries:
                retry_after = response.headers.get("Retry-After", "")
                wait = float(retry_after) if retry_after.isdigit() else min(60.0, 2.0 ** attempt)
                self._sleep(wait)
                continue
            if response.status_code in (401, 403):
                raise HandbookApiError(
                    f"{response.status_code} from the API: check FCA_API_TOKEN, FCA_API_AUTH_HEADER "
                    "and FCA_API_AUTH_PREFIX against the API portal docs."
                )
            if response.status_code >= 400:
                raise HandbookApiError(f"{response.status_code} from {path}: {response.text[:200]}")
            return response.json()
        raise HandbookApiError(f"Gave up on {path} after {self._max_retries} retries.")

    @staticmethod
    def next_page(payload: Any) -> str | None:
        """URL or path of the next page, or None when there are no more.

        TODO(you): match this to the pagination the API docs describe.
        """
        if not isinstance(payload, dict):
            return None
        links = payload.get("links") if isinstance(payload.get("links"), dict) else {}
        candidate = payload.get("next") or payload.get("nextPage") or links.get("next")
        return candidate if isinstance(candidate, str) and candidate else None

    def fetch_pages(self, path: str, max_pages: int = 500) -> list[Any]:
        """Follow pagination from `path` and return every page's raw payload."""
        pages: list[Any] = []
        current: str | None = path
        while current and len(pages) < max_pages:
            payload = self.get_json(current)
            pages.append(payload)
            current = self.next_page(payload)
            if current:
                self._sleep(self._delay)  # stay well inside the rate limit
        return pages

    def fetch_sourcebook(self, sourcebook: str, path_template: str | None = None) -> list[Any]:
        template = path_template or get_settings().fca_api_provisions_path
        if not template:
            raise HandbookApiError(
                "Set FCA_API_PROVISIONS_PATH in .env, e.g. a path containing {sourcebook}."
            )
        return self.fetch_pages(template.format(sourcebook=sourcebook))

    def close(self) -> None:
        self._client.close()


def describe(value: Any, depth: int = 0, max_depth: int = 4) -> str:
    """Summarise the shape of a JSON value without printing its content."""
    pad = "  " * depth
    if isinstance(value, dict):
        if depth >= max_depth:
            return f"{pad}{{...{len(value)} keys}}"
        lines = []
        for key, item in list(value.items())[:25]:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(describe(item, depth + 1, max_depth))
            else:
                sample = str(item)[:50].replace("\n", " ")
                lines.append(f"{pad}{key}: {type(item).__name__} = {sample!r}")
        return "\n".join(lines)
    if isinstance(value, list):
        head = f"{pad}list of {len(value)}"
        if value and depth < max_depth:
            return head + ", first item:\n" + describe(value[0], depth + 1, max_depth)
        return head
    return f"{pad}{type(value).__name__} = {str(value)[:50]!r}"
