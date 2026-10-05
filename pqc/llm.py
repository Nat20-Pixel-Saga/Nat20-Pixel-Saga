"""Bridge between the encounter and a tactical language model.

The model never sees dice or HP math it could change. It is shown the
situation and a numbered menu from ``Encounter.legal_actions()`` and must
answer with JSON ``{"choice": <number>, "why": "<short reason>"}``. Anything
else falls back to the deterministic policy, and the fallback is logged.

Phase 1 ships the prompt and the parser; Phase 3 plugs in the API call by
passing ``call_model`` (a function ``prompt -> text``) to
:func:`make_llm_policy`.
"""
from __future__ import annotations

import json
import re
from typing import Callable

from .ai import simple_policy
from .combat import Encounter
from .creature import Creature

SYSTEM_PROMPT = (
    "You choose combat actions for one creature in a D&D 5e (SRD 5.2) fight on a pixel-art show. "
    "Stay in character: use the personality notes. Pick exactly one option number from the menu. "
    "Answer only with JSON: {\"choice\": <number>, \"why\": \"<= 12 words\"}."
)


def situation(enc: Encounter, c: Creature) -> dict:
    def brief(x: Creature) -> dict:
        return {
            "id": x.id, "name": x.name, "hp": f"{x.hp}/{x.max_hp}", "ac": x.ac, "pos": list(x.pos),
            "distance_ft": enc.dist(c, x), "conditions": sorted(x.conditions), "effects": [e.name for e in x.effects],
        }

    return {
        "round": enc.round,
        "you": {**brief(c), "speed_left_ft": enc.turn.movement, "actions": enc.turn.actions,
                "bonus_action": enc.turn.bonus_action, "attacks_left": enc.turn.attacks_left,
                "slots": {k: v["current"] for k, v in (c.spellcasting or {}).get("slots", {}).items()},
                "concentrating_on": c.concentration},
        "allies": [brief(a) for a in enc.allies_of(c, standing_only=False)],
        "enemies": [brief(e) for e in enc.enemies_of(c, standing_only=False) if not e.dead],
    }


def build_turn_prompt(enc: Encounter, c: Creature, personality: str = "") -> tuple[str, list[dict]]:
    menu = enc.legal_actions()
    lines = [f"{i}. {opt['label']} [{opt['cost']}]" + (f" hit≈{int(opt['hit_chance'] * 100)}%" if "hit_chance" in opt else "")
             for i, opt in enumerate(menu, start=1)]
    prompt = (
        f"{SYSTEM_PROMPT}\n\nPERSONALITY: {personality or 'n/a'}\n\n"
        f"SITUATION:\n{json.dumps(situation(enc, c), ensure_ascii=False)}\n\nMENU:\n" + "\n".join(lines)
    )
    return prompt, menu


_JSON = re.compile(r"\{.*\}", re.DOTALL)


def parse_choice(text: str, menu: list[dict]) -> dict | None:
    """Return the chosen intent, or None if the answer is unusable."""
    m = _JSON.search(text or "")
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        n = int(obj["choice"])
    except (ValueError, KeyError, TypeError):
        return None
    if not 1 <= n <= len(menu):
        return None
    return menu[n - 1]["intent"]


def make_llm_policy(call_model: Callable[[str], str], personalities: dict[str, str] | None = None):
    personalities = personalities or {}

    def policy(enc: Encounter, c: Creature) -> dict:
        prompt, menu = build_turn_prompt(enc, c, personalities.get(c.id, ""))
        try:
            intent = parse_choice(call_model(prompt), menu)
        except Exception as exc:  # noqa: BLE001 - network or model errors fall back
            enc.emit("policy_fallback", actor=c.id, reason=f"model error: {exc}")
            intent = None
        if intent is None:
            enc.emit("policy_fallback", actor=c.id, reason="unusable answer")
            return simple_policy(enc, c)
        return intent

    return policy
