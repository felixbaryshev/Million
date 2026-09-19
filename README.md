# tokenomics

Measure and cut what your Claude API traffic costs.

No dependencies, no telemetry, no API key required for the parts that matter.
Point it at your real request bodies and it tells you, in dollars, what you are
paying and what you would pay if the prompt cache were placed correctly.

```
pip install -e .
tokenomics analyze requests.jsonl --output 400 --scale 5000
```

```
strategy         cost   vs base  why
---------------  -----  -------  ---------------------------------------------
no cache         $0.99  +0%      prefix of ~2937 tok re-sent at full price 40x
cache (5m TTL)   $0.48  +52%     1 write + 39 reads; breaks even at 2 requests
batch, no cache  $0.49  +50%     50% off, results arrive asynchronously

At 5,000x this volume: $4,946 -> $2,387, saving $2,559.

Cache breaks at block 1 (user[0]). Everything from there on is uncacheable.
```

## Why this exists

A prompt cache miss never raises an error. It shows up only as
`cache_read_input_tokens: 0` on a request you expected to hit, and as a bill
that does not go down. One `datetime.now()` in a system prompt can double an
invoice and nothing in the stack will tell you.

This finds it.

## Commands

### `analyze` -- what your traffic costs, and what it could cost

Takes a JSONL file (or JSON array) of Messages API request bodies.

```
tokenomics analyze requests.jsonl --model claude-opus-5 --output 400
tokenomics analyze turns.jsonl --mode conversation
tokenomics analyze requests.jsonl --json    # machine-readable
```

Two traffic shapes, because they cache differently:

| mode | shape | what caching does |
|---|---|---|
| `fanout` (default) | N independent requests sharing a prefix | prefix written once, read N-1 times |
| `conversation` | successive turns of one transcript | breakpoint moves forward; each turn writes only its delta |

The most useful line in the output is the last one: **where the cache breaks.**
Everything after that block is uncacheable, so if it sits at block 0 your
requests share no prefix at all and no breakpoint placement will save you
anything until you reorder them.

### `audit` -- find silent cache invalidators in source

```
tokenomics audit src/ --strict
```

Scans Python, TypeScript, Go, Ruby, Java, PHP and C# for the patterns that
quietly destroy a cache: clock readings and random ids rendered into a prefix,
`json.dumps` without `sort_keys`, tool lists built from sets, mutated system
prompts, `tiktoken`, and lowballed `max_tokens`. Each finding carries the fix.

`--strict` exits 1 on any high-severity finding, so it works in CI.

### `estimate` -- price a change before you ship it

```
tokenomics estimate --input 40000 --output 800 --requests 10000 --cached 38000
```

```
input    400,000,000 tok  -> $290.22
output     8,000,000 tok  -> $200.00
TOTAL    $490.22
Same traffic on the Batch API: $245.11
```

Without the cached prefix that same traffic is $2,200. That gap is the whole
point of the tool.

### `models` -- the rate card

```
tokenomics models
```

### `count` -- tokens in a file

```
tokenomics count prompt.txt              # offline estimate, no credentials
tokenomics count request.json --api      # exact, via count_tokens
```

## The economics it encodes

Cache reads cost 0.1x the base input price (0.025x on Claude Fable 5.1).
Writes cost 1.25x at the 5-minute TTL and 2x at the 1-hour TTL. So:

- **5m TTL breaks even at 2 requests** (1.25 + 0.1 = 1.35 against 2.0 uncached).
- **1h TTL breaks even at 3** (2.0 + 0.2 = 2.2 against 3.0).

The 1-hour TTL is for bursty traffic with gaps longer than five minutes. If
real requests arrive more often than that they keep the cache warm on their
own, and the doubled write price buys nothing.

The Batch API is a flat 50% off both directions for traffic that can wait.

Prefixes shorter than the model's floor (roughly 1-4K tokens, model-dependent)
**never cache and never warn**. The tool flags this rather than quoting you
savings that will not arrive.

## Accuracy

Offline token estimates are a heuristic, good to roughly +/-15% on prose and
code. They are for ranking options. Before you quote a number at someone, use
`--api` for exact counts from `count_tokens` -- it is free.

Never use `tiktoken`: it is a different tokenizer and will not match what you
are billed. The audit flags it.

Prices are Anthropic first-party rates. Bedrock and Vertex are partner-operated
and priced separately; do not use this table for them.

## Verifying a finding

Every rule here is a heuristic over source text. Confirm one before you rewrite
anything:

```python
r1 = client.messages.create(**request)
r2 = client.messages.create(**request)   # byte-identical
print(r2.usage.cache_read_input_tokens)  # 0 means the cache is not hitting
```

## Tests

```
pip install -e ".[dev]"
pytest
```

70 tests, no network, no credentials.

## License

MIT.
