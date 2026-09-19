"""Token counting.

Two backends:

* :func:`estimate` -- offline heuristic, no network, no API key. Good to
  roughly +/-15% on English prose and code. Use it to rank options.
* :func:`count_api` -- the real thing, via ``POST /v1/messages/count_tokens``.
  Free, exact, and the only number you should quote at someone. Never use
  ``tiktoken`` -- it is a different tokenizer and will mislead you.

Tokenizers differ across model generations, so a count measured on one model
is not transferable to another. Re-baseline when you migrate.
"""

from __future__ import annotations

import json
import re
from typing import Any, List, Optional

# Word-ish chunks, runs of whitespace, and everything else one char at a time.
_CHUNK = re.compile(r"[A-Za-z]+|[0-9]+|\s+|[^\sA-Za-z0-9]")

# Rough BPE behaviour: common short words are one token, longer words split
# every ~4 characters, digits split every ~3, and CJK runs about one token
# per character.
_CJK = re.compile(r"[　-鿿가-힯＀-￯]")


def estimate(text: str) -> int:
    """Estimate the token count of a string without calling the API."""
    if not text:
        return 0
    tokens = 0.0
    for chunk in _CHUNK.findall(text):
        head = chunk[0]
        if head.isspace():
            # Leading whitespace usually merges into the following token; only
            # runs longer than one character cost extra.
            tokens += max(0, len(chunk) - 1) * 0.5
        elif head.isdigit():
            tokens += max(1, len(chunk) / 3.0)
        elif head.isalpha():
            tokens += 1.0 if len(chunk) <= 5 else len(chunk) / 4.0
        elif _CJK.match(head):
            tokens += 1.0
        else:
            tokens += 0.5  # punctuation mostly merges with a neighbour
    return max(1, round(tokens))


def estimate_json(value: Any) -> int:
    """Estimate tokens for a value serialized the way the API sees it."""
    if isinstance(value, str):
        return estimate(value)
    return estimate(json.dumps(value, ensure_ascii=False, sort_keys=True))


def flatten_content(content: Any) -> str:
    """Reduce a message ``content`` field to the text the model reads.

    Non-text blocks (images, documents, tool results) are serialized whole so
    their bulk is still accounted for, even though the real token cost of an
    image is computed from its dimensions rather than its bytes.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if content.get("type") == "text":
            return content.get("text", "")
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    if isinstance(content, list):
        return "\n".join(flatten_content(block) for block in content)
    return str(content)


def count_api(
    request: dict,
    model: Optional[str] = None,
    client: Any = None,
) -> int:
    """Exact token count for a request body via the count_tokens endpoint.

    ``request`` is a Messages API body: ``system``, ``messages``, ``tools``.
    Requires the ``anthropic`` package and a resolvable credential (an API key
    or an ``ant auth login`` profile -- a bare client finds either).
    """
    try:
        import anthropic  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "exact counting needs the anthropic SDK: pip install anthropic"
        ) from exc

    if client is None:  # pragma: no cover - needs credentials
        import anthropic

        client = anthropic.Anthropic()

    body = {k: v for k, v in request.items() if k in ("system", "messages", "tools")}
    body["model"] = model or request.get("model") or "claude-opus-5"
    if not body.get("messages"):
        raise ValueError("count_tokens requires at least one message")
    return client.messages.count_tokens(**body).input_tokens


def counter(use_api: bool = False, model: Optional[str] = None, client: Any = None):
    """Return a ``(request) -> int`` callable for the chosen backend."""
    if not use_api:
        return lambda request: estimate_json(request)
    return lambda request: count_api(request, model=model, client=client)
