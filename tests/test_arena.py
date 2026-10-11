"""The Pit: monster rules added for the arena (Parry, Bloodied, charges, Rampage, grapples) and the
arena formats (deterministic bouts, odds maths, the season spec)."""
import json
import unittest
from pathlib import Path

from pqc import data
from pqc.arena import formats
from pqc.combat import Encounter
from pqc.dice import Dice
from pqc.state import monster_from_data

ROOT = Path(__file__).resolve().parent.parent


def enc_of(*specs, seed="t"):
    cs = [monster_from_data(m, cid, team=team, pos=pos) for m, cid, team, pos in specs]
    e = Encounter(cs, Dice(seed))
    e.start(order=[c.id for c in cs])
    return e


class MonsterRules(unittest.TestCase):
    def test_parry_turns_a_hit_into_a_miss(self):
        seen = 0
        for k in range(40):
            e = enc_of(("polar_bear", "p", "a", (0, 0)), ("knight", "k", "b", (1, 0)), seed=f"parry-{k}")
            bear, knight = e.get("p"), e.get("k")
            for _ in range(2):
                ev = e.resolve_weapon_attack(bear, knight, bear.attack_by_id("rend"))
                if ev.get("parried"):
                    seen += 1
                    self.assertFalse(ev["hit"])
                    self.assertEqual(ev["ac"], 20)
                    self.assertTrue(18 <= ev["total"] < 20)
                    self.assertFalse(e.reactions["k"])
        self.assertGreater(seen, 0)

    def test_bloodied_fury_gives_advantage(self):
        e = enc_of(("berserker", "b", "a", (0, 0)), ("knight", "k", "b", (1, 0)))
        b, k = e.get("b"), e.get("k")
        adv, _, _ = e._attack_modifiers(b, k, False, False)
        self.assertFalse(adv)
        b.hp = b.max_hp // 2
        adv, _, why = e._attack_modifiers(b, k, False, False)
        self.assertTrue(adv)
        self.assertIn("+bloodied", why)
        g = enc_of(("giant_boar", "g", "a", (0, 0)), ("knight", "k", "b", (1, 0)))
        g.get("g").hp = 10
        self.assertFalse(g._attack_modifiers(g.get("g"), g.get("k"), True, False)[0])   # melee only
        self.assertTrue(g._attack_modifiers(g.get("g"), g.get("k"), False, False)[0])

    def test_charge_needs_twenty_feet_straight_in(self):
        hits = 0
        for k in range(30):
            e = enc_of(("giant_boar", "g", "a", (0, 0)), ("polar_bear", "t", "b", (6, 0)), seed=f"ch-{k}")
            e.act({"type": "move", "to": [5, 0]})
            ev = e.resolve_weapon_attack(e.get("g"), e.get("t"), e.get("g").attack_by_id("gore"))
            if ev["hit"]:
                hits += 1
                self.assertTrue(ev.get("charge"))
                if e.get("t").standing:
                    self.assertTrue(e.get("t").has_condition("prone"))
        self.assertGreater(hits, 0)
        e = enc_of(("giant_boar", "g", "a", (4, 0)), ("polar_bear", "t", "b", (6, 0)))
        e.get("t").hp = e.get("t").max_hp = 999
        e.act({"type": "move", "to": [5, 0]})                     # only 5 ft
        for _ in range(20):
            ev = e.resolve_weapon_attack(e.get("g"), e.get("t"), e.get("g").attack_by_id("gore"))
            self.assertFalse(ev.get("charge"))

    def test_rampage_bites_again_at_a_bloodied_target(self):
        found = False
        for k in range(40):
            e = enc_of(("giant_hyena", "h", "a", (0, 0)), ("polar_bear", "t", "b", (1, 0)), seed=f"rp-{k}")
            t = e.get("t")
            t.hp = 20                                            # already Bloodied (max 42)
            n0 = len(e.events)
            e.resolve_weapon_attack(e.get("h"), t, e.get("h").attack_by_id("bite"))
            new = e.events[n0:]
            if any(x["t"] == "trait" and x.get("trait") == "rampage" for x in new):
                found = True
                self.assertEqual(sum(1 for x in new if x["t"] == "attack"), 2)
                self.assertFalse(e.turn.bonus_action)
        self.assertTrue(found)

    def test_grapple_restrains_and_ends_with_the_grappler(self):
        for k in range(60):
            e = enc_of(("tyrannosaurus_rex", "r", "a", (0, 0)), ("polar_bear", "p", "b", (1, 0)), seed=f"gr-{k}")
            p, r = e.get("p"), e.get("r")
            p.hp = p.max_hp = 200                                # survives the bite
            ev = e.resolve_weapon_attack(r, p, r.attack_by_id("bite"))
            if ev["hit"]:
                self.assertTrue(p.has_condition("grappled"))
                self.assertTrue(p.has_condition("restrained"))
                self.assertEqual(p.conditions["grappled"]["escape_dc"], 17)
                r.hp = 1
                e.apply_damage(r, {"slashing": 50})
                self.assertFalse(p.has_condition("grappled"))
                self.assertFalse(p.has_condition("restrained"))
                return
        self.fail("no bite hit in 60 tries")


class Formats(unittest.TestCase):
    def fs(self):
        return [{"id": "a1", "monster": "lion", "name": "Lion", "team": "a", "pos": (6, 7)},
                {"id": "b1", "monster": "brown_bear", "name": "Brown Bear", "team": "b", "pos": (14, 8)}]

    def test_bouts_are_deterministic_and_replay(self):
        r1 = formats.run_bout(self.fs(), "pit-test", samples=4)
        r2 = formats.run_bout(self.fs(), "pit-test", samples=4)
        self.assertEqual(r1["winner"], r2["winner"])
        self.assertEqual(r1["odds"], r2["odds"])
        self.assertTrue(Dice.verify_log("pit-test", r1["rolls"]))
        last = r1["odds"][max(r1["odds"])]
        self.assertEqual(last[r1["winner"]], 1.0)

    def test_no_illegal_intents_with_multiattack_and_reach(self):
        fs = [{"id": "r", "monster": "tyrannosaurus_rex", "name": "T", "team": "a", "pos": (6, 7)}] + [
            {"id": f"g{i}", "monster": "goblin_warrior", "name": "G", "team": "b", "pos": (13 + i % 3, 6 + i // 3)}
            for i in range(8)]
        for k in range(3):
            e = formats.make_encounter(fs, f"rex-{k}")
            formats.advance(e)
            self.assertFalse([x for x in e.events if x["t"] == "illegal_intent"])

    def test_match_and_bracket_maths(self):
        self.assertAlmostEqual(formats.match_chance(0.5, 0.5, (0, 0), 3), 0.5)
        self.assertEqual(formats.match_chance(1.0, 0.3, (2, 0), 3), 1.0)
        p = {(x, y): 0.5 for x in "abcd" for y in "abcd" if x != y}
        out = formats.tournament_odds(list("abcd"), p, [3, 4])
        self.assertAlmostEqual(sum(out.values()), 1.0)
        for v in out.values():
            self.assertAlmostEqual(v, 0.25)


class SeasonSpec(unittest.TestCase):
    def test_every_episode_has_a_unique_seed_and_known_fighters(self):
        s = json.loads((ROOT / "production" / "arena" / "s1.json").read_text())
        seeds = [e["seed"] for e in s["episodes"]]
        self.assertEqual(len(seeds), len(set(seeds)))
        mons = data.monsters()
        for e in s["episodes"]:
            for k in ("a", "b", "star", "minion"):
                if k in e:
                    self.assertIn(e[k], mons)
            for m in e.get("fighters", []):
                self.assertIn(m, mons)

    def test_arena_stat_blocks_are_verified(self):
        mons = data.monsters()
        for mid in ("lion", "brown_bear", "polar_bear", "giant_spider", "ghoul", "knight", "giant_hyena",
                    "allosaurus", "bandit_captain", "tyrannosaurus_rex", "dire_wolf"):
            self.assertTrue(mons[mid]["verified"], mid)


if __name__ == "__main__":
    unittest.main()
