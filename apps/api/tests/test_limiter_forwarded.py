"""The limiter keys on the proxy-added X-Forwarded-For hop, not the client's."""

from __future__ import annotations

import pytest

from stockviz.limiter import forwarded_client, trusted_proxy_hops


def test_client_chosen_left_entry_is_ignored() -> None:
    # A client sends "203.0.113.5"; our proxy appends what it saw.
    assert forwarded_client("203.0.113.5, 198.51.100.7", hops=1) == "198.51.100.7"
    assert forwarded_client("198.51.100.8", hops=1) == "198.51.100.8"


def test_hops_count_from_the_right() -> None:
    chain = "203.0.113.1, 10.0.0.2, 10.0.0.3"
    assert forwarded_client(chain, hops=2) == "10.0.0.2"
    assert forwarded_client(chain, hops=9) == "203.0.113.1"
    assert forwarded_client(chain, hops=0) is None
    assert forwarded_client(None, hops=1) is None
    assert forwarded_client(" , ", hops=1) is None


@pytest.mark.parametrize(("raw", "hops"), [("", 1), ("2", 2), ("0", 0), ("junk", 1), ("-3", 1)])
def test_trusted_proxy_hops(raw: str, hops: int) -> None:
    assert trusted_proxy_hops(raw) == hops
