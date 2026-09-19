"""Static scan for silent prompt-cache invalidators.

A cache miss never raises. It shows up only as ``cache_read_input_tokens: 0``
on a request you expected to hit, and as a bill that does not go down. These
rules catch the patterns that cause it -- volatile values rendered into a
prefix that is otherwise stable.

Every finding is a heuristic over source text. Confirm one by checking
``usage.cache_read_input_tokens`` across two identical requests before you
rewrite anything.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterator, List, Optional, Sequence

SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rb", ".java", ".php", ".cs")

SKIP_DIRS = {
    ".git", ".hg", "node_modules", "__pycache__", ".venv", "venv", "dist",
    "build", ".mypy_cache", ".pytest_cache", ".tox", "vendor", "target",
}


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: "re.Pattern[str]"
    severity: str
    message: str
    fix: str
    #: When set, the rule only fires if this also matches somewhere nearby.
    context: Optional["re.Pattern[str]"] = None


def _rx(p: str) -> "re.Pattern[str]":
    return re.compile(p)


_PROMPT_CONTEXT = _rx(
    r"system\s*[=:]|system_prompt|systemPrompt|SYSTEM_PROMPT|"
    r"messages\s*[=:]|tools\s*[=:]|cache_control|cacheControl"
)

RULES: Sequence[Rule] = (
    Rule(
        "clock-in-prefix",
        _rx(r"datetime\.(now|utcnow|today)\(|time\.time\(|Date\.now\(|new Date\(|"
            r"time\.Now\(|Time\.now|DateTime\.(Now|UtcNow)|LocalDateTime\.now"),
        "high",
        "A clock reading appears next to prompt construction.",
        "A timestamp in the cached prefix changes every request, so nothing "
        "after it can ever hit. Move it below the last cache_control "
        "breakpoint -- into the final user message, not the system prompt.",
        context=_PROMPT_CONTEXT,
    ),
    Rule(
        "random-in-prefix",
        _rx(r"uuid4\(|uuid\.New|randomUUID\(|Math\.random\(|random\.(random|choice|randint)\(|"
            r"secrets\.token_"),
        "high",
        "A random or unique value appears next to prompt construction.",
        "Request ids, trace ids and nonces belong after the breakpoint. One "
        "uuid in a system prompt costs you the entire cache.",
        context=_PROMPT_CONTEXT,
    ),
    Rule(
        "unsorted-json",
        _rx(r"json\.dumps\((?![^)]*sort_keys)"),
        "medium",
        "json.dumps without sort_keys=True.",
        "Python dict order is insertion order, not content order. Two "
        "semantically identical payloads can serialize to different bytes and "
        "miss the cache. Pass sort_keys=True for anything in the prefix.",
        context=_PROMPT_CONTEXT,
    ),
    Rule(
        "set-iteration",
        _rx(r"tools\s*=\s*\[[^\]]*for\s+\w+\s+in\s+(set\(|\{)|for\s+\w+\s+in\s+set\("),
        "medium",
        "Tool list built by iterating a set.",
        "Set iteration order is not guaranteed across runs. The tool list is "
        "the very first thing rendered, so an unstable order invalidates the "
        "whole request. Sort it.",
    ),
    Rule(
        "mutable-system-edit",
        _rx(r"system\s*(\+=|\.append\(|\.format\(|%\s*\()"),
        "medium",
        "The system prompt is mutated or interpolated per request.",
        "Every edit to the top-level system field resets the cache. For "
        "mid-conversation operator instructions, append a "
        "{'role': 'system', ...} entry to messages[] instead -- it preserves "
        "the cached prefix (Opus 5, Opus 4.8, Fable 5/5.1; not Sonnet 5).",
    ),
    Rule(
        "effort-switch",
        _rx(r"effort\s*[=:]\s*(\"|')(low|medium|high|xhigh|max)"),
        "low",
        "An effort level is set here.",
        "Changing top-level effort mid-conversation invalidates the messages "
        "cache. On Opus 5 / Fable 5.1 use the per-message effort system "
        "message (beta mid-conversation-output-config-2026-07-01) to change "
        "it without a cache reset.",
        context=_rx(r"cache_control|cacheControl|messages\s*[=:]"),
    ),
    Rule(
        "no-breakpoint",
        _rx(r"\.messages\.(create|stream)\(|messages\.create\(|Messages\.New\("),
        "info",
        "An API call site.",
        "Check that a cache_control breakpoint sits at the end of this "
        "request's stable prefix. No breakpoint means no caching at all -- "
        "the most expensive default there is.",
    ),
    Rule(
        "tiktoken",
        _rx(r"^\s*import\s+tiktoken\b|\bfrom\s+tiktoken\b|\btiktoken\s*\.|"
            r"require\(\s*[\"']tiktoken|from\s+[\"']tiktoken"),
        "high",
        "tiktoken is used to count tokens.",
        "tiktoken implements a different tokenizer and will not match what "
        "Anthropic bills you. Use POST /v1/messages/count_tokens -- it is "
        "free and exact.",
    ),
    Rule(
        "lowball-max-tokens",
        _rx(r"max_tokens\s*[=:]\s*(?:[1-9]\d{0,2})\b|maxTokens\s*[=:]\s*(?:[1-9]\d{0,2})\b"),
        "low",
        "max_tokens is set below 1000.",
        "A truncated response has to be retried, and you pay for both. Low "
        "caps are right for classification; for anything generative, default "
        "to ~16000 non-streaming or ~64000 streaming.",
    ),
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    severity: str
    message: str
    fix: str
    source: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  [{self.severity}] {self.rule}: {self.message}"


SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}

_TRIPLE_QUOTES = ('"""', "'''")
_LINE_COMMENTS = ("#", "//", "*", "--", "/*")


def _blank_commentary(lines: Sequence[str]) -> List[str]:
    """Blank out comments and docstrings, keeping line numbering intact.

    A rule must not fire on prose. Code that *discusses* a clock reading in a
    comment is not code that calls one -- and a file documenting these very
    rules would otherwise report itself. Inline string literals are kept,
    because an f-string is exactly where an interpolated clock hides.
    """
    out: List[str] = []
    fence: Optional[str] = None
    in_block_comment = False

    for raw in lines:
        line = raw

        if fence is not None:
            if fence in line:
                fence = None
            out.append("")
            continue

        if in_block_comment:
            if "*/" in line:
                in_block_comment = False
                line = line.split("*/", 1)[1]
            else:
                out.append("")
                continue

        stripped = line.strip()

        if stripped.startswith(_LINE_COMMENTS):
            if stripped.startswith("/*") and "*/" not in stripped:
                in_block_comment = True
            out.append("")
            continue

        opened = False
        for quote in _TRIPLE_QUOTES:
            if stripped.startswith(quote):
                # A docstring, unless it also closes on this line.
                if stripped.count(quote) == 1:
                    fence = quote
                opened = True
                break
        if opened:
            out.append("")
            continue

        if "/*" in line and "*/" not in line:
            in_block_comment = True
            line = line.split("/*", 1)[0]

        out.append(line)

    return out


def iter_sources(root: str, suffixes: Sequence[str] = SOURCE_SUFFIXES) -> Iterator[str]:
    """Yield source file paths under ``root``, skipping vendored trees."""
    if os.path.isfile(root):
        yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in sorted(filenames):
            if name.endswith(tuple(suffixes)):
                yield os.path.join(dirpath, name)


def scan_text(
    text: str,
    path: str = "<string>",
    rules: Sequence[Rule] = RULES,
    context_lines: int = 12,
    include_info: bool = False,
) -> List[Finding]:
    """Run the rule set over one file's contents."""
    lines = text.splitlines()
    code = _blank_commentary(lines)
    findings: List[Finding] = []
    for rule in rules:
        if rule.severity == "info" and not include_info:
            continue
        for i, line in enumerate(code):
            if not rule.pattern.search(line):
                continue
            if rule.context is not None:
                lo = max(0, i - context_lines)
                hi = min(len(code), i + context_lines + 1)
                if not rule.context.search("\n".join(code[lo:hi])):
                    continue
            findings.append(
                Finding(
                    path=path,
                    line=i + 1,
                    rule=rule.id,
                    severity=rule.severity,
                    message=rule.message,
                    fix=rule.fix,
                    source=lines[i].strip()[:120],
                )
            )
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.line))
    return findings


def scan_path(
    root: str,
    rules: Sequence[Rule] = RULES,
    include_info: bool = False,
) -> List[Finding]:
    """Scan every source file under ``root``."""
    findings: List[Finding] = []
    for path in iter_sources(root):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        findings.extend(scan_text(text, path, rules, include_info=include_info))
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.path, f.line))
    return findings
