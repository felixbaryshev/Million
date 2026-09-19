import json

import pytest

from tokenomics.cli import main


def test_models_lists_the_rate_card(capsys):
    assert main(["models"]) == 0
    out = capsys.readouterr().out
    assert "claude-opus-5" in out and "in/MTok" in out


def test_estimate_prices_a_workload(capsys):
    assert main(["estimate", "--input", "1000", "--output", "100"]) == 0
    assert "TOTAL" in capsys.readouterr().out


def test_estimate_rejects_an_unknown_model(capsys):
    assert main(["estimate", "--model", "gpt-4", "--input", "1"]) == 2
    assert "unknown model" in capsys.readouterr().err


def test_analyze_reports_savings(tmp_path, capsys):
    path = tmp_path / "r.jsonl"
    prefix = "Stable policy text. " * 900
    path.write_text("\n".join(
        json.dumps({"system": prefix, "messages": [{"role": "user", "content": f"q{i}"}]})
        for i in range(25)
    ))
    assert main(["analyze", str(path), "--output", "300"]) == 0
    assert "saving" in capsys.readouterr().out


def test_analyze_emits_machine_readable_json(tmp_path, capsys):
    path = tmp_path / "r.jsonl"
    prefix = "Stable policy text. " * 900
    path.write_text("\n".join(
        json.dumps({"system": prefix, "messages": [{"role": "user", "content": f"q{i}"}]})
        for i in range(5)
    ))
    assert main(["analyze", str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["savings_pct"] > 0
    assert payload["model"] == "claude-opus-5"


def test_analyze_accepts_a_json_array(tmp_path, capsys):
    path = tmp_path / "r.json"
    path.write_text(json.dumps([
        {"system": "x" * 40, "messages": [{"role": "user", "content": "a"}]},
    ]))
    assert main(["analyze", str(path)]) == 0


def test_analyze_reports_the_offending_line_on_bad_json(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"ok": 1}\nnot json\n')
    with pytest.raises(SystemExit, match="bad.jsonl:2"):
        main(["analyze", str(path)])


def test_audit_reports_a_clean_tree(tmp_path, capsys):
    (tmp_path / "ok.py").write_text('SYSTEM = "hi"\n')
    assert main(["audit", str(tmp_path)]) == 0
    assert "No cache invalidators" in capsys.readouterr().out


def test_audit_strict_fails_on_a_high_finding(tmp_path):
    (tmp_path / "bad.py").write_text(
        'import datetime\nsystem = f"{datetime.datetime.now()}"\n'
        'client.messages.create(system=system)\n'
    )
    assert main(["audit", str(tmp_path), "--strict"]) == 1


def test_count_estimates_a_file(tmp_path, capsys):
    path = tmp_path / "t.txt"
    path.write_text("hello world " * 100)
    assert main(["count", str(path)]) == 0
    out = capsys.readouterr().out
    assert "tokens" in out and "claude-opus-5" in out
