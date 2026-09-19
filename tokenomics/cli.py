"""Command line interface: ``python -m tokenomics``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Sequence

from . import __version__
from .audit import scan_path
from .cache import analyse
from .pricing import CATALOG, DEFAULT_MODEL, Usage, get_model, price
from .report import money, render_analysis, render_findings, render_models
from .tokens import count_api, estimate, estimate_json


def load_requests(path: str) -> List[Dict[str, Any]]:
    """Read requests from a JSONL file, a JSON array, or stdin."""
    text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    text = text.strip()
    if not text:
        raise SystemExit("no input")
    if text.startswith("["):
        data = json.loads(text)
        if not isinstance(data, list):
            raise SystemExit("expected a JSON array of request bodies")
        return data
    requests = []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            requests.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}:{n}: invalid JSON: {exc}") from None
    return requests


def cmd_models(args: argparse.Namespace) -> int:
    print(render_models(CATALOG.values()))
    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    model = get_model(args.model)
    n = args.requests
    cached = min(args.cached, args.input)
    usage = Usage(
        input_tokens=(args.input - cached) * n,
        output_tokens=args.output * n,
        cache_read_input_tokens=cached * max(0, n - 1),
        cache_creation_5m_tokens=cached if args.ttl == "5m" else 0,
        cache_creation_1h_tokens=cached if args.ttl == "1h" else 0,
    )
    cost = price(usage, model, batch=args.batch)
    print(f"model    {model.id}{' (batch)' if args.batch else ''}")
    print(f"requests {n:,}")
    print(f"input    {usage.total_input_tokens:,} tok  -> {money(cost.input)}")
    if cached:
        print(f"  cached {cached:,} tok prefix, written once, read {max(0, n-1):,}x")
    print(f"output   {usage.output_tokens:,} tok  -> {money(cost.output)}")
    print(f"TOTAL    {money(cost.total)}")
    if not args.batch and model.batch_eligible:
        batched = price(usage, model, batch=True)
        print(f"\nSame traffic on the Batch API: {money(batched.total)} "
              f"(saves {money(cost.total - batched.total)}, async delivery).")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    requests = load_requests(args.file)
    result = analyse(requests, args.model, mode=args.mode, output_tokens=args.output)
    if args.json:
        print(json.dumps(
            {
                "model": result.model.id,
                "mode": result.mode,
                "requests": result.requests,
                "prefix_tokens": result.prefix_tokens,
                "volatile_tokens": result.volatile_tokens,
                "plans": [
                    {"name": p.name, "total_usd": round(p.total, 6), "detail": p.detail}
                    for p in result.plans
                ],
                "best": result.best.name,
                "savings_usd": round(result.savings, 6),
                "savings_pct": round(result.savings_pct, 2),
                "divergence": result.divergence,
                "warnings": result.warnings,
            },
            indent=2,
        ))
    else:
        print(render_analysis(result, scale=args.scale))
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    findings = scan_path(args.path, include_info=args.all)
    print(render_findings(findings, show_fixes=not args.quiet))
    blocking = [f for f in findings if f.severity == "high"]
    return 1 if (blocking and args.strict) else 0


def cmd_count(args: argparse.Namespace) -> int:
    if args.file == "-":
        text = sys.stdin.read()
    else:
        text = open(args.file, encoding="utf-8").read()
    if args.api:
        request = json.loads(text)
        if isinstance(request, list):
            request = request[0]
        n = count_api(request, model=args.model)
        print(f"{n:,} tokens (exact, count_tokens on {args.model})")
    else:
        n = estimate(text)
        print(f"~{n:,} tokens (offline estimate, +/-15%; use --api for exact)")
    model = get_model(args.model)
    print(f"as input on {model.id}: {money(n * model.input_per_mtok / 1_000_000)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tokenomics",
        description="Find and cut what your Claude API traffic costs.",
    )
    p.add_argument("--version", action="version", version=f"tokenomics {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    m = sub.add_parser("models", help="show the rate card")
    m.set_defaults(func=cmd_models)

    e = sub.add_parser("estimate", help="price a hypothetical workload")
    e.add_argument("--model", default=DEFAULT_MODEL)
    e.add_argument("--input", type=int, required=True, help="input tokens per request")
    e.add_argument("--output", type=int, default=0, help="output tokens per request")
    e.add_argument("--requests", type=int, default=1)
    e.add_argument("--cached", type=int, default=0,
                   help="tokens of the input that are a stable cached prefix")
    e.add_argument("--ttl", choices=("5m", "1h"), default="5m")
    e.add_argument("--batch", action="store_true", help="price on the Batch API")
    e.set_defaults(func=cmd_estimate)

    a = sub.add_parser("analyze", help="analyse real request bodies (JSONL or JSON array)")
    a.add_argument("file", help="path to requests, or - for stdin")
    a.add_argument("--model", default=DEFAULT_MODEL)
    a.add_argument("--mode", choices=("fanout", "conversation"), default="fanout")
    a.add_argument("--output", type=int, default=0, help="output tokens per request")
    a.add_argument("--scale", type=float, default=1.0,
                   help="project savings onto N times this volume")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_analyze)

    d = sub.add_parser("audit", help="scan source for silent cache invalidators")
    d.add_argument("path", nargs="?", default=".")
    d.add_argument("--all", action="store_true", help="include informational findings")
    d.add_argument("--quiet", action="store_true", help="omit the fix for each finding")
    d.add_argument("--strict", action="store_true", help="exit 1 on any high finding")
    d.set_defaults(func=cmd_audit)

    c = sub.add_parser("count", help="count tokens in a file")
    c.add_argument("file", help="path to a text file, or - for stdin")
    c.add_argument("--model", default=DEFAULT_MODEL)
    c.add_argument("--api", action="store_true",
                   help="use the exact count_tokens endpoint (needs credentials)")
    c.set_defaults(func=cmd_count)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
