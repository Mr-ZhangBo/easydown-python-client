"""Synchronous, server-side client for EasyDown public-media parsing."""

from __future__ import annotations

import json
import math
import socket
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

__version__ = "0.1.0"
__all__ = ["EasyDownClient", "EasyDownError", "HttpResponse", "PLATFORMS"]

PLATFORMS = (
    "tiktok", "douyin", "toutiao", "youtube", "twitter", "instagram",
    "threads", "xiaohongshu", "bilibili", "kuaishou", "weibo",
)
_API = "https://api.easydown.org"
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_CODES = {
    "platform_mismatch", "unsupported_url", "content_unavailable", "no_media",
    "upstream_unavailable", "platform_not_allowed", "insufficient_credits",
}


class EasyDownError(Exception):
    """Safe error categories; raw bodies, URLs and credentials are omitted."""

    def __init__(self, kind: str, http_status: int | None = None,
                 code: str | None = None) -> None:
        self.kind = kind
        self.http_status = http_status
        self.code = code if isinstance(code, str) and code in _CODES else None
        suffix = "" if http_status is None else f" (HTTP {http_status})"
        super().__init__(f"EasyDown request failed: {kind}{suffix}")


@dataclass(frozen=True)
class HttpResponse:
    """Response returned by a trusted transport; never log the raw body."""

    status: int
    body: bytes


Transport = Callable[[Request, float], HttpResponse]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int,
                         msg: str, headers: Any, newurl: str) -> None:
        # Never forward Bearer credentials to a redirected destination.
        return None


def _http_transport(request: Request, timeout: float) -> HttpResponse:
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            body = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(body) > _MAX_RESPONSE_BYTES:
                raise EasyDownError("invalid_response", response.status)
            return HttpResponse(response.status, body)
    except HTTPError as error:
        status = error.code
        error.close()
        raise EasyDownError("http", status) from None
    except (TimeoutError, socket.timeout):
        raise EasyDownError("timeout") from None
    except URLError as error:
        kind = "timeout" if isinstance(error.reason, TimeoutError) else "network"
        raise EasyDownError(kind) from None


def _number(value: Any) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _headers(value: dict[str, Any]) -> bool:
    return "headers" not in value or (
        isinstance(value["headers"], dict)
        and all(isinstance(k, str) and isinstance(v, str)
                for k, v in value["headers"].items())
    )


def _image(value: Any) -> bool:
    return (isinstance(value, dict) and isinstance(value.get("url"), str)
            and _number(value.get("width")) and _number(value.get("height")))


def _video(value: Any) -> bool:
    return (_image(value) and isinstance(value.get("quality"), str)
            and isinstance(value.get("mimeType"), str)
            and isinstance(value.get("hasAudio"), bool)
            and value.get("source") in ("direct", "adaptive", "dash", "live_photo")
            and _headers(value))


def _audio(value: Any) -> bool:
    return (isinstance(value, dict) and isinstance(value.get("url"), str)
            and isinstance(value.get("quality"), str)
            and isinstance(value.get("mimeType"), str)
            and _number(value.get("bitrate"))
            and value.get("source") in ("direct", "adaptive", "dash", "native_voice")
            and _headers(value))


def _media(value: Any) -> bool:
    return (isinstance(value, dict) and value.get("platform") in PLATFORMS
            and isinstance(value.get("title"), str)
            and isinstance(value.get("thumbnail"), str)
            and _number(value.get("duration"))
            and isinstance(value.get("images"), list)
            and all(_image(v) for v in value["images"])
            and isinstance(value.get("videos"), list)
            and all(_video(v) for v in value["videos"])
            and isinstance(value.get("audios"), list)
            and all(_audio(v) for v in value["audios"]))


def _post_url(value: str) -> str:
    message = "Provide an absolute public HTTP(S) post URL without credentials."
    if not isinstance(value, str) or not value or any(ord(c) <= 32 for c in value):
        raise ValueError(message)
    try:
        parts = urlsplit(value)
        valid = (parts.scheme in ("https", "http") and bool(parts.hostname)
                 and parts.username is None and parts.password is None)
        parts.port  # Reject invalid ports before making a request.
    except ValueError:
        raise ValueError(message) from None
    if not valid:
        raise ValueError(message)
    return value


class EasyDownClient:
    """Calls the fixed official host. No automatic retries or media downloads.

    A custom transport receives the Bearer credential: supply only trusted code.
    Timeout is a per-socket timeout, not a total request deadline.
    """

    __slots__ = ("__token", "__timeout", "__transport")

    def __init__(self, token: str, *, timeout: float = 60.0,
                 transport: Transport | None = None) -> None:
        if (not isinstance(token, str) or not token.strip()
                or any(ord(c) < 32 or ord(c) > 126 for c in token)):
            raise ValueError("Provide a non-empty ASCII API token without control characters.")
        if not _number(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive, finite number of seconds.")
        if transport is not None and not callable(transport):
            raise TypeError("transport must be a trusted callable.")
        self.__token = token.strip()
        self.__timeout = float(timeout)
        self.__transport = _http_transport if transport is None else transport

    def __repr__(self) -> str:
        return "EasyDownClient(token=<redacted>)"

    def parse(self, url: str) -> dict[str, Any]:
        """POST /api/v1/parse; returns normalized data directly."""
        data = self.__request("/api/v1/parse", _post_url(url))
        if not _media(data):
            raise EasyDownError("invalid_response", 200)
        return data

    def parse_platform(self, platform: str, url: str) -> dict[str, Any]:
        """Returns media plus unmodified platformData and its version."""
        if not isinstance(platform, str) or platform not in PLATFORMS:
            raise ValueError("Unsupported platform endpoint name.")
        data = self.__request(f"/api/v1/platforms/{platform}/parse", _post_url(url))
        if (not _media(data.get("media"))
                or data["media"]["platform"] != platform
                or not isinstance(data.get("platformData"), dict)
                or not isinstance(data.get("platformDataVersion"), str)):
            raise EasyDownError("invalid_response", 200)
        return data

    def __request(self, path: str, url: str) -> dict[str, Any]:
        request = Request(
            _API + path,
            data=json.dumps({"url": url}).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.__token}",
                     "Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            response = self.__transport(request, self.__timeout)
        except EasyDownError:
            raise
        except TimeoutError:
            raise EasyDownError("timeout") from None
        except Exception:
            raise EasyDownError("network") from None
        if (not isinstance(response, HttpResponse) or type(response.status) is not int
                or not isinstance(response.body, bytes)):
            raise EasyDownError("invalid_response")
        if not 200 <= response.status < 300:
            raise EasyDownError("http", response.status)
        if len(response.body) > _MAX_RESPONSE_BYTES:
            raise EasyDownError("invalid_response", response.status)
        try:
            body = json.loads(response.body)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise EasyDownError("invalid_response", response.status) from None
        if not isinstance(body, dict) or not _number(body.get("status")):
            raise EasyDownError("invalid_response", response.status)
        if body["status"] != 200:
            raise EasyDownError("api", response.status, body.get("code"))
        if body.get("msg") != "success" or not isinstance(body.get("data"), dict):
            raise EasyDownError("invalid_response", response.status)
        return body["data"]
