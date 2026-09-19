import pytest

from tokenomics.tokens import estimate, estimate_json, flatten_content


def test_empty_text_is_free():
    assert estimate("") == 0


def test_estimate_lands_near_the_chars_over_four_rule():
    text = "The quick brown fox jumps over the lazy dog. " * 40
    n = estimate(text)
    assert len(text) / 6 < n < len(text) / 2.5


def test_longer_text_costs_more():
    assert estimate("hello " * 100) > estimate("hello " * 10)


def test_cjk_costs_about_one_token_per_character():
    assert 8 <= estimate("这是一段中文文本") <= 12


def test_flatten_reads_text_blocks():
    content = [{"type": "text", "text": "alpha"}, {"type": "text", "text": "beta"}]
    assert flatten_content(content) == "alpha\nbeta"


def test_flatten_keeps_non_text_blocks_accounted_for():
    out = flatten_content([{"type": "image", "source": {"data": "xyz"}}])
    assert "image" in out and "xyz" in out


def test_flatten_handles_a_bare_string():
    assert flatten_content("plain") == "plain"


def test_json_serialization_is_key_order_independent():
    assert estimate_json({"a": 1, "b": 2}) == estimate_json({"b": 2, "a": 1})
