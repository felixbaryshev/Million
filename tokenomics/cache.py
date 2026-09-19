"""Prompt-cache analysis: what a run of requests costs, and what it could cost.

Two traffic shapes, because they cache differently:

``fanout``
    N independent requests that share a long stable prefix (a system prompt,
    a tool list, a retrieved document) and differ only at the tail. The prefix
    is written once and read N-1 times.

``conversation``
    Successive turns of one conversation, where each turn's prefix is the
    whole preceding transcript. The breakpoint moves forward every turn: each
    turn reads what the last one left behind and writes only its own delta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .blocks import Block, common_prefix, first_divergence, render, token_total
from .pricing import Cost, Model, Usage, get_model, price


@dataclass
class Plan:
    """A priced caching strategy for one run of requests."""

    name: str
    usage: Usage
    cost: Cost
    detail: str = ""

    @property
    def total(self) -> float:
        return self.cost.total


@dataclass
class Analysis:
    """The result of analysing a run of requests."""

    model: Model
    mode: str
    requests: int
    prefix_tokens: int
    volatile_tokens: int
    output_tokens: int
    plans: List[Plan]
    divergence: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def baseline(self) -> Plan:
        return self.plans[0]

    @property
    def best(self) -> Plan:
        return min(self.plans, key=lambda p: p.total)

    @property
    def savings(self) -> float:
        return self.baseline.total - self.best.total

    @property
    def savings_pct(self) -> float:
        base = self.baseline.total
        return 0.0 if base == 0 else self.savings / base * 100.0

    def scaled(self, factor: float) -> Dict[str, float]:
        """Project the savings onto a larger volume of identical traffic."""
        return {
            "baseline": self.baseline.total * factor,
            "best": self.best.total * factor,
            "savings": self.savings * factor,
        }


def _cacheable(prefix_tokens: int, model: Model, warnings: List[str]) -> bool:
    if prefix_tokens < model.min_cacheable_tokens:
        warnings.append(
            f"Shared prefix is ~{prefix_tokens} tokens, below the "
            f"~{model.min_cacheable_tokens}-token floor for {model.id}. The API "
            "silently skips caching prefixes this short -- it will not error, "
            "it will just never hit. Move more stable content to the front, or "
            "accept that this traffic is not cacheable."
        )
        return False
    return True


def analyse_fanout(
    requests: Sequence[Dict[str, Any]],
    model: Model,
    output_tokens: int = 0,
    ttls: Sequence[str] = ("5m", "1h"),
) -> Analysis:
    """Price N independent requests that share a prefix."""
    runs = [render(r) for r in requests]
    n = len(runs)
    warnings: List[str] = []

    shared = common_prefix(runs)
    prefix_blocks = runs[0][:shared] if runs else []
    prefix_tokens = token_total(prefix_blocks)
    volatile_tokens = sum(token_total(run[shared:]) for run in runs)
    per_request_output = output_tokens

    plans: List[Plan] = []

    uncached = Usage(
        input_tokens=prefix_tokens * n + volatile_tokens,
        output_tokens=per_request_output * n,
    )
    plans.append(
        Plan(
            "no cache",
            uncached,
            price(uncached, model),
            f"prefix of ~{prefix_tokens} tok re-sent at full price {n}x",
        )
    )

    if _cacheable(prefix_tokens, model, warnings) and n > 0:
        for ttl in ttls:
            usage = Usage(
                input_tokens=volatile_tokens,
                output_tokens=per_request_output * n,
                cache_read_input_tokens=prefix_tokens * (n - 1),
                cache_creation_5m_tokens=prefix_tokens if ttl == "5m" else 0,
                cache_creation_1h_tokens=prefix_tokens if ttl == "1h" else 0,
            )
            need = model.break_even_reads(ttl)
            note = f"1 write + {n - 1} reads; breaks even at {need} requests"
            if n < need:
                note += f" -- you have {n}, so this LOSES money"
            plans.append(Plan(f"cache ({ttl} TTL)", usage, price(usage, model), note))

    if model.batch_eligible:
        batch_usage = uncached
        plans.append(
            Plan(
                "batch, no cache",
                batch_usage,
                price(batch_usage, model, batch=True),
                "50% off, results arrive asynchronously -- only for traffic "
                "that can wait",
            )
        )

    return Analysis(
        model=model,
        mode="fanout",
        requests=n,
        prefix_tokens=prefix_tokens,
        volatile_tokens=volatile_tokens,
        output_tokens=per_request_output * n,
        plans=plans,
        divergence=first_divergence(runs) if n > 1 else {},
        warnings=warnings,
    )


def analyse_conversation(
    requests: Sequence[Dict[str, Any]],
    model: Model,
    output_tokens: int = 0,
    ttls: Sequence[str] = ("5m",),
) -> Analysis:
    """Price successive turns of one growing conversation."""
    runs = [render(r) for r in requests]
    n = len(runs)
    warnings: List[str] = []

    totals = [token_total(run) for run in runs]
    uncached = Usage(input_tokens=sum(totals), output_tokens=output_tokens * n)
    plans = [
        Plan(
            "no cache",
            uncached,
            price(uncached, model),
            f"every turn re-sends the whole transcript ({sum(totals)} tok total)",
        )
    ]

    # With a moving breakpoint, turn i reads the prefix turn i-1 established
    # and writes only what it added. A turn whose delta is below the floor
    # still reads the existing entry; it just cannot extend it, so its delta
    # is re-sent at full price until enough turns accumulate.
    for ttl in ttls:
        reads = writes = fresh = 0
        cached_through = 0
        for i, run in enumerate(runs):
            total = totals[i]
            if i == 0:
                if _cacheable(total, model, warnings):
                    writes += total
                    cached_through = total
                else:
                    fresh += total
                continue
            delta = total - cached_through
            reads += cached_through
            if delta >= model.min_cacheable_tokens:
                writes += delta
                cached_through = total
            else:
                fresh += delta
        usage = Usage(
            input_tokens=fresh,
            output_tokens=output_tokens * n,
            cache_read_input_tokens=reads,
            cache_creation_5m_tokens=writes if ttl == "5m" else 0,
            cache_creation_1h_tokens=writes if ttl == "1h" else 0,
        )
        plans.append(
            Plan(
                f"moving breakpoint ({ttl} TTL)",
                usage,
                price(usage, model),
                f"{reads} tok read, {writes} tok written, {fresh} tok at full price",
            )
        )

    return Analysis(
        model=model,
        mode="conversation",
        requests=n,
        prefix_tokens=totals[0] if totals else 0,
        volatile_tokens=sum(totals) - (totals[0] if totals else 0),
        output_tokens=output_tokens * n,
        plans=plans,
        divergence={},
        warnings=warnings,
    )


def analyse(
    requests: Sequence[Dict[str, Any]],
    model_id: str = "claude-opus-5",
    mode: str = "fanout",
    output_tokens: int = 0,
) -> Analysis:
    """Analyse a run of requests under the given traffic shape."""
    if not requests:
        raise ValueError("no requests to analyse")
    model = get_model(model_id)
    if mode == "fanout":
        return analyse_fanout(requests, model, output_tokens)
    if mode == "conversation":
        return analyse_conversation(requests, model, output_tokens)
    raise ValueError(f"unknown mode {mode!r} (expected 'fanout' or 'conversation')")
