"""Synthetic builders + fakes for the M2.1 live-book tests. Not collected by pytest.

Obviously synthetic tickers / slugs / credentials; hand-built domain objects,
frames, and in-memory transport / snapshot / signer fakes.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from prediction_market_arbitrage.domain import Contract, Market, PriceLevel, Venue
from prediction_market_arbitrage.livebook import BookSnapshot, Handshake
from prediction_market_arbitrage.livebook.transport import TransportClosed

KALSHI_VENUE = Venue(id="kalshi", name="Kalshi")
POLY_VENUE = Venue(id="polymarket_us", name="Polymarket US")

KALSHI_TICKER = "LIVEBOOK-TEST-T1"
POLY_SLUG = "livebook-test-market"

T0 = datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)


def _market(venue: Venue, market_id: str) -> Market:
    return Market(venue=venue, id=market_id, title="synthetic live-book market", close_time=None)


def kalshi_contract(outcome: str = "YES", *, ticker: str = KALSHI_TICKER) -> Contract:
    return Contract(market=_market(KALSHI_VENUE, ticker), id=f"{ticker}:{outcome}", outcome=outcome)


def poly_contract(outcome: str = "LONG", *, slug: str = POLY_SLUG) -> Contract:
    return Contract(market=_market(POLY_VENUE, slug), id=f"{slug}:{outcome}", outcome=outcome)


def levels(pairs: Sequence[tuple[str, str]]) -> tuple[PriceLevel, ...]:
    return tuple(PriceLevel(price=Decimal(p), quantity=Decimal(q)) for p, q in pairs)


def kalshi_snapshot_frame(
    *,
    seq: int,
    yes_fp: Sequence[tuple[str, str]] | None,
    no_fp: Sequence[tuple[str, str]] | None,
    ticker: str = KALSHI_TICKER,
) -> dict[str, object]:
    msg: dict[str, object] = {
        "market_ticker": ticker,
        "market_id": "00000000-0000-0000-0000-000000000000",
    }
    if yes_fp is not None:
        msg["yes_dollars_fp"] = [list(pair) for pair in yes_fp]
    if no_fp is not None:
        msg["no_dollars_fp"] = [list(pair) for pair in no_fp]
    return {"type": "orderbook_snapshot", "sid": 7, "seq": seq, "msg": msg}


def kalshi_delta_frame(
    *,
    seq: int,
    side: str,
    price_dollars: str,
    delta_fp: str,
    ts_ms: int | None = None,
    ticker: str = KALSHI_TICKER,
) -> dict[str, object]:
    msg: dict[str, object] = {
        "market_ticker": ticker,
        "market_id": "00000000-0000-0000-0000-000000000000",
        "price_dollars": price_dollars,
        "delta_fp": delta_fp,
        "side": side,
    }
    if ts_ms is not None:
        msg["ts_ms"] = ts_ms
    return {"type": "orderbook_delta", "sid": 7, "seq": seq, "msg": msg}


def poly_market_data_frame(
    *,
    bids: Sequence[tuple[str, str]],
    offers: Sequence[tuple[str, str]],
    state: str | None = "MARKET_STATE_OPEN",
    transact_time: str | None = "2026-02-01T12:00:00Z",
    slug: str = POLY_SLUG,
) -> dict[str, object]:
    market_data: dict[str, object] = {
        "marketSlug": slug,
        "bids": [{"px": {"value": p, "currency": "USD"}, "qty": q} for p, q in bids],
        "offers": [{"px": {"value": p, "currency": "USD"}, "qty": q} for p, q in offers],
    }
    if state is not None:
        market_data["state"] = state
    if transact_time is not None:
        market_data["transactTime"] = transact_time
    return {
        "requestId": "md-sub-1",
        "subscriptionType": "SUBSCRIPTION_TYPE_MARKET_DATA",
        "marketData": market_data,
    }


# --------------------------------------------------------------------------- #
# Fakes for the transport boundary (M2.1)
# --------------------------------------------------------------------------- #

FAKE_KALSHI_KEY_ID = "kalshi-test-key-id-0000"
FAKE_KALSHI_PEM = "-----BEGIN PRIVATE KEY-----\nNOT-A-REAL-KEY\n-----END PRIVATE KEY-----\n"
FAKE_POLY_KEY_ID = "poly-test-key-id-0000"
FAKE_POLY_SECRET = "cG9seS10ZXN0LXNlY3JldC1ub3QtcmVhbA=="  # base64("poly-test-secret-not-real")


class StaticSigner:
    """A deterministic fake ``Signer`` — returns a fixed byte string, records
    every message it was asked to sign."""

    def __init__(self, signature: bytes = b"fake-signature-bytes") -> None:
        self._signature = signature
        self.signed: list[bytes] = []

    def sign(self, message: bytes) -> bytes:
        self.signed.append(message)
        return self._signature


class FakeWebSocketTransport:
    """Scripted in-memory ``WebSocketTransport``. ``inbound`` is a list of items:
    a ``str`` (delivered by ``receive``) or the sentinel ``TransportClosed`` /
    an ``Exception`` instance (raised by ``receive``)."""

    def __init__(self, inbound: Sequence[object] | None = None) -> None:
        self.inbound: list[object] = list(inbound or [])
        self.connected_with: list[Handshake] = []
        self.sent: list[str] = []
        self.closed = 0

    def connect(self, handshake: Handshake) -> None:
        self.connected_with.append(handshake)

    def send(self, text: str) -> None:
        self.sent.append(text)

    def receive(self) -> str:
        if not self.inbound:
            raise TransportClosed("script exhausted")
        item = self.inbound.pop(0)
        if item is TransportClosed or isinstance(item, TransportClosed):
            raise TransportClosed("scripted close")
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, str)
        return item

    def close(self) -> None:
        self.closed += 1


class FakeSnapshotSource:
    """Returns a pre-registered :class:`BookSnapshot` per ``contract_id``."""

    def __init__(self, snapshots: dict[str, BookSnapshot]) -> None:
        self._snapshots = snapshots
        self.fetched: list[str] = []

    def fetch(self, contract_id: str) -> BookSnapshot:
        self.fetched.append(contract_id)
        return self._snapshots[contract_id]


class RecordingSleep:
    """Injectable ``sleep`` that records the durations it was called with."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
