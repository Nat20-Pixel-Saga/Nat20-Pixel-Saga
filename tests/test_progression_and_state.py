import copy
import json
import unittest
from pathlib import Path

from helpers import ROOT, ScriptedDice, pc
from pqc import data
from pqc.llm import build_turn_prompt, make_llm_policy, parse_choice
from pqc.progression import (apply_ability_increase, arcane_recovery, level_for_xp, level_up, long_rest,
                             short_rest, unlight_rest_check)
from pqc.schema import validate, validate_named
from pqc.state import character_from_sheet, load_json, sheet_from_character

PARTY = ["brannoc", "ilsevel", "tamsin", "oriel"]
SUBCLASS = {"brannoc": "champion", "ilsevel": "evoker", "tamsin": "thief", "oriel": "life"}


def sheet(name):
    return load_json(ROOT / "state" / "genesis" / "party" / f"{name}.json")


class TestLevelling(unittest.TestCase):
    def test_xp_table(self):
        self.assertEqual([level_for_xp(x) for x in (0, 299, 300, 6500, 354999, 355000)], [1, 1, 2, 5, 19, 20])

    def test_brannoc_to_level_three(self):
        s = sheet("brannoc")
        r2 = level_up(s)
        self.assertEqual(s["hp"]["max"], 13 + 6 + 2 + 1)  # fixed 6 + Con 2 + Dwarven Toughness 1
        self.assertIn("Action Surge", r2["gains"])
        self.assertIn("action_surge", s["features"])
        with self.assertRaises(ValueError):
            level_up(copy.deepcopy(s))  # level 3 needs a subclass
        level_up(s, subclass="champion")
        c = character_from_sheet(s)
        self.assertEqual((c.level, c.crit_range, c.resources["action_surge"]["max"]), (3, 19, 1))

    def test_full_run_to_twenty_stays_valid(self):
        for name in PARTY:
            s = sheet(name)
            for lvl in range(2, 21):
                level_up(s, subclass=SUBCLASS[name] if lvl == 3 else None)
                errs = validate_named(s, "character")
                self.assertEqual(errs, [], f"{name} L{lvl}: {errs[:3]}")
            c = character_from_sheet(s)
            self.assertEqual((c.level, c.proficiency), (20, 6))
            if name == "brannoc":
                self.assertEqual((c.extra_attacks, c.crit_range), (3, 18))
            if name == "tamsin":
                self.assertEqual(c.sneak_attack_dice, 10)
            if name in ("ilsevel", "oriel"):
                self.assertEqual([c.spellcasting["slots"][str(i)]["max"] for i in range(1, 10)], [4, 3, 3, 3, 3, 2, 2, 1, 1])

    def test_level_five_milestones(self):
        s = sheet("ilsevel")
        for lvl in range(2, 6):
            rep = level_up(s, subclass="evoker" if lvl == 3 else None)
        self.assertEqual(rep["spell_slots"], [4, 3, 2])
        c = character_from_sheet(s)
        self.assertEqual(c.cantrip_dice_multiplier(), 2)  # Fire Bolt 2d10 at 5th
        self.assertIn("potent_cantrip", c.features)

    def test_asi_rules_and_con_retroactive(self):
        s = sheet("brannoc")
        for _ in range(3):
            level_up(s, subclass="champion" if s["level"] == 2 else None)
        hp = s["hp"]["max"]
        apply_ability_increase(s, {"con": 1, "str": 1})  # Con 15 -> 16: +1 HP per level
        self.assertEqual(s["hp"]["max"], hp + 4)
        with self.assertRaises(ValueError):
            apply_ability_increase(s, {"str": 3})
        s["abilities"]["str"] = 19
        with self.assertRaises(ValueError):
            apply_ability_increase(s, {"str": 2})


class TestRests(unittest.TestCase):
    def test_short_rest_hit_dice_and_resources(self):
        b = pc("brannoc")
        b.take_damage(8, "slashing")
        b.resources["second_wind"]["current"] = 0
        rep = short_rest(b, ScriptedDice([6]), hit_dice_to_spend=1)
        self.assertEqual(b.hp, 5 + 6 + 2)
        self.assertEqual(b.resources["second_wind"]["current"], 1)
        self.assertEqual(rep["hit_dice_spent"], 1)

    def test_long_rest(self):
        o = pc("oriel")
        o.take_damage(6, "fire")
        o.spellcasting["slots"]["1"]["current"] = 0
        o.heroic_inspiration = False
        o.exhaustion = 2
        long_rest(o)
        self.assertEqual((o.hp, o.slots_available(1), o.exhaustion, o.heroic_inspiration), (10, 2, 1, True))

    def test_arcane_recovery(self):
        i = pc("ilsevel")
        i.spellcasting["slots"]["1"]["current"] = 0
        arcane_recovery(i, {1: 1})  # level 1: budget 1 slot level
        self.assertEqual(i.slots_available(1), 1)
        with self.assertRaises(ValueError):
            arcane_recovery(i, {1: 1})

    def test_unlight_rest(self):
        b = pc("brannoc")
        self.assertEqual(unlight_rest_check(b, ScriptedDice([2]), "deep", lantern_nearby=False)["exhaustion_gained"], 1)
        self.assertEqual(unlight_rest_check(b, ScriptedDice([]), "deep", lantern_nearby=True)["exhaustion_gained"], 0)


class TestStateFiles(unittest.TestCase):
    def test_all_state_files_valid(self):
        for name in PARTY:
            self.assertEqual(validate_named(sheet(name), "character"), [], name)
        self.assertEqual(validate_named(load_json(ROOT / "state" / "world.json"), "world"), [])
        self.assertEqual(validate_named(load_json(ROOT / "state" / "genesis" / "world.json"), "world"), [])
        for p in (ROOT / "state" / "party").glob("*.json"):  # the live sheets too
            self.assertEqual(validate_named(load_json(p), "character"), [], p.name)
        for mid, m in data.monsters().items():
            self.assertEqual(validate_named(m, "monster"), [], mid)

    def test_validator_catches_errors(self):
        s = sheet("tamsin")
        s["abilities"]["dex"] = 40
        s["class"] = "bard"
        del s["hp"]
        errs = validate_named(s, "character")
        self.assertTrue(any("dex" in e for e in errs))
        self.assertTrue(any("class" in e or "bard" in e for e in errs))
        self.assertTrue(any("hp" in e for e in errs))

    def test_roundtrip_sheet(self):
        t = pc("tamsin")
        t.take_damage(4, "slashing")
        t.inventory["arrows"] -= 3
        s = sheet_from_character(t)
        self.assertEqual(validate_named(s, "character"), [])
        again = character_from_sheet(s)
        self.assertEqual((again.hp, again.inventory["arrows"], again.ac), (6, 17, 14))

    def test_referenced_data_exists(self):
        spells, weapons = data.spells(), data.weapons()
        for name in PARTY:
            s = sheet(name)
            for w in s["equipment"]["weapons"]:
                self.assertIn(w, weapons)
            sc = s.get("spellcasting")
            if sc:
                for sid in sc["cantrips"] + sc["prepared"] + sc.get("spellbook", []) + list(sc.get("free_casts", {})):
                    self.assertIn(sid, spells, f"{name}: {sid}")

    def test_world_ids_unique_and_linked(self):
        w = load_json(ROOT / "state" / "world.json")
        hooks = [h["id"] for h in w["hooks"]]
        self.assertEqual(len(hooks), len(set(hooks)))
        self.assertTrue(all(h["owner"] in PARTY for h in w["hooks"]))
        self.assertEqual(sorted(w["party"]["members"]), sorted(PARTY))
        self.assertEqual(len(w["party"]["bonds"]), 6)

    def test_episode_record_from_demo_is_valid(self):
        import subprocess
        import sys
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "demo_combat.py"), "--quiet"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ep = json.loads((ROOT / "out" / "C01-E001.json").read_text())
        self.assertEqual(validate_named(ep, "episode"), [])
        for roll in ep["rolls"][:20]:
            self.assertEqual(validate_named(roll, "roll"), [])


class TestBibleAndDossiers(unittest.TestCase):
    def test_files_present_with_front_matter(self):
        bible = sorted((ROOT / "bible").glob("[0-9][0-9]_*.md"))
        self.assertEqual(len(bible), 11)
        for p in bible + [d for d in sorted((ROOT / "dossiers").glob("*.md")) if d.name != "README.md"]:
            self.assertTrue(p.read_text(encoding="utf-8").startswith("---\n"), p.name)

    def test_dossier_numbers_match_sheets(self):
        expect = {"brannoc": "AC 19 · HP 13", "ilsevel": "AC 12 (15 with Mage Armor) · HP 8",
                  "tamsin": "AC 14 · HP 10", "oriel": "AC 18 · HP 10"}
        for name, text in expect.items():
            self.assertIn(text, (ROOT / "dossiers" / f"{name}.md").read_text(encoding="utf-8"))


class TestLLMBridge(unittest.TestCase):
    def setUp(self):
        import sys
        sys.path.insert(0, str(Path(ROOT / "scripts")))
        import demo_combat
        self.enc = demo_combat.build("LLM-1")
        self.enc.start()

    def test_prompt_lists_menu(self):
        prompt, menu = build_turn_prompt(self.enc, self.enc.current, "Brave and blunt.")
        self.assertIn("MENU:", prompt)
        self.assertIn("1. ", prompt)
        self.assertGreater(len(menu), 1)

    def test_parse_choice(self):
        menu = self.enc.legal_actions()
        self.assertEqual(parse_choice('{"choice": 1, "why": "x"}', menu), menu[0]["intent"])
        self.assertEqual(parse_choice('Sure! {"choice": 2}', menu), menu[1]["intent"])
        for bad in ("", "attack!", '{"choice": 0}', '{"choice": 999}', '{"pick": 1}', '{"choice": "x"}'):
            self.assertIsNone(parse_choice(bad, menu), bad)

    def test_policy_falls_back_on_garbage(self):
        policy = make_llm_policy(lambda prompt: "I refuse to answer in JSON")
        res = self.enc.run(policy)
        self.assertTrue(res["finished"])
        self.assertTrue(any(e["t"] == "policy_fallback" for e in res["events"]))

    def test_policy_with_fake_model(self):
        def model(prompt):
            # Always pick the first attack if any, else end turn (last option).
            lines = [l for l in prompt.splitlines() if l[:1].isdigit()]
            for l in lines:
                if "→" in l and "Move" not in l:
                    return json.dumps({"choice": int(l.split(".")[0]), "why": "hit it"})
            return json.dumps({"choice": len(lines), "why": "done"})

        res = self.enc.run(make_llm_policy(model))
        self.assertTrue(res["finished"] or res["rounds"] > 0)
        self.assertFalse(any(e["t"] == "illegal_intent" for e in res["events"]))


if __name__ == "__main__":
    unittest.main()
