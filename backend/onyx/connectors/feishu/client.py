"""Bounded, authenticated requests to the official mainland Feishu API."""

import re
import time
from collections.abc import Iterator
from typing import Any, cast
from urllib.parse import urlsplit

import requests

from onyx.connectors.exceptions import CredentialInvalidError

API_ORIGIN = "https://open.feishu.cn"
MAX_ATTEMPTS = 5
REQUEST_TIMEOUT = (5, 45)
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
TOKEN_ERROR_CODES = {99991661, 99991663, 99991664, 99991668}
RETRY_ERROR_CODES = {99991400, 99991401, 99991402}


class FeishuAPIError(RuntimeError):
    """Expose only status codes, never tokens or upstream response bodies."""


def api_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Feishu IDs must contain only letters, numbers, '_' or '-'.")
    return value


def trusted_feishu_url(value: str) -> str:
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not hostname.endswith(".feishu.cn")
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Use an HTTPS URL on a Feishu tenant domain.")
    return value.rstrip("/")


def require_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FeishuAPIError("Feishu returned an invalid object.")
    return cast(dict[str, Any], value)


def require_items(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = data.get(key)
    if not isinstance(values, list):
        raise FeishuAPIError(f"Feishu response has no {key} list.")
    return [require_object(value) for value in values]


class FeishuClient:
    def __init__(self, app_id: str, app_secret: str) -> None:
        if not app_id or not app_secret:
            raise CredentialInvalidError("Feishu App ID and App Secret are required.")
        self._app_id = app_id
        self._app_secret = app_secret
        self._token = ""
        self._token_expires_at = 0.0
        self._session = requests.Session()

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        body: dict[str, Any] | None = None,
        authenticated: bool = True,
        stream: bool = False,
    ) -> requests.Response:
        # Never accept caller-controlled origins or follow download redirects.
        if not path.startswith("/open-apis/") or ".." in path or "?" in path:
            raise ValueError("Invalid Feishu API path.")
        if authenticated:
            self.refresh_token()
        for attempt in range(MAX_ATTEMPTS):
            headers = (
                {"Authorization": f"Bearer {self._token}"} if authenticated else {}
            )
            try:
                response = self._session.request(
                    method,
                    API_ORIGIN + path,
                    headers=headers,
                    params=params,
                    json=body,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=False,
                    stream=stream,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt == MAX_ATTEMPTS - 1:
                    raise FeishuAPIError(
                        "Feishu request timed out or failed to connect."
                    ) from exc
                time.sleep(min(2**attempt, 16))
                continue
            if response.status_code == 401 and authenticated and attempt == 0:
                response.close()
                self.refresh_token(force=True)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                retry_after = response.headers.get("Retry-After", "")
                response.close()
                if attempt < MAX_ATTEMPTS - 1:
                    delay = (
                        float(retry_after) if retry_after.isdecimal() else 2**attempt
                    )
                    time.sleep(min(delay, 30))
                    continue
            if not 200 <= response.status_code < 300:
                response.close()
                raise FeishuAPIError(
                    f"Feishu HTTP request failed ({response.status_code})."
                )
            return response
        raise FeishuAPIError("Feishu request retries exhausted.")

    @staticmethod
    def _envelope(response: requests.Response) -> dict[str, Any]:
        try:
            result = require_object(response.json())
        except ValueError as exc:
            raise FeishuAPIError("Feishu returned invalid JSON.") from exc
        finally:
            response.close()
        if not isinstance(result.get("code"), int):
            raise FeishuAPIError("Feishu response has no API status code.")
        return result

    def refresh_token(self, force: bool = False) -> None:
        if not force and self._token and time.monotonic() < self._token_expires_at:
            return
        result = self._envelope(
            self._send(
                "POST",
                "/open-apis/auth/v3/tenant_access_token/internal",
                body={"app_id": self._app_id, "app_secret": self._app_secret},
                authenticated=False,
            )
        )
        token, expiry = result.get("tenant_access_token"), result.get("expire")
        if (
            result["code"] != 0
            or not isinstance(token, str)
            or not isinstance(expiry, int)
            or expiry <= 0
        ):
            raise CredentialInvalidError(
                "Feishu could not issue a tenant access token."
            )
        self._token = token
        self._token_expires_at = time.monotonic() + max(1, expiry - 60)

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        params: dict[str, str | int] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        refreshed = False
        for attempt in range(MAX_ATTEMPTS):
            result = self._envelope(self._send(method, path, params=params, body=body))
            code = result["code"]
            if code in TOKEN_ERROR_CODES and not refreshed:
                self.refresh_token(force=True)
                refreshed = True
                continue
            if code in RETRY_ERROR_CODES and attempt < MAX_ATTEMPTS - 1:
                time.sleep(min(2**attempt, 16))
                continue
            if code != 0:
                raise FeishuAPIError(f"Feishu API request failed (code {code}).")
            return require_object(result.get("data"))
        raise FeishuAPIError("Feishu API retries exhausted.")

    def iterate(
        self,
        path: str,
        key: str = "items",
        params: dict[str, str | int] | None = None,
        page_size: int = 100,
    ) -> Iterator[dict[str, Any]]:
        query = dict(params or {})
        query["page_size"] = page_size
        seen_page_tokens: set[str] = set()
        while True:
            data = self.request(path, params=query)
            yield from require_items(data, key)
            if data.get("has_more") is False:
                return
            if data.get("has_more") is not True:
                raise FeishuAPIError("Feishu response has no pagination state.")
            page_token = data.get("page_token") or data.get("next_page_token")
            if (
                not isinstance(page_token, str)
                or not page_token
                or page_token in seen_page_tokens
            ):
                raise FeishuAPIError("Feishu pagination token is missing or repeated.")
            seen_page_tokens.add(page_token)
            query["page_token"] = page_token

    def download_file(self, token: str) -> bytes:
        response = self._send(
            "GET",
            f"/open-apis/drive/v1/files/{api_identifier(token)}/download",
            stream=True,
        )
        try:
            if "json" in response.headers.get("Content-Type", ""):
                raise FeishuAPIError("Feishu file download returned an API error.")
            content = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                content.extend(chunk)
                if len(content) > MAX_DOWNLOAD_BYTES:
                    raise FeishuAPIError(
                        "Feishu file exceeds the 50 MiB download limit."
                    )
            return bytes(content)
        finally:
            response.close()
