from tokenomics.audit import scan_text

CLOCK = '''
import datetime
system = f"You are an agent. Now: {datetime.datetime.now()}"
resp = client.messages.create(system=system, messages=msgs)
'''

CLEAN = '''
SYSTEM_PROMPT = "You are an agent."
resp = client.messages.create(system=SYSTEM_PROMPT, messages=msgs, max_tokens=16000)
'''


def ids(findings):
    return {f.rule for f in findings}


def test_a_clock_in_the_prefix_is_a_high_finding():
    findings = scan_text(CLOCK, "a.py")
    assert "clock-in-prefix" in ids(findings)
    assert [f for f in findings if f.rule == "clock-in-prefix"][0].severity == "high"


def test_a_clean_prompt_produces_no_findings():
    assert scan_text(CLEAN, "b.py") == []


def test_a_clock_far_from_any_prompt_is_not_reported():
    unrelated = "\n".join(["import time"] + ["pass"] * 40 + ["t = time.time()"])
    assert "clock-in-prefix" not in ids(scan_text(unrelated, "c.py"))


def test_random_ids_near_a_prompt_are_flagged():
    src = 'system = "agent " + str(uuid.uuid4())\nclient.messages.create(system=system)'
    assert "random-in-prefix" in ids(scan_text(src, "d.py"))


def test_unsorted_json_near_tools_is_flagged():
    src = 'tools = json.dumps(defs)\nclient.messages.create(tools=tools)'
    assert "unsorted-json" in ids(scan_text(src, "e.py"))


def test_sorted_json_is_accepted():
    src = 'tools = json.dumps(defs, sort_keys=True)\nclient.messages.create(tools=tools)'
    assert "unsorted-json" not in ids(scan_text(src, "f.py"))


def test_tiktoken_is_flagged_anywhere():
    assert "tiktoken" in ids(scan_text("import tiktoken", "g.py"))


def test_lowball_max_tokens_is_flagged():
    assert "lowball-max-tokens" in ids(scan_text("max_tokens=200", "h.py"))


def test_generous_max_tokens_is_not_flagged():
    assert "lowball-max-tokens" not in ids(scan_text("max_tokens=16000", "i.py"))


def test_info_findings_are_opt_in():
    src = "client.messages.create(model='claude-opus-5')"
    assert scan_text(src, "j.py") == []
    assert "no-breakpoint" in ids(scan_text(src, "j.py", include_info=True))


def test_findings_are_ordered_by_severity():
    src = CLOCK + "\nmax_tokens=100\n"
    sev = [f.severity for f in scan_text(src, "k.py")]
    assert sev == sorted(sev, key=lambda s: ["high", "medium", "low", "info"].index(s))


def test_every_finding_carries_an_actionable_fix():
    for f in scan_text(CLOCK, "l.py"):
        assert len(f.fix) > 40


def test_a_commented_out_invalidator_is_not_flagged():
    src = '# system = f"{datetime.datetime.now()}"\nclient.messages.create(system=s)'
    assert "clock-in-prefix" not in ids(scan_text(src, "m.py"))


def test_prose_in_a_docstring_is_not_flagged():
    src = '"""We must never call datetime.now() inside a system prompt."""\n'
    assert scan_text(src, "n.py") == []


def test_a_javascript_line_comment_is_ignored():
    src = '// const system = `${Date.now()}`;\nclient.messages.create({system});'
    assert "clock-in-prefix" not in ids(scan_text(src, "o.js"))


def test_a_block_comment_is_ignored():
    src = '/*\n const s = `${Date.now()}`;\n*/\nclient.messages.create({system});'
    assert "clock-in-prefix" not in ids(scan_text(src, "p.js"))


def test_an_fstring_clock_is_still_caught_after_comment_stripping():
    src = 'system = f"now {datetime.datetime.now()}"\nclient.messages.create(system=system)'
    assert "clock-in-prefix" in ids(scan_text(src, "q.py"))


def test_merely_naming_tiktoken_in_a_string_is_not_usage():
    assert "tiktoken" not in ids(scan_text('LABEL = "tiktoken"', "r.py"))


def test_real_tiktoken_usage_is_still_caught():
    assert "tiktoken" in ids(scan_text("enc = tiktoken.get_encoding('cl100k')", "s.py"))


def test_the_scanner_does_not_report_itself():
    from tokenomics import audit as mod
    with open(mod.__file__, encoding="utf-8") as fh:
        assert scan_text(fh.read(), mod.__file__) == []
