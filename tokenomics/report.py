"""Human-readable rendering of analyses and findings."""

from __future__ import annotations

from typing import Iterable, List, Sequence

from .audit import Finding
from .cache import Analysis
from .pricing import CATALOG, Model


def money(value: float) -> str:
    """Format USD without pretending to precision we do not have."""
    if value == 0:
        return "$0"
    if abs(value) < 0.01:
        return f"${value:.5f}"
    if abs(value) < 1000:
        return f"${value:,.2f}"
    return f"${value:,.0f}"


def table(rows: Sequence[Sequence[str]], headers: Sequence[str]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    out.append("  ".join("-" * w for w in widths))
    for row in rows:
        out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(out)


def render_models(models: Iterable[Model]) -> str:
    rows = []
    for m in models:
        rows.append([
            m.id,
            f"{m.input_per_mtok:g}",
            f"{m.output_per_mtok:g}",
            f"{m.cache_read_per_mtok:g}",
            f"{m.cache_write_per_mtok('5m'):g}",
            f"{m.input_per_mtok / 2:g}",
            f"{m.context_window // 1000}K",
        ])
    body = table(
        rows,
        ["model", "in/MTok", "out/MTok", "cache rd", "cache wr", "batch in", "ctx"],
    )
    return body + "\n\nUSD per million tokens, Anthropic first-party rates."


def render_analysis(analysis: Analysis, scale: float = 1.0) -> str:
    a = analysis
    lines = [
        f"model      {a.model.id}",
        f"shape      {a.mode}, {a.requests} requests",
        f"prefix     ~{a.prefix_tokens:,} tokens shared across every request",
        f"volatile   ~{a.volatile_tokens:,} tokens that differ",
        f"output     ~{a.output_tokens:,} tokens assumed",
        "",
    ]

    rows = []
    baseline = a.baseline.total
    for plan in a.plans:
        delta = baseline - plan.total
        pct = "" if baseline == 0 else f"{delta / baseline * 100:+.0f}%"
        rows.append([plan.name, money(plan.total), pct, plan.detail])
    lines.append(table(rows, ["strategy", "cost", "vs base", "why"]))
    lines.append("")

    if a.savings > 0:
        lines.append(
            f"Best: {a.best.name} at {money(a.best.total)}, "
            f"saving {money(a.savings)} ({a.savings_pct:.0f}%) over this sample."
        )
        if scale != 1.0:
            s = a.scaled(scale)
            lines.append(
                f"At {scale:,.0f}x this volume: {money(s['baseline'])} -> "
                f"{money(s['best'])}, saving {money(s['savings'])}."
            )
    else:
        lines.append("No caching strategy beats sending these requests as-is.")

    if a.divergence and "block" in a.divergence:
        d = a.divergence
        lines += [
            "",
            f"Cache breaks at block {d['index']} ({d['block']}). Everything from "
            "there on is uncacheable. Samples:",
        ]
        for s in d["samples"]:
            lines.append(f"  - {s}")
        if d["index"] == 0:
            lines.append(
                "  This is block 0 -- the requests share no prefix at all, so "
                "caching cannot help until you move stable content to the front."
            )

    for w in a.warnings:
        lines += ["", f"WARNING: {w}"]

    return "\n".join(lines)


def render_findings(findings: List[Finding], show_fixes: bool = True) -> str:
    if not findings:
        return "No cache invalidators found."
    lines = []
    counts = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
        lines.append(str(f))
        lines.append(f"    {f.source}")
        if show_fixes:
            lines.append(f"    fix: {f.fix}")
        lines.append("")
    summary = ", ".join(f"{n} {sev}" for sev, n in sorted(counts.items()))
    lines.append(f"{len(findings)} finding(s): {summary}")
    lines.append(
        "Confirm any of these by checking usage.cache_read_input_tokens across "
        "two identical requests before rewriting code."
    )
    return "\n".join(lines)
