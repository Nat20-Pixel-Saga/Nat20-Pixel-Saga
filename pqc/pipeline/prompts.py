"""Prompt templates and model routing for each pipeline step."""
from __future__ import annotations

import json
import re

from ..schema import load_schema
from ..state import ROOT
from .claude import MODELS, Request

PROMPTS = ROOT / "prompts"

# step -> (template, schema, tool name, audience, max output tokens)
STEPS = {
    "campaign": ("campaign_planner", "campaign", "submit_campaign", "dm", 32000),
    "plan": ("planner", "plan", "submit_plan", "dm", 8000),
    "script": ("writer", "script", "submit_script", "dm", 12000),
    "continuity": ("checker", "continuity", "submit_continuity", "dm", 3000),
    "wiki_facts": ("wiki", "wiki_facts", "submit_wiki_facts", "public", 4000),
    "packaging": ("packager", "packaging", "submit_packaging", "public", 2000),
}

# Cheapest model that does each job well (see README "Costs").
ROUTING = {
    "campaign": "fable",      # once per campaign: long-range structure
    "plan": "sonnet",
    "script": "sonnet",       # "opus" on premieres, finales and milestone episodes
    "continuity": "haiku",
    "wiki_facts": "haiku",
    "packaging": "haiku",
}

TEMPERATURE = {"campaign": 0.7, "plan": 0.7, "script": 0.9, "continuity": 0.0, "wiki_facts": 0.0, "packaging": 0.6}


def model_for(step: str, entry: dict | None = None, premiere_finale: bool = False) -> str:
    key = ROUTING[step]
    if step == "script" and (premiere_finale or (entry and entry.get("milestone_level"))):
        key = "opus"
    return MODELS[key]


def render(template: str, **values) -> str:
    text = (PROMPTS / f"{template}.md").read_text(encoding="utf-8")

    def sub(m):
        key = m.group(1)
        if key not in values:
            raise KeyError(f"Prompt {template}: missing value for {{{{{key}}}}}")
        v = values[key]
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=1)

    return re.sub(r"\{\{(\w+)\}\}", sub, text)


def all_tools() -> list[dict]:
    """Every step's tool, always in the same order (shared cache prefix)."""
    from .claude import _api_schema
    return [{"name": tool, "description": f"Submit the {step.replace('_', ' ')} result.",
             "input_schema": _api_schema(load_schema(schema))}
            for step, (_, schema, tool, _, _) in STEPS.items()]


def build_request(step: str, model: str, core: str, **values) -> Request:
    template, schema, tool, _, max_tokens = STEPS[step]
    values.setdefault("feedback", "")
    return Request(
        step=step, model=model,
        system=[{"text": core, "cache": True}],
        user=render(template, **values),
        schema=load_schema(schema), tool_name=tool, max_tokens=max_tokens,
        temperature=TEMPERATURE[step], tools=all_tools(),
    )
