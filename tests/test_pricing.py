import pytest

from tokenomics.pricing import (
    BATCH_DISCOUNT, CATALOG, Usage, cheaper_than, get_model, price,
)


def test_catalog_ids_have_no_date_suffix():
    for model_id in CATALOG:
        assert not model_id[-8:].isdigit(), f"{model_id} looks date-suffixed"


def test_unknown_model_error_lists_alternatives():
    with pytest.raises(KeyError, match="claude-opus-5"):
        get_model("claude-opus-5-20260401")


def test_break_even_matches_documented_economics():
    m = get_model("claude-opus-5")
    # 1.25x write + 0.1x read beats 2x uncached at two requests.
    assert m.break_even_reads("5m") == 2
    # 2x write needs a third read to pay off.
    assert m.break_even_reads("1h") == 3


def test_fable_cheap_reads_lower_the_break_even_floor():
    fable = get_model("claude-fable-5-1")
    opus = get_model("claude-opus-5")
    assert fable.cache_read_multiplier < opus.cache_read_multiplier
    assert fable.cache_read_per_mtok == pytest.approx(0.25)


def test_batch_is_half_price_on_both_directions():
    m = get_model("claude-sonnet-5")
    u = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    full, batched = price(u, m), price(u, m, batch=True)
    assert batched.total == pytest.approx(full.total * BATCH_DISCOUNT)
    assert batched.input == pytest.approx(full.input * BATCH_DISCOUNT)


def test_cache_read_is_a_tenth_of_input():
    m = get_model("claude-opus-5")
    read = price(Usage(cache_read_input_tokens=1_000_000), m)
    full = price(Usage(input_tokens=1_000_000), m)
    assert read.total == pytest.approx(full.total * 0.1)


def test_one_hour_write_costs_more_than_five_minute():
    m = get_model("claude-opus-5")
    short = price(Usage(cache_creation_5m_tokens=1_000_000), m).total
    long = price(Usage(cache_creation_1h_tokens=1_000_000), m).total
    assert long == pytest.approx(short * (2.0 / 1.25))


def test_usage_from_response_splits_creation_by_ttl():
    u = Usage.from_response({
        "input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 30,
        "cache_creation": {"ephemeral_5m_input_tokens": 40, "ephemeral_1h_input_tokens": 50},
    })
    assert (u.cache_creation_5m_tokens, u.cache_creation_1h_tokens) == (40, 50)
    assert u.total_input_tokens == 10 + 30 + 40 + 50


def test_usage_from_response_handles_rolled_up_shape():
    u = Usage.from_response({"input_tokens": 1, "cache_creation_input_tokens": 99})
    assert u.cache_creation_5m_tokens == 99
    assert u.cache_creation_1h_tokens == 0


def test_cheaper_alternatives_to_opus_include_haiku():
    ids = {m.id for m in cheaper_than("claude-opus-5")}
    assert "claude-haiku-4-5" in ids
    assert "claude-fable-5-1" not in ids


def test_costs_of_the_same_model_add_up():
    m = get_model("claude-opus-5")
    a = price(Usage(input_tokens=100), m)
    b = price(Usage(output_tokens=100), m)
    assert (a + b).total == pytest.approx(a.total + b.total)


def test_costs_of_different_models_refuse_to_add():
    a = price(Usage(input_tokens=1), get_model("claude-opus-5"))
    b = price(Usage(input_tokens=1), get_model("claude-sonnet-5"))
    with pytest.raises(ValueError):
        a + b
