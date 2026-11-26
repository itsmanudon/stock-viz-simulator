"""The three senders (A2.3): signed webhook, email, Telegram.

Each takes a payload and raises :class:`DeliveryError` with ``retryable``
set when it fails. Error text never carries a secret, a token or a URL.

**Webhook.** ``POST`` the JSON payload (compact, keys sorted) with
``X-StockViz-Signature: sha256=<hex HMAC-SHA256 of the body bytes under the
user's secret>`` and ``X-StockViz-Timestamp`` (Unix seconds). Rules against
server-side request forgery, checked on every send:

- ``https`` only. ``http`` is allowed for ``localhost``, ``127.0.0.1`` and
  ``::1`` outside production, and only there may a loopback address be used.
- No credentials in the URL.
- The host is resolved and **every** address must be public: private,
  loopback, link-local, carrier-grade NAT, multicast, reserved and
  unspecified addresses are refused (IPv4-mapped IPv6 is unwrapped first).
- The request goes to the checked address (the host stays in ``Host`` and
  in TLS SNI and certificate checks), so a second DNS answer cannot swap it.
- Redirects are never followed: a 3xx is a permanent failure.
- 5 s timeout. 2xx is sent; 408, 429 and 5xx retry; other 4xx are permanent.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from stockviz.services.delivery import transport
from stockviz.settings import get_settings

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
SIGNATURE_HEADER = "X-StockViz-Signature"
TIMESTAMP_HEADER = "X-StockViz-Timestamp"
USER_AGENT = "StockViz-Webhook/1"
TELEGRAM_API = "https://api.telegram.org"
TELEGRAM_MAX_TEXT = 4000


class DeliveryError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


def body_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode()


def signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _local_allowed() -> bool:
    return not get_settings().is_production


def check_url_syntax(url: str) -> str:
    """The URL rules that need no DNS (used when the user saves it)."""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        _port = parts.port
    except ValueError as exc:
        raise DeliveryError("the webhook URL is not valid", retryable=False) from exc
    if parts.scheme not in ("https", "http") or not host:
        raise DeliveryError("the webhook URL must start with https://", retryable=False)
    if parts.username or parts.password:
        raise DeliveryError(
            "the webhook URL must not hold a user name or password", retryable=False
        )
    local = host in LOCAL_HOSTS
    if local and not _local_allowed():
        raise DeliveryError("a local webhook is allowed only in development", retryable=False)
    if parts.scheme == "http" and not local:
        raise DeliveryError("the webhook URL must use https", retryable=False)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not local and not _public(literal):
        raise DeliveryError("the webhook URL points at a private address", retryable=False)
    return url.strip()


def _public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def pinned_target(url: str) -> tuple[str, str]:
    """Check ``url`` and resolve it: (URL with the checked address, host).

    Raises :class:`DeliveryError` (permanent) when any address is not public.
    """
    check_url_syntax(url)
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    port = parts.port or (443 if parts.scheme == "https" else 80)
    local = host in LOCAL_HOSTS
    try:
        addresses = transport.resolve(host, port)
    except OSError as exc:
        raise DeliveryError("the webhook host did not resolve", retryable=True) from exc
    if not addresses:
        raise DeliveryError("the webhook host did not resolve", retryable=True)
    for raw in addresses:
        ip = ipaddress.ip_address(raw.split("%", 1)[0])
        if local and ip.is_loopback:
            continue
        if not _public(ip):
            raise DeliveryError("the webhook host resolves to a private address", retryable=False)
    chosen = addresses[0].split("%", 1)[0]
    netloc_host = f"[{chosen}]" if ":" in chosen else chosen
    netloc = f"{netloc_host}:{parts.port}" if parts.port else netloc_host
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, "")), host


def _classify(status: int, what: str) -> None:
    if 200 <= status < 300:
        return
    if 300 <= status < 400:
        raise DeliveryError(
            f"{what} answered {status}: redirects are not followed", retryable=False
        )
    retryable = status in (408, 429) or status >= 500
    raise DeliveryError(f"{what} answered HTTP {status}", retryable=retryable)


def send_webhook(url: str, secret: str, payload: dict[str, Any]) -> None:
    if not secret:
        raise DeliveryError("the webhook has no secret", retryable=False)
    target, host = pinned_target(url)
    body = body_bytes(payload)
    headers = {
        "Host": host if urlsplit(url).port is None else f"{host}:{urlsplit(url).port}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        SIGNATURE_HEADER: signature(secret, body),
        TIMESTAMP_HEADER: str(int(time.time())),
    }
    extensions = {"sni_hostname": host} if urlsplit(url).scheme == "https" else {}
    try:
        with transport.http_client() as client:
            response = client.post(target, content=body, headers=headers, extensions=extensions)
    except httpx.TimeoutException as exc:
        raise DeliveryError("the webhook timed out", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise DeliveryError(f"the webhook failed ({type(exc).__name__})", retryable=True) from exc
    _classify(response.status_code, "the webhook")


def send_telegram(chat_id: str, text: str) -> None:
    token = get_settings().telegram_bot_token.get_secret_value().strip()
    if not token:
        raise DeliveryError("Telegram is not available on this server", retryable=False)
    try:
        with transport.http_client() as client:
            response = client.post(
                f"{TELEGRAM_API}/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text[:TELEGRAM_MAX_TEXT],
                    "disable_web_page_preview": True,
                },
            )
    except httpx.TimeoutException as exc:
        raise DeliveryError("Telegram timed out", retryable=True) from exc
    except httpx.HTTPError as exc:  # the message would hold the URL, so the token
        raise DeliveryError(f"Telegram failed ({type(exc).__name__})", retryable=True) from exc
    _classify(response.status_code, "Telegram")


def send_email(to: str, subject: str, body: str) -> None:
    sender = transport.email_sender()
    if sender is None:
        raise DeliveryError("email is not available on this server", retryable=False)
    try:
        sender.send(to=to, subject=subject, body=body)
    except transport.SmtpError as exc:
        raise DeliveryError(str(exc), retryable=exc.retryable) from exc


__all__ = [
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "DeliveryError",
    "body_bytes",
    "check_url_syntax",
    "pinned_target",
    "send_email",
    "send_telegram",
    "send_webhook",
    "signature",
]
