"""Async client for the Brave Search API.

Provides current, factual, and real-world grounding for the Director agent when
the local LLM cannot reliably supply a fact (history, real people and places,
cultural/period accuracy, canonical poem text, or anything after the model's
training cutoff).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ..config import settings


class BraveSearchError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    @property
    def retryable(self) -> bool:
        return self.status_code == 429 or bool(
            self.status_code is not None and self.status_code >= 500
        )


@dataclass(frozen=True)
class BraveSearchResult:
    title: str
    url: str
    description: str
    snippets: tuple[str, ...]
    age: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "description": self.description,
            "snippets": list(self.snippets),
            "age": self.age,
        }


class BraveSearchClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_sec: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = (api_key or settings.brave_api_key or "").strip()
        self.base_url = (base_url or settings.brave_base_url).rstrip("/")
        self.timeout_sec = (
            settings.brave_search_timeout_sec
            if timeout_sec is None
            else float(timeout_sec)
        )
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise BraveSearchError(
                "Brave Search API key is not configured. Set DS_BRAVE_API_KEY "
                "(or BRAVE_API_KEY) before using web_search."
            )
        return {
            "X-Subscription-Token": self.api_key,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }

    async def search(
        self,
        query: str,
        *,
        count: int = 5,
        freshness: str | None = None,
        search_lang: str | None = None,
        country: str | None = None,
        safesearch: str = "moderate",
    ) -> list[BraveSearchResult]:
        params: dict[str, Any] = {
            "q": query,
            "count": max(1, min(int(count), 20)),
            "safesearch": safesearch,
        }
        if freshness:
            params["freshness"] = freshness
        if search_lang:
            params["search_lang"] = search_lang
        if country:
            params["country"] = country

        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=self.timeout_sec,
        ) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/res/v1/web/search",
                    headers=self._headers(),
                    params=params,
                )
            except httpx.HTTPError as exc:
                raise BraveSearchError(f"Brave Search request failed: {exc}") from exc

        self._raise_for_status(response)
        try:
            data = response.json()
        except ValueError as exc:
            raise BraveSearchError(
                "Brave Search returned a non-JSON response"
            ) from exc
        if not isinstance(data, dict):
            raise BraveSearchError("Brave Search returned an unexpected payload")
        return self._parse(data)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if status in (401, 403):
            raise BraveSearchError(
                "Brave Search rejected the API key (authentication).",
                status_code=status,
            )
        if status == 429:
            raise BraveSearchError(
                "Brave Search rate limit exceeded. Try again shortly.",
                status_code=status,
            )
        if status >= 400:
            raise BraveSearchError(
                f"Brave Search returned HTTP {status}.",
                status_code=status,
            )

    @staticmethod
    def _parse(data: dict[str, Any]) -> list[BraveSearchResult]:
        web = data.get("web")
        raw_results = web.get("results") if isinstance(web, dict) else None
        results: list[BraveSearchResult] = []
        if not isinstance(raw_results, list):
            return results
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            raw_snippets = item.get("extra_snippets")
            snippets: tuple[str, ...] = ()
            if isinstance(raw_snippets, list):
                snippets = tuple(
                    str(snippet).strip()
                    for snippet in raw_snippets
                    if isinstance(snippet, str) and str(snippet).strip()
                )
            results.append(
                BraveSearchResult(
                    title=str(item.get("title") or "").strip(),
                    url=str(item.get("url") or "").strip(),
                    description=str(item.get("description") or "").strip(),
                    snippets=snippets,
                    age=str(item.get("age") or item.get("page_age") or "").strip(),
                )
            )
        return results
