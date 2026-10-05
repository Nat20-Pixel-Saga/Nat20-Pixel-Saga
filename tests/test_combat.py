import copy
import json
import unittest

from helpers import ScriptedDice, dummy, mon, pc, scene
from pqc.ai import simple_policy
from pqc.combat import EngineError, Encounter
from pqc.creature import Attack
from pqc.dice import Dice


def last(enc, t):
    return next(e for e in reversed(enc.events) if e["t"] == t)


class TestWeaponAttacks(unittest.TestCase):
    def test_hit_with_savage_attacker_keeps_higher(self):
        b, d = pc("brannoc"), dummy(ac=10, pos=(1, 0))
        b.pos = (0, 0)
        enc = scene([b, d], [15, 4, 6])
        enc.act({"type": "attack", "attack": "longsword", "target": "dummy"})
        ev = last(enc, "attack")
        self.assertTrue(ev["hit"])
        self.assertEqual(ev["damage"]["total"], 9)  # 6 + 3, the 4 was discarded
        self.assertEqual(d.hp, 41)

    def test_critical_doubles_dice_not_modifier(self):
        b, d = pc("brannoc"), dummy(ac=30, pos=(1, 0))
        b.pos = (0, 0)
        enc = scene([b, d], [20, 3, 5, 1, 1])
        enc.act({"type": "attack", "attack": "longsword", "target": "dummy"})
        ev = last(enc, "attack")
        self.assertTrue(ev["critical"])
        self.assertEqual(ev["damage"]["total"], 3 + 5 + 3)

    def test_natural_one_always_misses(self):
        b, d = pc("brannoc"), dummy(ac=1, pos=(1, 0))
        b.pos = (0, 0)
        enc = scene([b, d], [1])
        enc.act({"type": "attack", "attack": "longsword", "target": "dummy"})
        self.assertFalse(last(enc, "attack")["hit"])

    def test_out_of_reach_is_rejected_without_rolling(self):
        b, d = pc("brannoc"), dummy(pos=(3, 0))
        b.pos = (0, 0)
        enc = scene([b, d], [])
        n = len(enc.dice.log)
        with self.assertRaises(EngineError):
            enc.act({"type": "attack", "attack": "longsword", "target": "dummy"})
        self.assertEqual(len(enc.dice.log), n)
        self.assertEqual(enc.turn.actions, 1)

    def test_out_of_range_is_rejected(self):
        t, d = pc("tamsin"), dummy(pos=(70, 0))
        t.pos = (0, 0)
        enc = scene([t, d], [])
        with self.assertRaises(EngineError):
            enc.act({"type": "attack", "attack": "shortbow", "target": "dummy"})

    def test_ammunition_is_spent(self):
        t, d = pc("tamsin"), dummy(pos=(4, 0))
        t.pos = (0, 0)
        enc = scene([t, d], [2])
        enc.act({"type": "attack", "attack": "shortbow", "target": "dummy"})
        self.assertEqual(t.inventory["arrows"], 19)

    def test_one_attack_per_action_at_level_one(self):
        b, d = pc("brannoc"), dummy(pos=(1, 0))
        b.pos = (0, 0)
        enc = scene([b, d], [2])
        enc.act({"type": "attack", "attack": "longsword", "target": "dummy"})
        with self.assertRaises(EngineError):
            enc.act({"type": "attack", "attack": "longsword", "target": "dummy"})


class TestAdvantageSources(unittest.TestCase):
    def test_ranged_attack_with_hostile_adjacent_has_disadvantage(self):
        t, d = pc("tamsin"), dummy(pos=(1, 0))
        t.pos = (0, 0)
        enc = scene([t, d], [18, 3])
        enc.act({"type": "attack", "attack": "shortbow", "target": "dummy"})
        self.assertEqual(last(enc, "attack")["advantage"], "disadvantage")

    def test_long_range_disadvantage(self):
        t, d = pc("tamsin"), dummy(pos=(20, 0))
        t.pos = (0, 0)
        enc = scene([t, d], [18, 3])
        enc.act({"type": "attack", "attack": "shortbow", "target": "dummy"})
        self.assertEqual(last(enc, "attack")["advantage"], "disadvantage")

    def test_prone_target(self):
        b, d = pc("brannoc"), dummy(pos=(1, 0))
        b.pos = (0, 0)
        d.add_condition("prone")
        enc = scene([b, d], [3, 15, 2, 2])
        enc.act({"type": "attack", "attack": "longsword", "target": "dummy"})
        self.assertEqual(last(enc, "attack")["advantage"], "advantage")
        t, d2 = pc("tamsin"), dummy("d2", pos=(4, 0))
        t.pos = (0, 0)
        d2.add_condition("prone")
        enc2 = scene([t, d2], [15, 2])
        enc2.act({"type": "attack", "attack": "shortbow", "target": "d2"})
        self.assertEqual(last(enc2, "attack")["advantage"], "disadvantage")

    def test_unconscious_target_auto_crit_in_melee(self):
        b, d = pc("brannoc"), dummy(pos=(1, 0), ac=10)
        b.pos = (0, 0)
        d.add_condition("unconscious")
        enc = scene([b, d], [2, 12, 1, 1, 1, 1])
        enc.act({"type": "attack", "attack": "longsword", "target": "dummy"})
        ev = last(enc, "attack")
        self.assertTrue(ev["hit"] and ev["critical"])

    def test_pack_tactics_and_wolf_knockdown(self):
        o = pc("oriel")
        o.pos = (0, 0)
        w1, w2 = mon("wolf", "wolf-1", pos=(1, 0)), mon("wolf", "wolf-2", pos=(0, 1))
        enc = scene([w1, o, w2], [3, 17, 4])
        enc.act({"type": "attack", "attack": "bite", "target": "oriel"})
        ev = last(enc, "attack")
        self.assertEqual(ev["advantage"], "advantage")
        self.assertTrue(o.has_condition("prone"))
        self.assertEqual(o.hp, 10 - 6)


class TestSneakAttackAndMasteries(unittest.TestCase):
    def test_sneak_attack_with_ally_adjacent(self):
        t, b, d = pc("tamsin"), pc("brannoc"), dummy(pos=(1, 0))
        t.pos, b.pos = (0, 0), (2, 0)
        enc = scene([t, b, d], [12, 4, 5])
        enc.act({"type": "attack", "attack": "shortsword", "target": "dummy"})
        ev = last(enc, "attack")
        self.assertTrue(ev.get("sneak_attack"))
        self.assertEqual(ev["damage"]["total"], 4 + 3 + 5)

    def test_no_sneak_attack_alone_without_advantage(self):
        t, d = pc("tamsin"), dummy(pos=(1, 0))
        t.pos = (0, 0)
        enc = scene([t, d], [12, 4])
        enc.act({"type": "attack", "attack": "shortsword", "target": "dummy"})
        self.assertFalse(last(enc, "attack").get("sneak_attack", False))

    def test_vex_grants_advantage_on_next_attack(self):
        t, d = pc("tamsin"), dummy(pos=(1, 0))
        t.pos = (0, 0)
        # Turn 1: hit (vex). Dummy's turn passes. Turn 2: advantage (3,18 -> 18) + Sneak Attack from advantage.
        enc = scene([t, d], [12, 2, 3, 18, 1, 1])
        enc.act({"type": "attack", "attack": "shortsword", "target": "dummy"})
        self.assertIsNotNone(t.effect("vex"))
        enc.end_turn()
        enc.end_turn()
        enc.act({"type": "attack", "attack": "shortsword", "target": "dummy"})
        ev = last(enc, "attack")
        self.assertEqual(ev["advantage"], "advantage")
        self.assertTrue(ev.get("sneak_attack"))
        # The old Vex was spent; the new hit applies a fresh one.
        self.assertEqual(t.effect("vex").expires, ("end", "tamsin", 1))

    def test_sap_gives_target_disadvantage(self):
        b, d = pc("brannoc"), dummy(pos=(1, 0))
        b.pos = (0, 0)
        enc = scene([b, d], [15, 2, 2, 15, 3])
        enc.act({"type": "attack", "attack": "longsword", "target": "dummy"})
        self.assertIsNotNone(d.effect("sapped"))
        enc.end_turn()
        enc.act({"type": "attack", "attack": "club", "target": "brannoc"})
        self.assertEqual(last(enc, "attack")["advantage"], "disadvantage")

    def test_graze_deals_modifier_on_miss(self):
        b, d = pc("brannoc"), dummy(pos=(1, 0), ac=30)
        b.pos = (0, 0)
        b.weapon_masteries.add("greatsword")
        b.attacks.append(Attack(id="greatsword", name="Greatsword", type="melee", to_hit=5, damage="2d6+3",
                                damage_type="slashing", mastery="graze", weapon_id="greatsword", ability="str"))
        enc = scene([b, d], [5])
        enc.act({"type": "attack", "attack": "greatsword", "target": "dummy"})
        ev = last(enc, "attack")
        self.assertFalse(ev["hit"])
        self.assertEqual(ev["graze"]["total"], 3)

    def test_slow_reduces_speed(self):
        b, d = pc("brannoc"), dummy(pos=(4, 0), speed=30)
        b.pos = (0, 0)
        enc = scene([b, d], [15, 3, 3])
        enc.act({"type": "attack", "attack": "javelin:thrown", "target": "dummy"})
        self.assertEqual(d.current_speed, 20)
        self.assertEqual(b.inventory["javelin"], 3)


class TestMovementAndReactions(unittest.TestCase):
    def test_opportunity_attack_when_leaving_reach(self):
        i, g = pc("ilsevel"), mon("goblin_warrior", "g", pos=(1, 0))
        i.pos = (0, 0)
        enc = scene([i, g], [15, 3])
        enc.act({"type": "move", "to": [-3, 0]})
        oa = last(enc, "attack")
        self.assertTrue(oa["opportunity"])
        self.assertEqual(i.hp, 8 - 5)
        self.assertFalse(enc.reactions["g"])

    def test_disengage_prevents_opportunity_attack(self):
        i, g = pc("ilsevel"), mon("goblin_warrior", "g", pos=(1, 0))
        i.pos = (0, 0)
        enc = scene([i, g], [])
        enc.act({"type": "disengage"})
        enc.act({"type": "move", "to": [-3, 0]})
        self.assertFalse(any(e["t"] == "attack" for e in enc.events))

    def test_movement_budget_and_occupied_squares(self):
        b, d = pc("brannoc"), dummy(pos=(1, 0))
        b.pos = (0, 0)
        enc = scene([b, d], [])
        enc.reactions["dummy"] = False  # no opportunity attack in this test
        with self.assertRaises(EngineError):
            enc.act({"type": "move", "to": [1, 0]})
        with self.assertRaises(EngineError):
            enc.act({"type": "move", "to": [0, 7]})
        enc.act({"type": "move", "to": [0, 6]})
        self.assertEqual(enc.turn.movement, 0)
        enc.act({"type": "dash"})
        enc.act({"type": "move", "to": [0, 12]})

    def test_shield_reaction_turns_hit_into_miss(self):
        g, i = mon("goblin_warrior", "g", pos=(1, 0)), pc("ilsevel")
        i.pos = (0, 0)
        enc = scene([g, i], [10])
        enc.act({"type": "attack", "attack": "scimitar", "target": "ilsevel"})
        self.assertFalse(last(enc, "attack")["hit"])
        self.assertEqual(i.slots_available(1), 1)
        self.assertEqual(i.ac, 17)
        enc.end_turn()  # start of Ilsevel's turn: Shield ends
        self.assertEqual(i.ac, 12)

    def test_shield_not_wasted_on_hopeless_hit(self):
        g, i = mon("goblin_warrior", "g", pos=(1, 0)), pc("ilsevel")
        i.pos = (0, 0)
        enc = scene([g, i], [17, 2])
        enc.act({"type": "attack", "attack": "scimitar", "target": "ilsevel"})
        self.assertTrue(last(enc, "attack")["hit"])
        self.assertEqual(i.slots_available(1), 2)


class TestSpells(unittest.TestCase):
    def test_magic_missile_auto_hits(self):
        i, d = pc("ilsevel"), dummy(pos=(3, 0))
        i.pos = (0, 0)
        enc = scene([i, d], [1, 2, 3])
        enc.act({"type": "cast", "spell": "magic_missile", "level": 1, "targets": ["dummy"]})
        self.assertEqual(d.hp, 50 - 9)
        self.assertEqual(i.slots_available(1), 1)

    def test_fire_bolt_attack(self):
        i, d = pc("ilsevel"), dummy(pos=(10, 0), ac=12)
        i.pos = (0, 0)
        enc = scene([i, d], [10, 7])
        enc.act({"type": "cast", "spell": "fire_bolt", "targets": ["dummy"]})
        r = last(enc, "cast")["results"][0]
        self.assertTrue(r["hit"])
        self.assertEqual(r["damage"]["total"], 7)

    def test_burning_hands_save_for_half(self):
        i = pc("ilsevel")
        i.pos = (0, 0)
        g1, g2 = mon("goblin_warrior", "g1", pos=(1, 0)), mon("goblin_warrior", "g2", pos=(2, 1))
        enc = scene([i, g1, g2], [3, 3, 2, 18, 4])  # damage 3d6=8; g1 saves 20 (succeeds), g2 fails
        enc.act({"type": "cast", "spell": "burning_hands", "level": 1, "targets": ["g1", "g2"]})
        res = {r["target"]: r for r in last(enc, "cast")["results"]}
        self.assertTrue(res["g1"]["saved"])
        self.assertEqual(res["g1"]["damage"]["total"], 4)
        self.assertFalse(res["g2"]["saved"])
        self.assertEqual(g2.hp, 2)

    def test_sacred_flame_no_damage_on_save(self):
        o, g = pc("oriel"), mon("goblin_warrior", "g", pos=(4, 0))
        o.pos = (0, 0)
        enc = scene([o, g], [6, 15])
        enc.act({"type": "cast", "spell": "sacred_flame", "targets": ["g"]})
        r = last(enc, "cast")["results"][0]
        self.assertTrue(r["saved"])
        self.assertNotIn("damage", r)

    def test_healing_word_revives_downed_ally(self):
        o, b = pc("oriel"), pc("brannoc")
        o.pos, b.pos = (0, 0), (5, 0)
        b.take_damage(13, "slashing")
        enc = scene([o, b], [2, 3])
        enc.act({"type": "cast", "spell": "healing_word", "level": 1, "targets": ["brannoc"]})
        self.assertEqual(b.hp, 2 + 3 + 3)
        self.assertTrue(b.conscious)

    def test_one_slot_spell_per_turn_with_bonus_action_spell(self):
        o, b, g = pc("oriel"), pc("brannoc"), mon("goblin_warrior", "g", pos=(3, 0))
        o.pos, b.pos = (0, 0), (1, 1)
        b.take_damage(3, "slashing")
        enc = scene([o, b, g], [1, 1, 5, 15])  # healing 2d4; sacred flame damage d8 then the save
        enc.act({"type": "cast", "spell": "healing_word", "level": 1, "targets": ["brannoc"]})
        with self.assertRaises(EngineError):
            enc.act({"type": "cast", "spell": "guiding_bolt", "level": 1, "targets": ["g"]})
        enc.act({"type": "cast", "spell": "sacred_flame", "targets": ["g"]})  # a cantrip is fine

    def test_unprepared_spell_rejected(self):
        i, d = pc("ilsevel"), dummy(pos=(2, 0))
        i.pos = (0, 0)
        enc = scene([i, d], [])
        with self.assertRaises(EngineError):
            enc.act({"type": "cast", "spell": "thunderwave", "level": 1, "targets": ["dummy"]})  # in book, not prepared

    def test_concentration_lost_on_failed_save(self):
        o, b, g = pc("oriel"), pc("brannoc"), mon("goblin_warrior", "g", pos=(1, 0))
        o.pos, b.pos = (0, 0), (0, 3)
        enc = scene([o, g, b], [18, 4, 5, 1])
        enc.act({"type": "cast", "spell": "bless", "level": 1, "targets": ["oriel", "brannoc"]})
        self.assertIsNotNone(b.effect("bless"))
        enc.end_turn()
        enc.act({"type": "attack", "attack": "scimitar", "target": "oriel"})
        self.assertIsNone(o.concentration)
        self.assertIsNone(b.effect("bless"))
        self.assertEqual(last(enc, "concentration_check")["dc"], 10)

    def test_bless_adds_to_attacks(self):
        b, d = pc("brannoc"), dummy(pos=(1, 0), ac=21)
        b.pos = (0, 0)
        from pqc.creature import Effect
        b.add_effect(Effect("bless", "oriel", {"attack_bonus": "1d4", "save_bonus": "1d4"}))
        enc = scene([b, d], [13, 3, 1, 1])
        enc.act({"type": "attack", "attack": "longsword", "target": "dummy"})
        ev = last(enc, "attack")
        self.assertEqual(ev["total"], 13 + 5 + 3)
        self.assertTrue(ev["hit"])

    def test_free_cast_from_magic_initiate(self):
        o, b = pc("oriel"), pc("brannoc")
        o.pos, b.pos = (0, 0), (1, 0)
        enc = scene([o, b, dummy(pos=(9, 9))], [])
        enc.act({"type": "cast", "spell": "sanctuary", "free": True, "targets": ["brannoc"]})
        self.assertIsNotNone(b.effect("sanctuary"))
        self.assertEqual(o.slots_available(1), 2)
        self.assertEqual(o.spellcasting["free_casts"]["sanctuary"]["current"], 0)


class TestMonstersAndResources(unittest.TestCase):
    def test_multiattack(self):
        boss, d = mon("goblin_boss", "boss", pos=(1, 0)), dummy(pos=(0, 0), team="party")
        enc = scene([boss, d], [15, 3, 15, 3])
        enc.act({"type": "attack", "attack": "scimitar", "target": "dummy"})
        enc.act({"type": "attack", "attack": "scimitar", "target": "dummy"})
        with self.assertRaises(EngineError):
            enc.act({"type": "attack", "attack": "scimitar", "target": "dummy"})
        self.assertEqual(d.hp, 50 - 10)

    def test_undead_fortitude(self):
        z = mon("zombie", "z", pos=(1, 0))
        hitter = dummy("hitter", team="party", pos=(0, 0))
        hitter.attacks = [Attack(id="maul", name="Maul", type="melee", to_hit=2, damage="16", damage_type="bludgeoning")]
        enc = scene([hitter, z], [15, 18])
        enc.act({"type": "attack", "attack": "maul", "target": "z"})
        self.assertEqual(z.hp, 1)
        self.assertFalse(z.dead)

    def test_radiant_bypasses_undead_fortitude(self):
        z = mon("zombie", "z", pos=(1, 0))
        hitter = dummy("hitter", team="party", pos=(0, 0))
        hitter.attacks = [Attack(id="smite", name="Smite", type="melee", to_hit=2, damage="16", damage_type="radiant")]
        enc = scene([hitter, z], [15])
        enc.act({"type": "attack", "attack": "smite", "target": "z"})
        self.assertTrue(z.dead)

    def test_second_wind_and_potion(self):
        b, d = pc("brannoc"), dummy(pos=(9, 9))
        b.take_damage(10, "slashing")
        enc = scene([b, d], [5, 3, 2])
        enc.act({"type": "second_wind"})
        self.assertEqual(b.hp, 3 + 6)
        self.assertEqual(b.resources["second_wind"]["current"], 1)
        with self.assertRaises(EngineError):  # bonus action already used
            enc.act({"type": "use_item", "item": "potion_of_healing"})

    def test_death_save_at_start_of_turn(self):
        d, t, b = dummy(pos=(9, 9)), pc("tamsin"), pc("brannoc")
        b.pos = (20, 20)
        t.take_damage(10, "piercing")
        enc = scene([d, t, b], [12])
        enc.end_turn()
        self.assertEqual(last(enc, "death_save")["result"], "success")
        self.assertEqual(t.death_saves["successes"], 1)
        self.assertEqual(enc.legal_actions()[0]["intent"]["type"], "end_turn")

    def test_encounter_ends_with_xp(self):
        b, g = pc("brannoc"), mon("goblin_warrior", "g", pos=(1, 0))
        b.pos = (0, 0)
        enc = scene([b, g], [18, 8, 8])
        enc.act({"type": "attack", "attack": "longsword", "target": "g"})
        self.assertTrue(enc.finished)
        end = last(enc, "encounter_end")
        self.assertEqual((end["winner"], end["xp"]), ("party", 50))
        with self.assertRaises(EngineError):
            enc.act({"type": "end_turn"})


class TestFullEncounters(unittest.TestCase):
    def build(self, seed):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import demo_combat
        return demo_combat.build(seed)

    def test_deterministic_replay(self):
        a = self.build("C01-E001-1").run(simple_policy)
        b = self.build("C01-E001-1").run(simple_policy)
        self.assertEqual(json.dumps(a["events"]), json.dumps(b["events"]))
        self.assertTrue(a["finished"])
        self.assertTrue(Dice.verify_log("C01-E001-1", a["rolls"]))

    def test_different_seeds_differ(self):
        a = self.build("C01-E001-1").run(simple_policy)
        b = self.build("C01-E001-2").run(simple_policy)
        self.assertNotEqual(json.dumps(a["events"]), json.dumps(b["events"]))

    def test_every_menu_option_is_legal(self):
        """Fuzz: at every decision point, every option in legal_actions() executes."""
        checked = 0
        for seed in ("FUZZ-1", "FUZZ-2", "FUZZ-3"):
            enc = self.build(seed)

            def policy(e: Encounter, c):
                nonlocal checked
                for opt in e.legal_actions():
                    clone = copy.deepcopy(e)
                    clone.act(opt["intent"])  # must not raise
                    checked += 1
                return simple_policy(e, c)

            res = enc.run(policy)
            self.assertTrue(res["finished"])
            self.assertFalse(any(ev["t"] == "illegal_intent" for ev in res["events"]))
        self.assertGreater(checked, 100)

    def test_many_seeds_always_terminate(self):
        outcomes = {}
        for n in range(1, 41):
            res = self.build(f"C01-E001-{n}").run(simple_policy)
            self.assertTrue(res["finished"], f"seed {n} did not finish")
            outcomes[res["winner"]] = outcomes.get(res["winner"], 0) + 1
        self.assertIn("party", outcomes)


if __name__ == "__main__":
    unittest.main()
