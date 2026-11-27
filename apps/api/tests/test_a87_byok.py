"""A8.7 (M11.2 BYOK): users' own keys, encrypted, and the OpenAI-compatible adapter."""

from __future__ import annotations

import logging

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlmodel import Session, select

from stockviz.models import UserAiKey
from stockviz.services.ai import keys
from stockviz.services.ai.openai_compat import OpenAICompatibleProvider, check_base_url
from stockviz.services.ai.provider import AiProviderError, Message
from stockviz.services.delivery import transport
from tests.test_drills import _auth, _user

SECRET = "sk-test-abcdef123456WXYZ"


class S:
    def __init__(self, key: str | None = None, production: bool = False) -> None:
        self.app_encryption_key = SecretStr(
            key if key is not None else Fernet.generate_key().decode()
        )
        self.is_production = production
        self.ollama_model = ""
        self.ollama_url = ""


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch) -> None:
    monkeypatch.setattr(transport, "resolve", lambda host, port: ["93.184.216.34"])


def test_saved_keys_are_encrypted_listed_without_the_key_and_isolated(session: Session) -> None:
    settings = S()
    alice, bob = _user(session, "alice@stockviz.dev"), _user(session, "bob@stockviz.dev")
    saved = keys.save_key(session, settings, alice, "openai_compatible", api_key=SECRET,
                          model="gpt-test", base_url="https://api.example.com/v1/")  # fmt: skip
    assert saved.key_last4 == "WXYZ" and saved.base_url == "https://api.example.com/v1"
    row = session.exec(select(UserAiKey)).one()
    assert SECRET not in row.ciphertext and "WXYZ" not in row.ciphertext
    assert keys.list_keys(session, bob) == []
    p = keys.provider_for(session, settings, alice, "openai_compatible")
    assert isinstance(p, OpenAICompatibleProvider) and p.api_key == SECRET
    assert SECRET not in repr(p)
    with pytest.raises(keys.KeyMissing):
        keys.provider_for(session, settings, bob, "openai_compatible")
    # Saving again replaces; a new server key makes it unreadable.
    keys.save_key(session, settings, alice, "openai_compatible", api_key=SECRET + "9",
                  model="gpt-2", base_url="https://api.example.com/v1")  # fmt: skip
    assert len(session.exec(select(UserAiKey)).all()) == 1
    with pytest.raises(keys.KeysOff, match="save it again"):
        keys.provider_for(session, S(), alice, "openai_compatible")
    keys.delete_key(session, alice, "openai_compatible")
    with pytest.raises(keys.KeyMissing):
        keys.delete_key(session, alice, "openai_compatible")


def test_refusals(session: Session) -> None:
    uid = _user(session, "r@stockviz.dev")
    with pytest.raises(keys.KeysOff, match="APP_ENCRYPTION_KEY"):
        keys.save_key(session, S(""), uid, "openai_compatible", api_key=SECRET, model="m",
                      base_url="https://api.example.com/v1")  # fmt: skip
    with pytest.raises(keys.KeysOff, match="not a valid"):
        keys.save_key(session, S("short"), uid, "openai_compatible", api_key=SECRET, model="m",
                      base_url="https://api.example.com/v1")  # fmt: skip
    with pytest.raises(keys.KeyError_, match="anthropic SDK"):
        keys.save_key(session, S(), uid, "anthropic", api_key=SECRET, model="m", base_url=None)
    with pytest.raises(keys.KeyError_, match="incomplete"):
        keys.save_key(session, S(), uid, "openai_compatible", api_key="sk 1234 5678", model="m",
                      base_url="https://api.example.com/v1")  # fmt: skip
    assert not keys.keys_available(S("")) and keys.keys_available(S())


@pytest.mark.parametrize(
    ("url", "problem"),
    [
        ("http://api.example.com/v1", "https"),
        ("https://user:pw@api.example.com/v1", "user name or password"),
        ("https://10.0.0.5/v1", "private address"),
        ("https://api.example.com/v1?key=x", "query"),
        ("", "base URL"),
    ],
)
def test_base_url_rules(url: str, problem: str) -> None:
    with pytest.raises(keys.KeyError_, match=problem):
        check_base_url(url, local_allowed=True)


def test_local_endpoint_only_outside_production() -> None:
    assert (
        check_base_url("http://localhost:1234/v1", local_allowed=True) == "http://localhost:1234/v1"
    )
    with pytest.raises(keys.KeyError_, match="local"):
        check_base_url("http://localhost:1234/v1", local_allowed=False)


def _provider(response: httpx.Response | Exception, sent: list) -> OpenAICompatibleProvider:
    def send(target, headers, body, extensions):
        sent.append((target, headers, body, extensions))
        if isinstance(response, Exception):
            raise response
        return response

    return OpenAICompatibleProvider(model="gpt-test", base_url="https://api.example.com/v1",
                                    api_key=SECRET, send=send)  # fmt: skip


def test_adapter_shape_pinning_and_errors(monkeypatch, caplog) -> None:
    sent: list = []
    ok = httpx.Response(200, json={"choices": [{"message": {"content": "hello [1]"}}]})
    p = _provider(ok, sent)
    assert p.complete([Message("system", "rules"), Message("user", "q")]) == "hello [1]"
    target, headers, body, extensions = sent[0]
    assert target == "https://93.184.216.34/v1/chat/completions"  # the checked address
    assert headers["Host"] == "api.example.com" and extensions == {
        "sni_hostname": "api.example.com"
    }
    assert headers["Authorization"] == f"Bearer {SECRET}"
    assert body["messages"][0] == {"role": "system", "content": "rules"}
    with caplog.at_level(logging.DEBUG):
        for response, msg in [
            (httpx.Response(401), "refused the key"),
            (httpx.Response(429), "rate limit"),
            (httpx.Response(302), "redirect"),
            (httpx.Response(500, text=f"echo {SECRET}"), "HTTP 500"),
            (httpx.Response(200, json={"nope": 1}), "chat-completions shape"),
            (httpx.ConnectError("x"), "not reachable"),
            (httpx.ReadTimeout("x"), "timed out"),
        ]:
            with pytest.raises(AiProviderError, match=msg) as err:
                _provider(response, []).complete([Message("user", "q")])
            assert SECRET not in str(err.value)
    assert SECRET not in caplog.text
    monkeypatch.setattr(transport, "resolve", lambda host, port: ["192.168.1.9"])
    with pytest.raises(AiProviderError, match="private address"):
        _provider(ok, []).complete([Message("user", "q")])


def test_routes(client: TestClient, session: Session, monkeypatch) -> None:
    settings = S()
    monkeypatch.setattr("stockviz.routers.ai.get_settings", lambda: settings)
    uid = _user(session, "k@stockviz.dev")
    h = _auth(uid)
    assert client.get("/v1/ai/keys").status_code == 401
    listed = client.get("/v1/ai/keys", headers=h).json()
    assert listed["available"] and listed["keys"] == [] and "anthropic" in listed["held"]
    body = {"api_key": SECRET, "model": "gpt-test", "base_url": "https://api.example.com/v1"}
    res = client.put("/v1/ai/keys/openai_compatible", json=body, headers=h)
    assert res.status_code == 200 and res.json()["key_last4"] == "WXYZ"
    assert SECRET not in res.text and SECRET not in client.get("/v1/ai/keys", headers=h).text
    assert client.put("/v1/ai/keys/anthropic", json=body, headers=h).status_code == 422
    bad = {**body, "base_url": "https://10.0.0.1/v1"}
    assert client.put("/v1/ai/keys/openai_compatible", json=bad, headers=h).status_code == 422

    # The copilot and the rule draft use the saved key when asked to.
    seen: list[str] = []

    def fake_complete(self, messages, *, temperature=0.0):
        seen.append(self.model)
        return "The stored documents do not cover this."

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", fake_complete)
    monkeypatch.setattr("stockviz.routers.ai.embedder_from_settings", lambda _s: None)
    from datetime import datetime

    from tests.symbols import seed_symbols
    from tests.test_a84_hybrid_search import _doc

    seed_symbols(session, "TCS.NS", currency="INR")
    _doc(session, "TCS.NS", "Q2", "Borrowings were repaid in full.", datetime(2026, 10, 9))
    ask = {"question": "what about borrowings", "provider": "openai_compatible"}
    res = client.post("/v1/ai/ask", json=ask, headers=h)
    assert res.status_code == 200 and res.json()["provider"] == "openai_compatible"
    assert seen == ["gpt-test"]
    other = _auth(_user(session, "nokey@stockviz.dev"))
    assert client.post("/v1/ai/ask", json=ask, headers=other).status_code == 409

    assert client.delete("/v1/ai/keys/openai_compatible", headers=h).status_code == 204
    assert client.delete("/v1/ai/keys/openai_compatible", headers=h).status_code == 404
    off = S("")
    monkeypatch.setattr("stockviz.routers.ai.get_settings", lambda: off)
    assert client.put("/v1/ai/keys/openai_compatible", json=body, headers=h).status_code == 409
    assert client.get("/v1/ai/status").json()["keys_available"] is False
