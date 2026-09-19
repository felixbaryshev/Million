"""Model catalog and cost arithmetic for the Claude API.

Prices are USD per million tokens, Anthropic first-party API rates.
Bedrock / Vertex are partner-operated and priced separately -- do not use
this table for them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Iterable, Optional

MTOK = 1_000_000

#: Message Batches run asynchronously at half price on both input and output.
BATCH_DISCOUNT = 0.5


@dataclass(frozen=True)
class Model:
    """Pricing and cache economics for a single model."""

    id: str
    display_name: str
    input_per_mtok: float
    output_per_mtok: float
    context_window: int
    max_output: int
    #: Cache reads are billed at this fraction of the base input price.
    cache_read_multiplier: float = 0.1
    #: Cache writes carry a premium over the base input price, by TTL.
    cache_write_5m_multiplier: float = 1.25
    cache_write_1h_multiplier: float = 2.0
    #: Prefixes shorter than this never cache (the API silently skips them).
    #: Documented as model-dependent in the 512-4096 range; these are
    #: conservative defaults -- override with --min-cache-tokens if you have
    #: measured the real floor for your model.
    min_cacheable_tokens: int = 1024
    batch_eligible: bool = True
    notes: str = ""

    @property
    def cache_read_per_mtok(self) -> float:
        return self.input_per_mtok * self.cache_read_multiplier

    def cache_write_per_mtok(self, ttl: str = "5m") -> float:
        return self.input_per_mtok * self.cache_write_multiplier(ttl)

    def cache_write_multiplier(self, ttl: str = "5m") -> float:
        if ttl == "5m":
            return self.cache_write_5m_multiplier
        if ttl == "1h":
            return self.cache_write_1h_multiplier
        raise ValueError(f"unknown cache TTL {ttl!r} (expected '5m' or '1h')")

    def break_even_reads(self, ttl: str = "5m") -> int:
        """How many requests must share a prefix before caching it pays off.

        Caching N requests costs ``write + (N-1) * read`` prefix-multiples
        against ``N`` uncached ones. Returns the smallest N where caching wins.
        """
        write = self.cache_write_multiplier(ttl)
        read = self.cache_read_multiplier
        # write + (n-1)*read < n  ->  n > (write - read) / (1 - read)
        n = 1
        while write + (n - 1) * read >= n:
            n += 1
            if n > 1000:  # pragma: no cover - only if read >= 1.0
                raise ValueError("caching never pays off at these multipliers")
        return n


_MODELS = [
    Model(
        "claude-fable-5-1", "Claude Fable 5.1", 10.00, 50.00, 1_000_000, 128_000,
        cache_read_multiplier=0.025, min_cacheable_tokens=2048,
        notes="Thinking always on. Cache reads at $0.25/MTok make keep-alives "
              "cheaper than the 1h TTL. No Priority Tier.",
    ),
    Model(
        "claude-mythos-5-1", "Claude Mythos 5.1", 10.00, 50.00, 1_000_000, 128_000,
        min_cacheable_tokens=2048,
        notes="Project Glasswing only. Whether it shares Fable 5.1's 0.025x "
              "cache-read rate is unconfirmed; priced here at the 0.1x default.",
    ),
    Model(
        "claude-fable-5", "Claude Fable 5", 10.00, 50.00, 1_000_000, 128_000,
        min_cacheable_tokens=2048,
    ),
    Model(
        "claude-opus-5", "Claude Opus 5", 5.00, 25.00, 1_000_000, 128_000,
        min_cacheable_tokens=2048,
        notes="Default model. Fast mode is priced separately at $10/$50.",
    ),
    Model("claude-opus-4-8", "Claude Opus 4.8", 5.00, 25.00, 1_000_000, 128_000,
          min_cacheable_tokens=2048),
    Model("claude-opus-4-7", "Claude Opus 4.7", 5.00, 25.00, 1_000_000, 128_000,
          min_cacheable_tokens=2048),
    Model("claude-opus-4-6", "Claude Opus 4.6", 5.00, 25.00, 1_000_000, 128_000,
          min_cacheable_tokens=2048),
    Model("claude-sonnet-5", "Claude Sonnet 5", 2.00, 10.00, 1_000_000, 128_000,
          min_cacheable_tokens=2048),
    Model("claude-sonnet-4-6", "Claude Sonnet 4.6", 3.00, 15.00, 1_000_000, 128_000,
          min_cacheable_tokens=2048),
    Model("claude-haiku-4-5", "Claude Haiku 4.5", 1.00, 5.00, 200_000, 64_000,
          min_cacheable_tokens=2048,
          notes="Cache reads DO count toward input-token rate limits here."),
]

CATALOG: Dict[str, Model] = {m.id: m for m in _MODELS}

DEFAULT_MODEL = "claude-opus-5"


def get_model(model_id: str) -> Model:
    """Look up a model by exact id, with a helpful error listing the catalog."""
    try:
        return CATALOG[model_id]
    except KeyError:
        known = ", ".join(sorted(CATALOG))
        raise KeyError(
            f"unknown model {model_id!r}. Known ids: {known}. "
            "Model ids are exact and never carry a date suffix."
        ) from None


def cheaper_than(model_id: str) -> Iterable[Model]:
    """Models with a strictly lower blended price than ``model_id``."""
    base = get_model(model_id)
    for m in CATALOG.values():
        if m.id == base.id:
            continue
        if m.input_per_mtok <= base.input_per_mtok and m.output_per_mtok < base.output_per_mtok:
            yield m


@dataclass(frozen=True)
class Usage:
    """A token bill, mirroring the fields of ``response.usage``."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_5m_tokens: int = 0
    cache_creation_1h_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_input_tokens + other.cache_read_input_tokens,
            self.cache_creation_5m_tokens + other.cache_creation_5m_tokens,
            self.cache_creation_1h_tokens + other.cache_creation_1h_tokens,
        )

    @property
    def total_input_tokens(self) -> int:
        return (
            self.input_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_5m_tokens
            + self.cache_creation_1h_tokens
        )

    @classmethod
    def from_response(cls, usage: dict) -> "Usage":
        """Build from a real ``response.usage`` dict (SDK or raw JSON)."""
        creation = usage.get("cache_creation") or {}
        five = creation.get("ephemeral_5m_input_tokens")
        hour = creation.get("ephemeral_1h_input_tokens")
        if five is None and hour is None:
            # Older shape: only the rolled-up counter is present. Attribute it
            # to the 5m TTL, which is the default and the common case.
            five = usage.get("cache_creation_input_tokens", 0) or 0
            hour = 0
        return cls(
            input_tokens=usage.get("input_tokens", 0) or 0,
            output_tokens=usage.get("output_tokens", 0) or 0,
            cache_read_input_tokens=usage.get("cache_read_input_tokens", 0) or 0,
            cache_creation_5m_tokens=five or 0,
            cache_creation_1h_tokens=hour or 0,
        )


@dataclass(frozen=True)
class Cost:
    """A priced-out usage record, in USD."""

    model_id: str
    uncached_input: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    output: float = 0.0
    batch: bool = False

    @property
    def input(self) -> float:
        return self.uncached_input + self.cache_read + self.cache_write

    @property
    def total(self) -> float:
        return self.input + self.output

    def __add__(self, other: "Cost") -> "Cost":
        if other.model_id != self.model_id:
            raise ValueError("cannot add costs for different models")
        return replace(
            self,
            uncached_input=self.uncached_input + other.uncached_input,
            cache_read=self.cache_read + other.cache_read,
            cache_write=self.cache_write + other.cache_write,
            output=self.output + other.output,
        )


def price(usage: Usage, model: Model, batch: bool = False) -> Cost:
    """Price a :class:`Usage` against a model's rate card."""
    if batch and not model.batch_eligible:
        raise ValueError(f"{model.id} is not available on the Batch API")
    factor = BATCH_DISCOUNT if batch else 1.0
    inp = model.input_per_mtok / MTOK * factor
    out = model.output_per_mtok / MTOK * factor
    return Cost(
        model_id=model.id,
        uncached_input=usage.input_tokens * inp,
        cache_read=usage.cache_read_input_tokens * inp * model.cache_read_multiplier,
        cache_write=(
            usage.cache_creation_5m_tokens * inp * model.cache_write_5m_multiplier
            + usage.cache_creation_1h_tokens * inp * model.cache_write_1h_multiplier
        ),
        output=usage.output_tokens * out,
        batch=batch,
    )
