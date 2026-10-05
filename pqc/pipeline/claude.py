"""Minimal Claude API client (standard library only) with a cost ledger.

* Structured output: every call forces one tool whose ``input_schema`` is the
  step's JSON Schema, so the model must return exactly that shape.
* Prompt caching: the long, stable context (series bible, voice sheets, canon
  digest) is sent as system blocks marked ``cache_control`` (5-minute cache).
* Batch API: ``submit_batch`` / ``batch_results`` for the steps that can wait
  (planning, writing, wiki, packaging) at 50% of the price.
* Replay: ``ReplayClient`` serves recorded outputs from ``fixtures/`` with
  estimated usage, so the pipeline runs offline, in CI and in tests.

Set ``ANTHROPIC_API_KEY`` for live calls.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

API = "https://api.anthropic.com/v1"
VERSION = "2023-06-01"

MODELS = {
    "fable": "claude-fable-5-1",
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5-5",
    "haiku": "claude-haiku-4-5-20251001",
}

# USD per million tokens (platform.claude.com/docs/en/about-claude/pricing, October 2026).
PRICES = {
    "claude-fable-5-1": {"in": 10.0, "out": 50.0, "cache_write": 12.5, "cache_read": 0.25},
    "claude-opus-5-5": {"in": 4.0, "out": 20.0, "cache_write": 5.0, "cache_read": 0.20},
    "claude-sonnet-5-5": {"in": 2.0, "out": 10.0, "cache_write": 2.5, "cache_read": 0.20},
    "claude-haiku-4-5-20251001": {"in": 1.0, "out": 5.0, "cache_write": 1.25, "cache_read": 0.10},
}
BATCH_DISCOUNT = 0.5


def estimate_tokens(text: str) -> int:
    """Rough token estimate (no tokenizer offline): ~3.2 characters per token
    for the newer tokenizer on English prose and JSON."""
    return max(1, int(len(text) / 3.2))


@dataclass
class Usage:
    model: str
    step: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    batch: bool = False
    estimated: bool = False

    @property
    def cost(self) -> float:
        p = PRICES[self.model]
        c = (self.input_tokens * p["in"] + self.output_tokens * p["out"] + self.cache_write_tokens * p["cache_write"]
             + self.cache_read_tokens * p["cache_read"]) / 1e6
        return c * (BATCH_DISCOUNT if self.batch else 1.0)

    def to_dict(self) -> dict:
        return {**self.__dict__, "cost_usd": round(self.cost, 5)}


@dataclass
class Ledger:
    entries: list[Usage] = field(default_factory=list)

    def add(self, u: Usage) -> None:
        self.entries.append(u)

    @property
    def total(self) -> float:
        return sum(u.cost for u in self.entries)

    def summary(self) -> dict:
        by_step: dict[str, dict] = {}
        for u in self.entries:
            s = by_step.setdefault(u.step, {"model": u.model, "calls": 0, "input": 0, "cache_write": 0, "cache_read": 0,
                                            "output": 0, "batch": u.batch, "cost_usd": 0.0})
            s["calls"] += 1
            s["input"] += u.input_tokens
            s["cache_write"] += u.cache_write_tokens
            s["cache_read"] += u.cache_read_tokens
            s["output"] += u.output_tokens
            s["cost_usd"] = round(s["cost_usd"] + u.cost, 5)
        return {"total_usd": round(self.total, 4), "estimated": any(u.estimated for u in self.entries), "steps": by_step}


@dataclass
class Request:
    step: str
    model: str
    system: list[dict]  # [{"text": ..., "cache": bool}]
    user: str
    schema: dict
    tool_name: str
    max_tokens: int = 8000
    temperature: float = 0.8
    # All step tools, in a fixed order, so the tools + system prefix is the same
    # for every step that uses this model and the prompt cache is shared across
    # steps; ``tool_choice`` (which only affects the message-level cache) picks
    # the step's tool. Falls back to the step's own tool alone.
    tools: list[dict] | None = None

    def body(self) -> dict:
        system = []
        for blk in self.system:
            b = {"type": "text", "text": blk["text"]}
            if blk.get("cache"):
                b["cache_control"] = {"type": "ephemeral"}
            system.append(b)
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system,
            "messages": [{"role": "user", "content": self.user}],
            "tools": self.tool_list(),
            "tool_choice": {"type": "tool", "name": self.tool_name},
        }

    def tool_list(self) -> list[dict]:
        if self.tools:
            return self.tools
        return [{"name": self.tool_name, "description": f"Submit the {self.step} result.",
                 "input_schema": _api_schema(self.schema)}]

    def prompt_chars(self) -> tuple[int, int]:
        """(characters in the cacheable prefix, characters sent fresh)."""
        any_cached = any(b.get("cache") for b in self.system)
        tools = len(json.dumps(self.tool_list()))
        cached = sum(len(b["text"]) for b in self.system if b.get("cache")) + (tools if any_cached else 0)
        fresh = sum(len(b["text"]) for b in self.system if not b.get("cache")) + len(self.user) + \
            (0 if any_cached else tools)
        return cached, fresh

    def prefix_key(self) -> str:
        import hashlib
        h = hashlib.sha256(json.dumps([self.model, self.tool_list(),
                                       [b["text"] for b in self.system if b.get("cache")]]).encode())
        return h.hexdigest()[:16]


def _api_schema(schema: dict) -> dict:
    """Drop JSON-Schema keys the tools API doesn't need ($schema, $id, title)."""
    return {k: v for k, v in schema.items() if k not in ("$schema", "$id", "title")}


class ClaudeError(RuntimeError):
    pass


class Client:
    """Live client. Retries on 429/5xx with backoff."""

    def __init__(self, api_key: str | None = None, ledger: Ledger | None = None, timeout: int = 300):
        self.key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.key:
            raise ClaudeError("ANTHROPIC_API_KEY is not set")
        self.ledger = ledger or Ledger()
        self.timeout = timeout

    def _post(self, path: str, body: dict | None = None, method: str = "POST") -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={
            "x-api-key": self.key, "anthropic-version": VERSION, "content-type": "application/json"})
        for attempt in range(6):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 529) and attempt < 5:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise ClaudeError(f"{e.code}: {e.read().decode(errors='replace')[:500]}") from e
        raise ClaudeError("unreachable")

    def call(self, req: Request) -> dict:
        resp = self._post("/messages", req.body())
        self.ledger.add(_usage(req, resp.get("usage", {}), batch=False))
        return _tool_input(resp, req.tool_name)

    # ------------------------------------------------------------ batch
    def submit_batch(self, reqs: list[Request]) -> str:
        body = {"requests": [{"custom_id": f"{r.step}-{i}", "params": r.body()} for i, r in enumerate(reqs)]}
        return self._post("/messages/batches", body)["id"]

    def batch_results(self, batch_id: str, reqs: list[Request], poll: int = 30, max_wait: int = 86400) -> list[dict]:
        waited = 0
        while True:
            info = self._post(f"/messages/batches/{batch_id}", method="GET")
            if info.get("processing_status") == "ended":
                break
            if waited > max_wait:
                raise ClaudeError(f"Batch {batch_id} did not finish")
            time.sleep(poll)
            waited += poll
        req = urllib.request.Request(info["results_url"], headers={"x-api-key": self.key, "anthropic-version": VERSION})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            lines = [json.loads(line) for line in r.read().decode().splitlines() if line.strip()]
        by_id = {line["custom_id"]: line for line in lines}
        out = []
        for i, rq in enumerate(reqs):
            res = by_id[f"{rq.step}-{i}"]["result"]
            if res["type"] != "succeeded":
                raise ClaudeError(f"Batch item {rq.step}-{i}: {res}")
            msg = res["message"]
            self.ledger.add(_usage(rq, msg.get("usage", {}), batch=True))
            out.append(_tool_input(msg, rq.tool_name))
        return out


def _usage(req: Request, u: dict, batch: bool) -> Usage:
    return Usage(req.model, req.step, u.get("input_tokens", 0), u.get("output_tokens", 0),
                 u.get("cache_creation_input_tokens", 0), u.get("cache_read_input_tokens", 0), batch)


def _tool_input(resp: dict, tool: str) -> dict:
    for block in resp.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == tool:
            return block["input"]
    raise ClaudeError(f"No {tool} tool call in response (stop_reason={resp.get('stop_reason')})")


class ReplayClient:
    """Serves recorded outputs from ``fixtures/<episode>/<step>.json``.

    Usage is estimated from the actual prompt size and the recorded output,
    and the cache is assumed warm after the first call of a run, matching the
    live pipeline's behaviour."""

    def __init__(self, fixtures: Path, ledger: Ledger | None = None, batch: bool = True):
        self.fixtures = Path(fixtures)
        self.ledger = ledger or Ledger()
        self.batch = batch
        self._warm: set[str] = set()

    def call(self, req: Request) -> dict:
        path = self.fixtures / f"{req.step}.json"
        if not path.exists():
            raise ClaudeError(f"No recorded output for step {req.step!r} at {path}")
        out = json.loads(path.read_text(encoding="utf-8"))
        cached_chars, fresh_chars = req.prompt_chars()
        cached_tok = estimate_tokens("x" * cached_chars) if cached_chars else 0
        key = req.prefix_key()
        first = key not in self._warm
        self._warm.add(key)
        u = Usage(req.model, req.step,
                  input_tokens=estimate_tokens("x" * fresh_chars),
                  output_tokens=estimate_tokens(json.dumps(out)),
                  cache_write_tokens=cached_tok if first else 0,
                  cache_read_tokens=0 if first else cached_tok,
                  batch=self.batch, estimated=True)
        self.ledger.add(u)
        return out


class RecordingClient:
    """Wraps a live client and saves every output as a fixture."""

    def __init__(self, inner: Client, fixtures: Path):
        self.inner = inner
        self.ledger = inner.ledger
        self.fixtures = Path(fixtures)

    def call(self, req: Request) -> dict:
        out = self.inner.call(req)
        self.fixtures.mkdir(parents=True, exist_ok=True)
        (self.fixtures / f"{req.step}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
        return out
