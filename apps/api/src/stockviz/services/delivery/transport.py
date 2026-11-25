"""The network edges of delivery (A2.3), kept in one place so tests stub them.

Tests replace :func:`http_client`, :func:`resolve` and :func:`email_sender`;
nothing in the test suite reaches the network.
"""

from __future__ import annotations

import smtplib
import socket
import ssl
from email.message import EmailMessage
from typing import Protocol

import httpx

from stockviz.settings import get_settings

TIMEOUT_SECONDS = 5.0
"""Every webhook and Telegram request gives up after this."""

SMTP_TIMEOUT_SECONDS = 10.0


def http_client() -> httpx.Client:
    """A client that never follows a redirect (a redirect could point inside)."""
    return httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)


def resolve(host: str, port: int) -> list[str]:
    """Every address ``host`` resolves to (A and AAAA)."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


class EmailSender(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> None: ...


class SmtpError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class SmtpSender:
    """Plain SMTP with STARTTLS (or implicit TLS on port 465), any provider."""

    def __init__(self, host: str, port: int, user: str, password: str, sender: str) -> None:
        self.host, self.port, self.user = host, port, user
        self._password = password
        self.sender = sender

    def send(self, *, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        context = ssl.create_default_context()
        try:
            if self.port == 465:
                with smtplib.SMTP_SSL(
                    self.host, self.port, timeout=SMTP_TIMEOUT_SECONDS, context=context
                ) as smtp:
                    smtp.login(self.user, self._password)
                    smtp.send_message(message)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
                    smtp.starttls(context=context)
                    smtp.login(self.user, self._password)
                    smtp.send_message(message)
        except smtplib.SMTPRecipientsRefused as exc:
            raise SmtpError("the mail server refused the address", retryable=False) from exc
        except smtplib.SMTPAuthenticationError as exc:
            raise SmtpError("the mail server refused the login", retryable=True) from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise SmtpError(f"mail send failed ({type(exc).__name__})", retryable=True) from exc


def email_sender() -> EmailSender | None:
    """The configured sender, or None when any SMTP_* value is missing."""
    s = get_settings()
    if not s.email_configured:
        return None
    return SmtpSender(
        s.smtp_host.strip(),
        s.smtp_port_number,
        s.smtp_user.strip(),
        s.smtp_password.get_secret_value(),
        s.smtp_from.strip(),
    )
