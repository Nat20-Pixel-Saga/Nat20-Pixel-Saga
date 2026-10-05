import unittest

from helpers import ScriptedDice, dummy, mon, pc
from pqc.checks import ability_check, death_save, group_check, saving_throw
from pqc.creature import Effect
from pqc.rules import distance_ft, modifier, proficiency_bonus


class TestCoreNumbers(unittest.TestCase):
    def test_modifiers(self):
        self.assertEqual([modifier(s) for s in (1, 8, 9, 10, 11, 12, 17, 20, 30)], [-5, -1, -1, 0, 0, 1, 3, 5, 10])

    def test_proficiency(self):
        self.assertEqual([proficiency_bonus(l) for l in (1, 4, 5, 8, 9, 13, 17, 20)], [2, 2, 3, 3, 4, 5, 6, 6])
        with self.assertRaises(ValueError):
            proficiency_bonus(21)

    def test_distance_diagonals_cost_five(self):
        self.assertEqual(distance_ft((0, 0), (3, 4)), 20)
        self.assertEqual(distance_ft((2, 2), (2, 2)), 0)


class TestPartySheets(unittest.TestCase):
    """The engine must derive exactly the numbers printed in the dossiers."""

    def test_brannoc(self):
        b = pc("brannoc")
        self.assertEqual((b.ac, b.hp, b.initiative_bonus), (19, 13, 1))
        self.assertEqual((b.attack_by_id("longsword").to_hit, b.attack_by_id("longsword").damage), (5, "1d8+3"))
        self.assertIn("poison", b.resistances)

    def test_ilsevel(self):
        i = pc("ilsevel")
        self.assertEqual((i.ac, i.hp, i.spell_attack_bonus, i.spell_save_dc), (12, 8, 5, 13))
        i.add_effect(Effect("mage_armor", "ilsevel", {"base_ac": 13}))
        self.assertEqual(i.ac, 15)

    def test_tamsin(self):
        t = pc("tamsin")
        self.assertEqual((t.ac, t.hp, t.initiative_bonus, t.sneak_attack_dice), (14, 10, 5, 1))
        self.assertEqual(t.skill_bonus("stealth"), 7)  # Dex 3 + expertise 4
        self.assertEqual(t.size, "small")

    def test_oriel(self):
        o = pc("oriel")
        self.assertEqual((o.ac, o.hp, o.spell_save_dc), (18, 10, 13))
        self.assertTrue(o.heroic_inspiration)


class TestDamage(unittest.TestCase):
    def test_resistance_vulnerability_immunity(self):
        b = pc("brannoc")
        self.assertEqual(b.take_damage(9, "poison")["amount"], 4)
        s = mon("skeleton")
        self.assertEqual(s.take_damage(5, "bludgeoning")["amount"], 10)
        s2 = mon("skeleton", "s2")
        self.assertEqual(s2.take_damage(5, "poison")["amount"], 0)

    def test_temp_hp_absorbs_first(self):
        o = pc("oriel")
        o.gain_temp_hp(5)
        o.gain_temp_hp(3)  # doesn't stack
        r = o.take_damage(7, "slashing")
        self.assertEqual((r["temp_absorbed"], o.temp_hp, o.hp), (5, 0, 8))

    def test_pc_drops_unconscious_and_prone(self):
        i = pc("ilsevel")
        r = i.take_damage(10, "fire")
        self.assertTrue(r["dropped_to_zero"])
        self.assertFalse(i.dead)
        self.assertTrue(i.has_condition("unconscious") and i.has_condition("prone"))

    def test_massive_damage_kills(self):
        i = pc("ilsevel")  # 8 HP: 8 damage beyond 0 kills outright
        self.assertTrue(i.take_damage(16, "fire")["instant_death"])
        self.assertTrue(i.dead)

    def test_damage_at_zero_causes_failures(self):
        i = pc("ilsevel")
        i.take_damage(8, "fire")
        self.assertEqual(i.take_damage(1, "fire")["death_save_failures"], 1)
        self.assertEqual(i.take_damage(1, "fire", critical=True)["death_save_failures"], 2)
        self.assertTrue(i.dead)

    def test_monster_dies_at_zero(self):
        g = mon("goblin_warrior")
        self.assertTrue(g.take_damage(10, "slashing")["died"])

    def test_heal_revives(self):
        t = pc("tamsin")
        t.take_damage(10, "piercing")
        r = t.heal(4)
        self.assertTrue(r["revived"])
        self.assertEqual(t.hp, 4)
        self.assertFalse(t.has_condition("unconscious"))
        self.assertTrue(t.has_condition("prone"))  # still on the ground

    def test_heal_capped_and_no_effect_on_dead(self):
        b = pc("brannoc")
        b.take_damage(3, "slashing")
        self.assertEqual(b.heal(100)["amount"], 3)
        b.dead = True
        self.assertEqual(b.heal(5)["amount"], 0)


class TestChecks(unittest.TestCase):
    def test_skill_check_with_expertise(self):
        r = ability_check(pc("tamsin"), ScriptedDice([10]), skill="sleight_of_hand", dc=17)
        self.assertEqual(r.total, 17)
        self.assertTrue(r.success)

    def test_heavy_armour_stealth_disadvantage(self):
        r = ability_check(pc("brannoc"), ScriptedDice([18, 3]), skill="stealth", dc=10)
        self.assertEqual((r.advantage, r.natural), ("disadvantage", 3))

    def test_poisoned_disadvantage_on_checks(self):
        o = pc("oriel")
        o.add_condition("poisoned")
        self.assertEqual(ability_check(o, ScriptedDice([18, 3]), skill="insight").advantage, "disadvantage")

    def test_guidance_adds_d4(self):
        b = pc("brannoc")
        b.add_effect(Effect("guidance", "oriel", {"check_bonus": "1d4"}))
        r = ability_check(b, ScriptedDice([10, 3]), skill="athletics", dc=18)
        self.assertEqual(r.total, 10 + 5 + 3)
        self.assertTrue(r.success)

    def test_exhaustion_penalty(self):
        b = pc("brannoc")
        b.exhaustion = 2
        self.assertEqual(ability_check(b, ScriptedDice([10]), skill="athletics").total, 10 + 5 - 4)

    def test_paralysed_auto_fails_dex_save(self):
        t = pc("tamsin")
        t.add_condition("paralyzed")
        r = saving_throw(t, ScriptedDice([20]), "dex", 5)
        self.assertFalse(r.success)

    def test_dwarven_resilience(self):
        r = saving_throw(pc("brannoc"), ScriptedDice([4, 15]), "con", 12, against={"poisoned"})
        self.assertEqual((r.advantage, r.natural, r.success), ("advantage", 15, True))

    def test_halfling_brave_and_luck(self):
        r = saving_throw(pc("tamsin"), ScriptedDice([1, 6, 12]), "wis", 12, against={"frightened"})
        # Advantage from Brave; the 1 is rerolled by Luck (-> 12), keep 12.
        self.assertEqual((r.natural, r.success), (12, True))

    def test_bless_on_saves(self):
        b = pc("brannoc")
        b.add_effect(Effect("bless", "oriel", {"save_bonus": "1d4"}))
        r = saving_throw(b, ScriptedDice([8, 4]), "wis", 13)
        self.assertEqual(r.total, 8 + 1 + 4)
        self.assertTrue(r.success)

    def test_group_check_half_succeed(self):
        p = [pc("brannoc"), pc("ilsevel"), pc("tamsin"), pc("oriel")]
        # Brannoc rolls 2 dice (disadvantage in chain mail), Oriel too.
        res = group_check(p, "stealth", 12, ScriptedDice([2, 2, 15, 9, 5, 5]))
        self.assertEqual(res["passed"], 2)
        self.assertTrue(res["success"])


class TestDeathSaves(unittest.TestCase):
    def down(self):
        i = pc("ilsevel")
        i.take_damage(8, "fire")
        return i

    def test_three_successes_stabilise(self):
        i = self.down()
        d = ScriptedDice([10, 15, 19])
        for _ in range(3):
            death_save(i, d)
        self.assertTrue(i.stable)
        self.assertFalse(i.dead)

    def test_three_failures_kill(self):
        i = self.down()
        d = ScriptedDice([9, 2, 5])
        outcomes = [death_save(i, d)[1]["result"] for _ in range(3)]
        self.assertEqual(outcomes[-1], "died")
        self.assertTrue(i.dead)

    def test_natural_one_counts_twice(self):
        i = self.down()
        death_save(i, ScriptedDice([1]))
        self.assertEqual(i.death_saves["failures"], 2)

    def test_natural_twenty_revives(self):
        i = self.down()
        _, out = death_save(i, ScriptedDice([20]))
        self.assertEqual((out["result"], i.hp), ("revived", 1))

    def test_dummy_helper(self):
        self.assertEqual(dummy(ac=13).ac, 13)


if __name__ == "__main__":
    unittest.main()
