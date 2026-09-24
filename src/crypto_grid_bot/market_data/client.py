"""Bounded GET-only transport to Binance's unauthenticated data-only host."""

from __future__ import annotations

import http.client
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from crypto_grid_bot.market_data.parsing import DataError, symbol_name

HOST = "data-api.binance.vision"
MAX_BODY = 2_000_000
PATHS = {
    "/api/v3/time": frozenset(),
    "/api/v3/exchangeInfo": frozenset({"symbol"}),
    "/api/v3/klines": frozenset({"symbol", "interval", "limit", "endTime"}),
    "/api/v3/depth": frozenset({"symbol", "limit"}),
}


class FeedError(RuntimeError):
    """Network or exchange failure; no stale data fallback is permitted."""

    def __init__(self, message: str, retry_after: int = 0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


class Transport(Protocol):
    def __call__(self, path: str, params: dict[str, str]) -> Response: ...


def public_get(path: str, params: dict[str, str]) -> Response:
    """No configurable host, redirects, authentication headers or write method."""
    if path not in PATHS or set(params) != PATHS[path]:
        raise DataError("endpoint or parameters are outside the public-data allowlist")
    if "symbol" in params:
        symbol_name(params["symbol"])
    connection = http.client.HTTPSConnection(HOST, timeout=10)
    try:
        query = "?" + urlencode(params) if params else ""
        connection.request("GET", path + query, headers={"Accept": "application/json"})
        response = connection.getresponse()
        body = response.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise FeedError("public response exceeded size limit")
        return Response(response.status, {k.lower(): v for k, v in response.getheaders()}, body)
    except (OSError, http.client.HTTPException) as exc:
        raise FeedError("public market-data transport failed") from exc
    finally:
        connection.close()


class PublicClient:
    def __init__(
        self,
        transport: Transport = public_get,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._monotonic = monotonic
        self._blocked_until = 0.0

    def get(self, path: str, params: dict[str, str]) -> Any:
        if path not in PATHS or set(params) != PATHS[path]:
            raise DataError("request is outside the public-data allowlist")
        if self._monotonic() < self._blocked_until:
            raise FeedError("public API cooldown remains active")
        response = self._transport(path, params)
        if response.status in (418, 429):
            fallback = 172800 if response.status == 418 else 60
            raw = response.headers.get("retry-after", "")
            if not raw.isascii() or not raw.isdigit() or len(raw) > 9:
                seconds = fallback
            else:
                seconds = max(fallback, int(raw))
            self._blocked_until = self._monotonic() + seconds
            raise FeedError(f"public API returned HTTP {response.status}; capture stopped", seconds)
        if response.status != 200:
            raise FeedError(f"public API returned HTTP {response.status}; capture stopped")
        if len(response.body) > MAX_BODY:
            raise FeedError("public response exceeded size limit")
        try:
            payload = json.loads(response.body)
        except (ValueError, UnicodeError) as exc:
            raise DataError("public response is not valid JSON") from exc
        if isinstance(payload, dict) and "code" in payload:
            raise FeedError("exchange returned an API error payload")
        return payload
