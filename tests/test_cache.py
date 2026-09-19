import pytest

from tokenomics.cache import analyse
from tokenomics.pricing import get_model

BIG = "Policy paragraph that never changes. " * 900


def fanout(n, prefix=BIG):
    return [{"system": prefix, "messages": [{"role": "user", "content": f"q{i}"}]}
            for i in range(n)]


def test_empty_input_is_rejected():
    with pytest.raises(ValueError):
        analyse([])


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        analyse(fanout(2), mode="sideways")


def test_caching_a_shared_prefix_saves_money_at_scale():
    a = analyse(fanout(50), "claude-opus-5", output_tokens=300)
    assert a.best.name.startswith("cache")
    assert a.savings > 0
    assert a.savings_pct > 30


def test_the_analysis_finds_the_shared_prefix():
    a = analyse(fanout(10))
    assert a.prefix_tokens > 2000
    assert a.volatile_tokens < a.prefix_tokens


def test_a_single_request_cannot_profit_from_caching():
    a = analyse(fanout(1), "claude-opus-5")
    cache_plans = [p for p in a.plans if p.name.startswith("cache")]
    assert all(p.total >= a.baseline.total for p in cache_plans)


def test_short_prefixes_warn_instead_of_promising_savings():
    a = analyse(fanout(20, prefix="short system prompt"), "claude-opus-5")
    assert a.warnings
    assert "floor" in a.warnings[0]
    assert not [p for p in a.plans if p.name.startswith("cache")]


def test_requests_sharing_nothing_report_divergence_at_block_zero():
    reqs = [{"system": f"unique {i}", "messages": [{"role": "user", "content": "x"}]}
            for i in range(3)]
    a = analyse(reqs)
    assert a.divergence["index"] == 0
    assert a.prefix_tokens == 0


def test_batch_halves_the_uncached_bill():
    a = analyse(fanout(10), "claude-opus-5", output_tokens=100)
    base = a.baseline.total
    batch = [p for p in a.plans if p.name.startswith("batch")][0]
    assert batch.total == pytest.approx(base * 0.5)


def test_five_minute_ttl_beats_one_hour_for_dense_traffic():
    a = analyse(fanout(30), "claude-opus-5")
    plans = {p.name: p.total for p in a.plans}
    assert plans["cache (5m TTL)"] < plans["cache (1h TTL)"]


def test_conversation_mode_charges_each_turn_only_for_its_delta():
    turns = []
    messages = []
    for i in range(8):
        messages = messages + [{"role": "user", "content": BIG[:4000] + f" turn {i}"}]
        turns.append({"system": BIG, "messages": list(messages)})
    a = analyse(turns, "claude-opus-5", mode="conversation", output_tokens=200)
    assert a.best.name.startswith("moving breakpoint")
    assert a.savings > 0


def test_scaling_projects_savings_linearly():
    a = analyse(fanout(20), "claude-opus-5", output_tokens=100)
    scaled = a.scaled(1000)
    assert scaled["savings"] == pytest.approx(a.savings * 1000)


def test_fable_cheap_reads_beat_opus_proportionally():
    opus = analyse(fanout(40), "claude-opus-5")
    fable = analyse(fanout(40), "claude-fable-5-1")
    assert fable.savings_pct > opus.savings_pct
