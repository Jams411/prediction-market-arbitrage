"""Pure, deterministic cross-venue arbitrage calculation (Milestone M1.5).

Consumes **already normalized** :class:`OrderBook`s and an **already verified**
:class:`MarketPairRecord` and computes whether buying both complementary
outcomes costs less than their combined $1 settlement, after explicit fees and an
explicit execution buffer, at a depth-walked executable size.

Boundaries (see ``docs/ARBITRAGE_METHODOLOGY.md`` and D-012):
- It does **not** decide equivalence — that is the M1.4 registry's job. The
  engine only evaluates pairs it receives through the registry's eligible path
  (or a record whose status is VERIFIED); anything else raises.
- It does **not** call venue APIs, submit orders, hold positions, or use wall
  clock time. Every timestamp is injected.
- It does **not** hardcode real venue fee schedules — the fee model is injected.

Scope: M1.5 implements two **buy-only** arbitrage models:

- **Cross-venue complementary buy/buy** — :meth:`ArbitrageEngine.evaluate`: buy
  one unit of each complementary side across two venues and let the $1
  settlement cover the combined cost. Only ``OutcomeRelation.COMPLEMENTARY``
  registry records are evaluated.
- **Same-market complete-set buy** — :meth:`ArbitrageEngine.evaluate_complete_set`:
  buy one unit of **every** mutually exclusive outcome of a single market on a
  single venue. Exactly one outcome settles to 1, so a matched set pays exactly
  1 per unit; if the set costs less than 1 after fees and the execution buffer
  it is a locked-in edge. There is no equivalence question (the outcomes belong
  to one market), so this path takes ``OrderBook``\\ s directly and uses **no**
  registry — the caller asserts, by which books it supplies, that they are the
  market's complete and mutually exclusive outcome set (A-039).

``IDENTICAL`` pairs are **not** claimed to be un-arbitrageable — an identical
contract quoted more cheaply on one venue than another is a real edge. But
capturing it means *selling* / shorting the richer side, which needs position
and execution semantics this buy/buy engine does not have. So ``IDENTICAL``
records return no opportunity with a reason; support is deferred to
execution/broker work, not ruled out.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from prediction_market_arbitrage.domain import (
    Contract,
    MarketPair,
    Opportunity,
    OrderBook,
    PriceLevel,
)
from prediction_market_arbitrage.registry import (
    ELIGIBLE_STATUSES,
    MarketPairRecord,
    MarketPairRegistry,
    OutcomeRelation,
    VenueLeg,
)

from .errors import ArbitrageError
from .fees import FeeModel, ZeroFeeModel

_ZERO = Decimal(0)


def _dsum(values: Sequence[Decimal]) -> Decimal:
    total = _ZERO
    for value in values:
        total += value
    return total


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """Deterministic knobs. Every monetary value is an exact ``Decimal``."""

    fee_model: FeeModel = field(default_factory=ZeroFeeModel)
    execution_buffer_per_unit: Decimal = _ZERO
    max_quantity: Decimal | None = None
    #: Optional freshness guard: max age of each book vs. the injected
    #: ``evaluation_time``. ``None`` disables the check.
    max_book_age: timedelta | None = None
    #: Optional freshness guard: max absolute difference between the two books'
    #: timestamps. ``None`` disables the check.
    max_cross_book_skew: timedelta | None = None
    #: When True, a requested quantity that exceeds available depth yields no
    #: opportunity instead of a depth-capped one.
    require_full_fill: bool = False

    def __post_init__(self) -> None:
        buffer = self.execution_buffer_per_unit
        if not isinstance(buffer, Decimal) or not buffer.is_finite() or buffer < _ZERO:
            raise ArbitrageError(
                "EngineConfig.execution_buffer_per_unit must be a finite Decimal >= 0"
            )
        if self.max_quantity is not None:
            mq = self.max_quantity
            if not isinstance(mq, Decimal) or not mq.is_finite() or mq <= _ZERO:
                raise ArbitrageError(
                    "EngineConfig.max_quantity must be a finite positive Decimal or None"
                )


# --------------------------------------------------------------------------- #
# Result types — designed so the calculation can be fully reconstructed
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LegFill:
    """One slice taken from an ask level while walking the book."""

    price: Decimal
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class LegEvaluation:
    """What the engine bought (or would buy) on one leg."""

    venue: str
    market_id: str
    outcome: str
    contract_id: str
    book_timestamp: datetime
    available_ask_depth: Decimal
    fills: tuple[LegFill, ...]
    filled_quantity: Decimal
    acquisition_cost: Decimal

    @property
    def average_price(self) -> Decimal:
        """Depth-weighted average acquisition price (derived; ``0`` when nothing filled)."""
        if self.filled_quantity <= _ZERO:
            return _ZERO
        return self.acquisition_cost / self.filled_quantity


@dataclass(frozen=True, slots=True)
class OpportunityEvaluation:
    """Full, auditable result of one evaluation.

    Every cost / edge / profit total is an **exact** Decimal (no internal
    rounding). The ``*_per_unit`` values are *derived* (a division) and may be
    rounded to the active Decimal context precision when they do not divide
    evenly — the totals remain authoritative.
    """

    pair_id: str
    relation: OutcomeRelation
    evaluation_time: datetime
    leg_a: LegEvaluation
    leg_b: LegEvaluation
    leg_a_contract: Contract
    leg_b_contract: Contract
    requested_quantity: Decimal | None
    executable_quantity: Decimal
    depth_capped: bool
    gross_total_cost: Decimal
    gross_edge: Decimal
    fees: Decimal
    execution_buffer: Decimal
    net_total_cost: Decimal
    net_edge: Decimal
    has_opportunity: bool
    rejection_reason: str

    @property
    def expected_total_profit(self) -> Decimal:
        """``net_edge`` when an opportunity exists, else ``0``. (== net_edge_per_unit * qty)"""
        return self.net_edge if self.has_opportunity else _ZERO

    @property
    def net_edge_per_unit(self) -> Decimal:
        if self.executable_quantity <= _ZERO:
            return _ZERO
        return self.net_edge / self.executable_quantity

    @property
    def gross_edge_per_unit(self) -> Decimal:
        if self.executable_quantity <= _ZERO:
            return _ZERO
        return self.gross_edge / self.executable_quantity

    def to_opportunity(self) -> Opportunity:
        """Build the minimal venue-neutral :class:`Opportunity` container.

        Only valid when ``has_opportunity`` — ``Opportunity.edge`` must be > 0.
        """
        if not self.has_opportunity:
            raise ArbitrageError(
                f"{self.pair_id}: no opportunity to convert ({self.rejection_reason})"
            )
        pair = MarketPair(
            id=self.pair_id, left=self.leg_a_contract, right=self.leg_b_contract
        )
        return Opportunity(
            id=f"{self.pair_id}@{self.evaluation_time.isoformat()}",
            pair=pair,
            quantity=self.executable_quantity,
            edge=self.net_edge_per_unit,
            timestamp=self.evaluation_time,
        )


@dataclass(frozen=True, slots=True)
class CompleteSetEvaluation:
    """Full, auditable result of one same-market complete-set evaluation.

    Same exact-Decimal discipline as :class:`OpportunityEvaluation`: every
    cost / edge / profit total is exact; the ``*_per_unit`` values are derived
    (a division) and may round to the active Decimal context precision.

    This is a **separate** type from :class:`OpportunityEvaluation` on purpose —
    it does **not** subclass it. Downstream components accept only
    ``OpportunityEvaluation`` (``recorder.record_opportunity`` isinstance-checks
    it and raises; ``risk.RiskManager`` / ``dashboard.build_dashboard`` are
    typed to it, enforced by the mypy gate), so a complete-set result — whose
    "guaranteed 1 at settlement" premise rests on the caller's A-039 assertion,
    not a registry gate — cannot be silently recorded, risk-scored, or
    displayed as if it were a registry-verified opportunity. Nothing consumes
    either evaluation type or the :class:`Opportunity` from ``to_opportunity``
    to produce an order; execution needs a hand-built
    ``OrderRequest`` / ``LiveOrderRequest``.
    """

    market_id: str
    venue: str
    evaluation_time: datetime
    legs: tuple[LegEvaluation, ...]
    outcome_contracts: tuple[Contract, ...]
    requested_quantity: Decimal | None
    executable_quantity: Decimal
    depth_capped: bool
    gross_total_cost: Decimal
    gross_edge: Decimal
    fees: Decimal
    execution_buffer: Decimal
    net_total_cost: Decimal
    net_edge: Decimal
    has_opportunity: bool
    rejection_reason: str

    @property
    def outcome_count(self) -> int:
        return len(self.legs)

    @property
    def expected_total_profit(self) -> Decimal:
        """``net_edge`` when an opportunity exists, else ``0``."""
        return self.net_edge if self.has_opportunity else _ZERO

    @property
    def net_edge_per_unit(self) -> Decimal:
        if self.executable_quantity <= _ZERO:
            return _ZERO
        return self.net_edge / self.executable_quantity

    @property
    def gross_edge_per_unit(self) -> Decimal:
        if self.executable_quantity <= _ZERO:
            return _ZERO
        return self.gross_edge / self.executable_quantity

    def to_opportunity(self) -> Opportunity:
        """Build the minimal venue-neutral :class:`Opportunity` container.

        Only defined for a **binary** complete set (exactly two outcomes) — the
        domain :class:`MarketPair` holds exactly two contracts. A categorical
        (>2 outcome) set has no ``MarketPair`` representation; convert it via a
        future domain type instead.
        """
        if not self.has_opportunity:
            raise ArbitrageError(
                f"{self.market_id}: no opportunity to convert ({self.rejection_reason})"
            )
        if self.outcome_count != 2:
            raise ArbitrageError(
                f"{self.market_id}: to_opportunity() needs exactly 2 outcomes, "
                f"got {self.outcome_count}"
            )
        left, right = self.outcome_contracts
        pair = MarketPair(id=self.market_id, left=left, right=right)
        return Opportunity(
            id=f"{self.market_id}@{self.evaluation_time.isoformat()}",
            pair=pair,
            quantity=self.executable_quantity,
            edge=self.net_edge_per_unit,
            timestamp=self.evaluation_time,
        )


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #


class ArbitrageEngine:
    """Evaluates one verified pair against two normalized books. Stateless."""

    def __init__(self, config: EngineConfig | None = None) -> None:
        self._config = config if config is not None else EngineConfig()

    @property
    def config(self) -> EngineConfig:
        return self._config

    def evaluate_from_registry(
        self,
        registry: MarketPairRegistry,
        pair_id: str,
        kalshi_book: OrderBook,
        polymarket_us_book: OrderBook,
        *,
        evaluation_time: datetime,
        requested_quantity: Decimal | None = None,
    ) -> OpportunityEvaluation:
        """Look ``pair_id`` up in ``registry`` and evaluate it only if it is in
        ``registry.eligible()`` (VERIFIED). This is the intended entry point."""
        record = registry.get(pair_id)
        if record is None:
            raise ArbitrageError(f"pair_id {pair_id!r} is not in the registry")
        if record not in registry.eligible():
            raise ArbitrageError(
                f"pair {pair_id!r} has status {record.status}; only VERIFIED pairs from "
                "the registry's eligible() set may be evaluated"
            )
        return self.evaluate(
            record,
            kalshi_book,
            polymarket_us_book,
            evaluation_time=evaluation_time,
            requested_quantity=requested_quantity,
        )

    def evaluate(
        self,
        record: MarketPairRecord,
        kalshi_book: OrderBook,
        polymarket_us_book: OrderBook,
        *,
        evaluation_time: datetime,
        requested_quantity: Decimal | None = None,
    ) -> OpportunityEvaluation:
        """Evaluate a single verified pair. Raises :class:`ArbitrageError` on misuse."""
        # 1. Registry gate — enforced even on this lower-level path (defence in depth).
        if record.status not in ELIGIBLE_STATUSES:
            raise ArbitrageError(
                f"pair {record.pair_id!r} has status {record.status}; only VERIFIED "
                "pairs may be evaluated (the registry eligibility gate cannot be bypassed)"
            )

        # 2. Input validation.
        _require_aware(evaluation_time, "evaluation_time")
        for book, name in (
            (kalshi_book, "kalshi_book"),
            (polymarket_us_book, "polymarket_us_book"),
        ):
            if not isinstance(book, OrderBook):
                raise ArbitrageError(f"{name} must be an OrderBook")
        if requested_quantity is not None:
            if not isinstance(requested_quantity, Decimal) or not requested_quantity.is_finite():
                raise ArbitrageError("requested_quantity must be a finite Decimal or None")
            if requested_quantity <= _ZERO:
                raise ArbitrageError("requested_quantity must be > 0 when given")

        # 3. Bind each book to its named leg — explicit, deterministic, no guessing.
        _check_leg(kalshi_book, record.kalshi, "kalshi_book")
        _check_leg(polymarket_us_book, record.polymarket_us, "polymarket_us_book")

        leg_a_contract = kalshi_book.contract
        leg_b_contract = polymarket_us_book.contract

        def _result(
            *,
            executable_quantity: Decimal,
            depth_capped: bool,
            leg_a_eval: LegEvaluation,
            leg_b_eval: LegEvaluation,
            gross_total_cost: Decimal,
            gross_edge: Decimal,
            fees: Decimal,
            execution_buffer: Decimal,
            net_total_cost: Decimal,
            net_edge: Decimal,
            has_opportunity: bool,
            rejection_reason: str,
        ) -> OpportunityEvaluation:
            return OpportunityEvaluation(
                pair_id=record.pair_id,
                relation=record.relation,
                evaluation_time=evaluation_time,
                leg_a=leg_a_eval,
                leg_b=leg_b_eval,
                leg_a_contract=leg_a_contract,
                leg_b_contract=leg_b_contract,
                requested_quantity=requested_quantity,
                executable_quantity=executable_quantity,
                depth_capped=depth_capped,
                gross_total_cost=gross_total_cost,
                gross_edge=gross_edge,
                fees=fees,
                execution_buffer=execution_buffer,
                net_total_cost=net_total_cost,
                net_edge=net_edge,
                has_opportunity=has_opportunity,
                rejection_reason=rejection_reason,
            )

        shell_a = _leg_shell(kalshi_book, record.kalshi)
        shell_b = _leg_shell(polymarket_us_book, record.polymarket_us)

        def _reject(reason: str) -> OpportunityEvaluation:
            return _result(
                executable_quantity=_ZERO,
                depth_capped=False,
                leg_a_eval=shell_a,
                leg_b_eval=shell_b,
                gross_total_cost=_ZERO,
                gross_edge=_ZERO,
                fees=_ZERO,
                execution_buffer=_ZERO,
                net_total_cost=_ZERO,
                net_edge=_ZERO,
                has_opportunity=False,
                rejection_reason=reason,
            )

        # 4. Relation — M1.5 evaluates COMPLEMENTARY only.
        if record.relation is not OutcomeRelation.COMPLEMENTARY:
            return _reject(
                f"relation {record.relation} is not evaluable in M1.5 — only "
                "COMPLEMENTARY (IDENTICAL needs a sell leg; deferred to execution work)"
            )

        # 5. Freshness (optional, uses only injected timestamps).
        stale = self._freshness_reason(kalshi_book, polymarket_us_book, evaluation_time)
        if stale:
            return _reject(stale)

        # 6. Ask liquidity must exist on both legs.
        if not kalshi_book.asks:
            return _reject("kalshi_book has an empty ask side")
        if not polymarket_us_book.asks:
            return _reject("polymarket_us_book has an empty ask side")

        # 7. Executable size: min(requested, depth_a, depth_b, max_quantity).
        depth_a = shell_a.available_ask_depth
        depth_b = shell_b.available_ask_depth
        size = min(depth_a, depth_b)
        if self._config.max_quantity is not None:
            size = min(size, self._config.max_quantity)

        depth_capped = False
        if requested_quantity is not None:
            if requested_quantity > size:
                depth_capped = True
                if self._config.require_full_fill:
                    return _reject(
                        f"insufficient depth: requested {requested_quantity}, "
                        f"executable at most {size}"
                    )
            size = min(requested_quantity, size)

        if size <= _ZERO:
            return _reject("zero executable quantity")

        # 8. Walk the ask side of each leg for `size` units.
        a_fills, a_cost, a_filled = _walk_asks(kalshi_book.asks, size)
        b_fills, b_cost, b_filled = _walk_asks(polymarket_us_book.asks, size)
        # size <= min(depth_a, depth_b) by construction, so both fill fully.
        if a_filled != size or b_filled != size:  # pragma: no cover - guarded above
            return _reject(
                f"internal: could not fill {size} on both legs "
                f"(a={a_filled}, b={b_filled})"
            )

        leg_a_eval = LegEvaluation(
            venue=record.kalshi.venue,
            market_id=record.kalshi.market_id,
            outcome=record.kalshi.outcome,
            contract_id=leg_a_contract.id,
            book_timestamp=kalshi_book.timestamp,
            available_ask_depth=depth_a,
            fills=a_fills,
            filled_quantity=a_filled,
            acquisition_cost=a_cost,
        )
        leg_b_eval = LegEvaluation(
            venue=record.polymarket_us.venue,
            market_id=record.polymarket_us.market_id,
            outcome=record.polymarket_us.outcome,
            contract_id=leg_b_contract.id,
            book_timestamp=polymarket_us_book.timestamp,
            available_ask_depth=depth_b,
            fills=b_fills,
            filled_quantity=b_filled,
            acquisition_cost=b_cost,
        )

        # 9. Economics — all exact Decimal, no internal rounding.
        fee_a = self._config.fee_model.fee(
            venue=record.kalshi.venue, fills=[(f.price, f.quantity) for f in a_fills]
        )
        fee_b = self._config.fee_model.fee(
            venue=record.polymarket_us.venue,
            fills=[(f.price, f.quantity) for f in b_fills],
        )
        for fee in (fee_a, fee_b):
            if not isinstance(fee, Decimal) or not fee.is_finite() or fee < _ZERO:
                raise ArbitrageError(
                    "fee model returned a non-Decimal, negative, or non-finite value"
                )
        fees = fee_a + fee_b
        execution_buffer = self._config.execution_buffer_per_unit * size

        gross_total_cost = a_cost + b_cost
        # A matched set of both complementary outcomes pays exactly `size` at settlement.
        gross_edge = size - gross_total_cost
        net_total_cost = gross_total_cost + fees + execution_buffer
        net_edge = size - net_total_cost

        has_opportunity = net_edge > _ZERO
        if has_opportunity:
            reason = ""
        elif net_edge == _ZERO:
            reason = "net edge is exactly zero (break-even is not an opportunity)"
        else:
            reason = "net edge is negative after fees and execution buffer"

        return _result(
            executable_quantity=size,
            depth_capped=depth_capped,
            leg_a_eval=leg_a_eval,
            leg_b_eval=leg_b_eval,
            gross_total_cost=gross_total_cost,
            gross_edge=gross_edge,
            fees=fees,
            execution_buffer=execution_buffer,
            net_total_cost=net_total_cost,
            net_edge=net_edge,
            has_opportunity=has_opportunity,
            rejection_reason=reason,
        )

    def _freshness_reason(
        self, book_a: OrderBook, book_b: OrderBook, evaluation_time: datetime
    ) -> str:
        config = self._config
        if config.max_book_age is not None:
            for book, name in ((book_a, "kalshi_book"), (book_b, "polymarket_us_book")):
                age = evaluation_time - book.timestamp
                if age < timedelta(0):
                    return f"{name} timestamp is after evaluation_time"
                if age > config.max_book_age:
                    return f"{name} is stale: age {age} exceeds max {config.max_book_age}"
        if config.max_cross_book_skew is not None:
            skew = abs(book_a.timestamp - book_b.timestamp)
            if skew > config.max_cross_book_skew:
                return (
                    f"cross-book skew {skew} exceeds max {config.max_cross_book_skew}"
                )
        return ""

    # ------------------------------------------------------------------ #
    # Same-market complete-set arbitrage
    # ------------------------------------------------------------------ #

    def evaluate_complete_set(
        self,
        books: Sequence[OrderBook],
        *,
        evaluation_time: datetime,
        requested_quantity: Decimal | None = None,
    ) -> CompleteSetEvaluation:
        """Evaluate buying one unit of **every** outcome of a single market.

        ``books`` must be the order books for two or more distinct outcomes of
        the **same** market on the **same** venue. The caller asserts, by which
        books it passes, that these are the market's *complete* and *mutually
        exclusive* outcome set (A-039) — the engine verifies only that the books
        share a venue+market and name distinct contracts. A matched set then
        pays exactly ``executable_quantity`` at settlement, so the same
        gross/net-edge arithmetic as :meth:`evaluate` applies (fees +
        ``execution_buffer_per_unit`` are the only subtracted frictions; exact
        break-even is not an opportunity).

        Raises :class:`ArbitrageError` on misuse (fewer than two books, a
        non-``OrderBook``, a mixed venue/market, a duplicate contract, a bad
        ``evaluation_time`` or ``requested_quantity``). Runtime conditions
        (an empty ask side, stale books, insufficient depth under
        ``require_full_fill``, a non-positive edge) are returned as a
        ``has_opportunity = False`` result with a reason.
        """
        # 1. Shape validation — misuse raises.
        books = tuple(books)
        if len(books) < 2:
            raise ArbitrageError(
                "evaluate_complete_set needs at least two outcome books"
            )
        for index, book in enumerate(books):
            if not isinstance(book, OrderBook):
                raise ArbitrageError(f"books[{index}] must be an OrderBook")
        _require_aware(evaluation_time, "evaluation_time")
        if requested_quantity is not None:
            if (
                not isinstance(requested_quantity, Decimal)
                or not requested_quantity.is_finite()
            ):
                raise ArbitrageError("requested_quantity must be a finite Decimal or None")
            if requested_quantity <= _ZERO:
                raise ArbitrageError("requested_quantity must be > 0 when given")

        venues = {book.contract.market.venue.id for book in books}
        markets = {book.contract.market.id for book in books}
        if len(venues) != 1 or len(markets) != 1:
            raise ArbitrageError(
                "evaluate_complete_set books must all be the same venue and market "
                f"(got venues {sorted(venues)}, markets {sorted(markets)})"
            )
        contract_ids = [book.contract.id for book in books]
        if len(set(contract_ids)) != len(contract_ids):
            raise ArbitrageError(
                f"evaluate_complete_set books must be distinct outcomes (got {contract_ids})"
            )

        venue = next(iter(venues))
        market_id = next(iter(markets))
        outcome_contracts = tuple(book.contract for book in books)
        shells = tuple(_leg_shell_from_book(book) for book in books)

        def _reject(reason: str) -> CompleteSetEvaluation:
            return CompleteSetEvaluation(
                market_id=market_id,
                venue=venue,
                evaluation_time=evaluation_time,
                legs=shells,
                outcome_contracts=outcome_contracts,
                requested_quantity=requested_quantity,
                executable_quantity=_ZERO,
                depth_capped=False,
                gross_total_cost=_ZERO,
                gross_edge=_ZERO,
                fees=_ZERO,
                execution_buffer=_ZERO,
                net_total_cost=_ZERO,
                net_edge=_ZERO,
                has_opportunity=False,
                rejection_reason=reason,
            )

        # 2. Freshness (optional, injected timestamps only).
        stale = self._complete_set_freshness(books, evaluation_time)
        if stale:
            return _reject(stale)

        # 3. Every outcome must have ask liquidity.
        for book in books:
            if not book.asks:
                return _reject(
                    f"outcome {book.contract.outcome!r} has an empty ask side"
                )

        # 4. Executable size: min ask depth across every outcome, then caps.
        depths = [shell.available_ask_depth for shell in shells]
        size = min(depths)
        if self._config.max_quantity is not None:
            size = min(size, self._config.max_quantity)

        depth_capped = False
        if requested_quantity is not None:
            if requested_quantity > size:
                depth_capped = True
                if self._config.require_full_fill:
                    return _reject(
                        f"insufficient depth: requested {requested_quantity}, "
                        f"executable at most {size}"
                    )
            size = min(requested_quantity, size)

        if size <= _ZERO:
            return _reject("zero executable quantity")

        # 5. Walk each outcome's ask side for `size` units.
        legs: list[LegEvaluation] = []
        fees_total = _ZERO
        gross_total_cost = _ZERO
        for book in books:
            fills, cost, filled = _walk_asks(book.asks, size)
            if filled != size:  # pragma: no cover - size <= min(depths) by construction
                return _reject(
                    f"internal: could not fill {size} on outcome "
                    f"{book.contract.outcome!r} (filled {filled})"
                )
            leg_venue = book.contract.market.venue.id
            fee = self._config.fee_model.fee(
                venue=leg_venue, fills=[(f.price, f.quantity) for f in fills]
            )
            if not isinstance(fee, Decimal) or not fee.is_finite() or fee < _ZERO:
                raise ArbitrageError(
                    "fee model returned a non-Decimal, negative, or non-finite value"
                )
            fees_total += fee
            gross_total_cost += cost
            legs.append(
                LegEvaluation(
                    venue=leg_venue,
                    market_id=book.contract.market.id,
                    outcome=book.contract.outcome,
                    contract_id=book.contract.id,
                    book_timestamp=book.timestamp,
                    available_ask_depth=_dsum([lvl.quantity for lvl in book.asks]),
                    fills=fills,
                    filled_quantity=filled,
                    acquisition_cost=cost,
                )
            )

        # 6. Economics — exact Decimal, no internal rounding. One matched set of
        #    every outcome pays exactly `size` at settlement.
        execution_buffer = self._config.execution_buffer_per_unit * size
        gross_edge = size - gross_total_cost
        net_total_cost = gross_total_cost + fees_total + execution_buffer
        net_edge = size - net_total_cost

        has_opportunity = net_edge > _ZERO
        if has_opportunity:
            reason = ""
        elif net_edge == _ZERO:
            reason = "net edge is exactly zero (break-even is not an opportunity)"
        else:
            reason = "net edge is negative after fees and execution buffer"

        return CompleteSetEvaluation(
            market_id=market_id,
            venue=venue,
            evaluation_time=evaluation_time,
            legs=tuple(legs),
            outcome_contracts=outcome_contracts,
            requested_quantity=requested_quantity,
            executable_quantity=size,
            depth_capped=depth_capped,
            gross_total_cost=gross_total_cost,
            gross_edge=gross_edge,
            fees=fees_total,
            execution_buffer=execution_buffer,
            net_total_cost=net_total_cost,
            net_edge=net_edge,
            has_opportunity=has_opportunity,
            rejection_reason=reason,
        )

    def _complete_set_freshness(
        self, books: Sequence[OrderBook], evaluation_time: datetime
    ) -> str:
        config = self._config
        if config.max_book_age is not None:
            for book in books:
                age = evaluation_time - book.timestamp
                if age < timedelta(0):
                    return (
                        f"outcome {book.contract.outcome!r} timestamp is after "
                        "evaluation_time"
                    )
                if age > config.max_book_age:
                    return (
                        f"outcome {book.contract.outcome!r} is stale: age {age} "
                        f"exceeds max {config.max_book_age}"
                    )
        if config.max_cross_book_skew is not None:
            stamps = [book.timestamp for book in books]
            skew = max(stamps) - min(stamps)
            if skew > config.max_cross_book_skew:
                return f"cross-book skew {skew} exceeds max {config.max_cross_book_skew}"
        return ""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _require_aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime):
        raise ArbitrageError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ArbitrageError(f"{name} must be timezone-aware")


def _check_leg(book: OrderBook, leg: VenueLeg, name: str) -> None:
    """Reject unless ``book`` is exactly the contract named by ``leg``.

    The join key is the domain ``Contract.id``, which every adapter builds as
    ``f"{market_id}:{outcome}"``. See A-020 — the registry's ``VenueLeg.outcome``
    must use that same contract-outcome vocabulary. The engine never guesses.
    """
    contract = book.contract
    expected_contract_id = f"{leg.market_id}:{leg.outcome}"
    if (
        contract.market.venue.id != leg.venue
        or contract.market.id != leg.market_id
        or contract.id != expected_contract_id
    ):
        raise ArbitrageError(
            f"{name} contract {contract.id!r} on venue "
            f"{contract.market.venue.id!r} does not match pair leg "
            f"{leg.venue}/{leg.market_id}/{leg.outcome} "
            f"(expected contract id {expected_contract_id!r})"
        )


def _leg_shell(book: OrderBook, leg: VenueLeg) -> LegEvaluation:
    """A leg evaluation with no fills — used on the reject paths."""
    return LegEvaluation(
        venue=leg.venue,
        market_id=leg.market_id,
        outcome=leg.outcome,
        contract_id=book.contract.id,
        book_timestamp=book.timestamp,
        available_ask_depth=_dsum([level.quantity for level in book.asks]),
        fills=(),
        filled_quantity=_ZERO,
        acquisition_cost=_ZERO,
    )


def _leg_shell_from_book(book: OrderBook) -> LegEvaluation:
    """A no-fill leg evaluation derived from a book alone (complete-set path)."""
    contract = book.contract
    return LegEvaluation(
        venue=contract.market.venue.id,
        market_id=contract.market.id,
        outcome=contract.outcome,
        contract_id=contract.id,
        book_timestamp=book.timestamp,
        available_ask_depth=_dsum([level.quantity for level in book.asks]),
        fills=(),
        filled_quantity=_ZERO,
        acquisition_cost=_ZERO,
    )


def _walk_asks(
    asks: Sequence[PriceLevel], target: Decimal
) -> tuple[tuple[LegFill, ...], Decimal, Decimal]:
    """Buy ``target`` units from ``asks`` (ascending price), walking levels.

    Returns ``(fills, total_cost, filled_quantity)``. ``filled_quantity`` is less
    than ``target`` only when the book runs out of depth.
    """
    remaining = target
    fills: list[LegFill] = []
    cost = _ZERO
    for level in asks:
        if remaining <= _ZERO:
            break
        take = level.quantity if level.quantity < remaining else remaining
        fills.append(LegFill(price=level.price, quantity=take))
        cost += level.price * take
        remaining -= take
    return tuple(fills), cost, target - remaining
