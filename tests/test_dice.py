import unittest
from collections import Counter

from helpers import ScriptedDice  # noqa: F401  (sets sys.path)
from pqc.dice import Dice, DiceError, DiceSpec


class TestNotation(unittest.TestCase):
    def test_parse_forms(self):
        self.assertEqual(DiceSpec.parse("d20"), DiceSpec(1, 20))
        self.assertEqual(DiceSpec.parse("2d6+3"), DiceSpec(2, 6, None, None, 3))
        self.assertEqual(DiceSpec.parse("1d8 - 1"), DiceSpec(1, 8, None, None, -1))
        self.assertEqual(DiceSpec.parse("4d6kh3"), DiceSpec(4, 6, "kh", 3, 0))
        self.assertEqual(DiceSpec.parse("7"), DiceSpec(0, 0, None, None, 7))
        self.assertEqual(str(DiceSpec.parse("8d6")), "8d6")

    def test_bad_notation(self):
        for bad in ("d7", "2x6", "", "0d6", "3d6kh4", "201d6"):
            with self.assertRaises(DiceError, msg=bad):
                DiceSpec.parse(bad)

    def test_scaling(self):
        self.assertEqual(str(DiceSpec.parse("1d8+3").scaled(2)), "2d8+3")
        self.assertEqual(str(DiceSpec.parse("3d6").plus_dice(2)), "5d6")
        self.assertEqual(DiceSpec.parse("2d6+1").average, 8.0)


class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_rolls(self):
        a, b = Dice("C01-E001-1"), Dice("C01-E001-1")
        self.assertEqual([a.roll("1d20").total for _ in range(50)], [b.roll("1d20").total for _ in range(50)])

    def test_different_seed_different_rolls(self):
        a, b = Dice("C01-E001-1"), Dice("C01-E001-2")
        self.assertNotEqual([a.roll("1d20").total for _ in range(30)], [b.roll("1d20").total for _ in range(30)])

    def test_empty_seed_rejected(self):
        with self.assertRaises(DiceError):
            Dice("")

    def test_uniform_enough(self):
        d = Dice("uniformity")
        counts = Counter(d.roll("1d20").total for _ in range(20000))
        self.assertEqual(set(counts), set(range(1, 21)))
        expected = 1000
        chi2 = sum((c - expected) ** 2 / expected for c in counts.values())
        self.assertLess(chi2, 43.8, "chi-square for 19 dof at p=0.001")

    def test_ranges(self):
        d = Dice("ranges")
        for sides in (4, 6, 8, 10, 12, 100):
            vals = {d.roll(f"1d{sides}").total for _ in range(2000)}
            self.assertEqual(min(vals), 1)
            self.assertEqual(max(vals), sides)


class TestVerification(unittest.TestCase):
    def test_log_verifies(self):
        d = Dice("C01-E002-1")
        d.d20(modifier=3, advantage=True)
        d.roll("8d6")
        d.roll("4d6kh3")
        self.assertTrue(Dice.verify_log("C01-E002-1", d.export_log()))

    def test_tampering_detected(self):
        d = Dice("C01-E002-1")
        d.d20()
        log = d.export_log()
        log[0]["draws"][0]["value"] = (log[0]["draws"][0]["value"] % 20) + 1
        self.assertFalse(Dice.verify_log("C01-E002-1", log))

    def test_wrong_seed_detected(self):
        d = Dice("A")
        d.d20()
        self.assertFalse(Dice.verify_log("B", d.export_log()))

    def test_reordering_detected(self):
        d = Dice("C")
        d.d20()
        d.d20()
        log = d.export_log()
        self.assertFalse(Dice.verify_log("C", list(reversed(log))))


class TestD20(unittest.TestCase):
    def test_advantage_keeps_higher(self):
        r = ScriptedDice([5, 17]).d20(modifier=2, advantage=True)
        self.assertEqual((r.natural, r.total, r.advantage), (17, 19, "advantage"))

    def test_disadvantage_keeps_lower(self):
        r = ScriptedDice([5, 17]).d20(disadvantage=True)
        self.assertEqual(r.natural, 5)

    def test_advantage_and_disadvantage_cancel(self):
        r = ScriptedDice([12]).d20(advantage=True, disadvantage=True)
        self.assertEqual((r.natural, r.advantage, len(r.draws)), (12, "none", 1))

    def test_halfling_luck_rerolls_a_one(self):
        r = ScriptedDice([1, 14]).d20(reroll_ones=True)
        self.assertEqual((r.natural, r.rerolled), (14, [1]))

    def test_luck_rerolls_only_one_die_with_advantage(self):
        r = ScriptedDice([1, 1, 3]).d20(advantage=True, reroll_ones=True)
        self.assertEqual(r.natural, 3)
        self.assertEqual(r.rerolled, [1])

    def test_attack_crit_and_fumble(self):
        crit = ScriptedDice([20]).d20(modifier=-5, dc=30, is_attack=True)
        self.assertTrue(crit.critical and crit.success)
        fumble = ScriptedDice([1]).d20(modifier=50, dc=5, is_attack=True)
        self.assertTrue(fumble.fumble)
        self.assertFalse(fumble.success)
        champion = ScriptedDice([19]).d20(dc=99, is_attack=True, crit_range=19)
        self.assertTrue(champion.critical and champion.success)

    def test_checks_have_no_natural_20_magic(self):
        r = ScriptedDice([20]).d20(modifier=0, dc=25)
        self.assertFalse(r.success)
        self.assertFalse(r.critical)

    def test_overlay_text(self):
        r = ScriptedDice([14]).d20(modifier=5, dc=16, is_attack=True)
        self.assertEqual(r.overlay_text(), "d20 (14) + 5 = 19 vs 16 — SUCCESS")
        r = ScriptedDice([4, 7]).d20(modifier=4, dc=12, disadvantage=True, is_attack=True)
        self.assertIn("DIS (4|7 → 4)", r.overlay_text())

    def test_keep_highest(self):
        r = ScriptedDice([2, 6, 5, 1]).roll("4d6kh3")
        self.assertEqual((r.kept, r.total), ([6, 5, 2], 13))


if __name__ == "__main__":
    unittest.main()
