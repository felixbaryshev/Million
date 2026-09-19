from tokenomics.blocks import common_prefix, first_divergence, render, token_total


def req(system="sys", user="hi", tools=None):
    body = {"system": system, "messages": [{"role": "user", "content": user}]}
    if tools:
        body["tools"] = tools
    return body


def test_render_order_is_tools_then_system_then_messages():
    blocks = render(req(tools=[{"name": "search"}]))
    assert [b.section for b in blocks] == ["tools", "system", "messages"]


def test_identical_requests_share_their_whole_prefix():
    a, b = render(req()), render(req())
    assert common_prefix([a, b]) == len(a)


def test_divergence_points_at_the_first_differing_block():
    a, b = render(req(user="one")), render(req(user="two"))
    d = first_divergence([a, b])
    assert d["index"] == 1
    assert d["block"] == "user[0]"
    assert sorted(d["samples"]) == ["one", "two"]


def test_a_varying_system_prompt_kills_the_whole_prefix():
    a, b = render(req(system="A")), render(req(system="B"))
    assert common_prefix([a, b]) == 0


def test_tool_order_changes_invalidate_everything():
    t1 = [{"name": "a"}, {"name": "b"}]
    a, b = render(req(tools=t1)), render(req(tools=list(reversed(t1))))
    assert common_prefix([a, b]) == 0


def test_tool_key_order_does_not_invalidate():
    a = render(req(tools=[{"name": "s", "description": "d"}]))
    b = render(req(tools=[{"description": "d", "name": "s"}]))
    assert common_prefix([a, b]) == len(a)


def test_system_as_a_block_list_is_split_per_block():
    blocks = render({"system": [{"type": "text", "text": "x"},
                                {"type": "text", "text": "y"}],
                     "messages": []})
    assert [b.label for b in blocks] == ["system[0]", "system[1]"]


def test_token_total_sums_the_blocks():
    blocks = render(req(system="a longer system prompt here"))
    assert token_total(blocks) == sum(b.tokens for b in blocks)
