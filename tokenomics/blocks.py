"""Decomposing a Messages API request into cacheable blocks.

The cache is a *prefix* match over the rendered request, in the order
``tools`` -> ``system`` -> ``messages``. Any byte that changes invalidates
everything after it, so the unit of analysis is the ordered list of blocks --
not the request as a whole.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from .tokens import estimate, flatten_content

SECTIONS = ("tools", "system", "messages")


@dataclass(frozen=True)
class Block:
    """One positional slot in the rendered prefix."""

    section: str
    index: int
    text: str
    label: str

    @property
    def tokens(self) -> int:
        return estimate(self.text)

    @property
    def key(self) -> str:
        return f"{self.section}[{self.index}]"


def render(request: Dict[str, Any]) -> List[Block]:
    """Decompose a request body into the blocks the cache matches on."""
    blocks: List[Block] = []

    for i, tool in enumerate(request.get("tools") or []):
        name = tool.get("name") or tool.get("type") or f"tool{i}"
        blocks.append(
            Block(
                "tools",
                i,
                json.dumps(tool, ensure_ascii=False, sort_keys=True),
                f"tool:{name}",
            )
        )

    system = request.get("system")
    if isinstance(system, str):
        if system:
            blocks.append(Block("system", 0, system, "system"))
    elif isinstance(system, list):
        for i, part in enumerate(system):
            blocks.append(Block("system", i, flatten_content(part), f"system[{i}]"))

    for i, message in enumerate(request.get("messages") or []):
        role = message.get("role", "?")
        blocks.append(
            Block("messages", i, flatten_content(message.get("content")), f"{role}[{i}]")
        )

    return blocks


def common_prefix(runs: Sequence[Sequence[Block]]) -> int:
    """Length of the longest block prefix shared by every run."""
    if not runs:
        return 0
    shortest = min(len(r) for r in runs)
    first = runs[0]
    for i in range(shortest):
        text = first[i].text
        section = first[i].section
        if any(r[i].text != text or r[i].section != section for r in runs[1:]):
            return i
    return shortest


def token_total(blocks: Sequence[Block]) -> int:
    return sum(b.tokens for b in blocks)


def first_divergence(runs: Sequence[Sequence[Block]]) -> Dict[str, Any]:
    """Describe the block where the runs stop agreeing.

    This is the single most useful diagnostic in the tool: everything after
    this point is uncacheable across the run, so if it sits early, that block
    is what is costing you money.
    """
    n = common_prefix(runs)
    if not runs or n >= min(len(r) for r in runs):
        return {"index": n, "reason": "runs agree for their whole shared length"}
    samples = []
    for run in runs[:3]:
        text = run[n].text
        samples.append(text if len(text) <= 160 else text[:157] + "...")
    return {
        "index": n,
        "block": runs[0][n].label,
        "section": runs[0][n].section,
        "samples": samples,
        "reason": "block content differs between requests",
    }
