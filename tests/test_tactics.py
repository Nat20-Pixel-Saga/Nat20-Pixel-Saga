"""Movement, areas, flanking and role-based tactics."""
import unittest

from helpers import ScriptedDice, dummy, mon, pc, scene
from pqc import grid
from pqc.ai import role_of, simple_policy
from pqc.combat import EngineError, Encounter
from pqc.dice import Dice


def last(enc, t):
    return next(e for e in reversed(enc.events) if e["t"] == t)


class TestGrid(unittest.TestCase):
    def test_cone_and_cube_sizes(self):
        self.assertEqual(len(grid.cone_squares((0, 0), (3, 0), 15)), 7)
        self.assertEqual(len(grid.cube_squares((0, 0), (3, 0), 15)), 9)
        self.assertEqual(len(grid.cube_squares((0, 0), (3, 3), 15)), 9)
        self.assertNotIn((0, 0), grid.cone_squares((0, 0), (0, 3), 15))

    def test_sphere(self):
        self.assertIn((4, 0), grid.sphere_squares((0, 0), 20))
        self.assertNotIn((4, 4), grid.sphere_squares((0, 0), 20))

    def test_dijkstra_around_wall(self):
        wall = {(1, -1), (1, 0), (1, 1)}
        tree = grid.reachable((0, 0), 30, lambda s: s not in wall)
        path = grid.path_to(tree, (2, 0))
        self.assertEqual(path[0], (0, 0))
        self.assertEqual(path[-1], (2, 0))
        self.assertTrue(all(p not in wall for p in path))
        self.assertEqual(tree[(2, 0)][0], 20)  # around the wall: 4 steps


class TestMovement(unittest.TestCase):
    def test_moves_around_obstacles(self):
        b, d = pc("brannoc"), dummy(pos=(9, 9))
        b.pos = (0, 0)
        enc = Encounter([b, d], ScriptedDice([]), occupied_extra={(1, -1), (1, 0), (1, 1)})
        enc.start(order=["brannoc", "dummy"])
        enc.act({"type": "move", "to": [2, 0]})
        ev = last(enc, "move")
        self.assertEqual(ev["cost"], 20)
        self.assertEqual(len(ev["path"]), 5)

    def test_cannot_pass_through_enemies_but_can_pass_allies(self):
        b, o = pc("brannoc"), pc("oriel")
        g1, g2, g3 = mon("goblin_warrior", "g1", pos=(1, -1)), mon("goblin_warrior", "g2", pos=(1, 0)), \
            mon("goblin_warrior", "g3", pos=(1, 1))
        b.pos, o.pos = (0, 0), (5, 5)
        enc = Encounter([b, o, g1, g2, g3], ScriptedDice([2, 2, 2, 2]))
        enc.start(order=["brannoc", "oriel", "g1", "g2", "g3"])
        for g in ("g1", "g2", "g3"):
            enc.reactions[g] = False
        tree = enc.reach_map(b)
        self.assertNotIn((1, 0), tree)
        o.pos = (1, 2)
        self.assertTrue(enc.passable(b, (1, 2)))   # through an ally...
        self.assertFalse(enc.endable(b, (1, 2)))   # ...but not stopping there

    def test_opportunity_attack_mid_path(self):
        """Walking past a goblin: the attack triggers on the step that leaves its reach."""
        i, g = pc("ilsevel"), mon("goblin_warrior", "g", pos=(2, 1))
        i.pos = (0, 0)
        enc = Encounter([i, g], ScriptedDice([3]))
        enc.start(order=["ilsevel", "g"])
        enc.act({"type": "move", "to": [5, 0], "path": [[1, 0], [2, 0], [3, 0], [4, 0], [5, 0]]})
        oa = last(enc, "attack")
        self.assertTrue(oa["opportunity"])
        # The goblin's reach ends when Ilsevel steps from (3,0) to (4,0).
        self.assertEqual(i.pos, (5, 0))

    def test_path_validation(self):
        b, d = pc("brannoc"), dummy(pos=(9, 9))
        b.pos = (0, 0)
        enc = scene([b, d], [])
        with self.assertRaises(EngineError):
            enc.act({"type": "move", "to": [2, 0], "path": [[2, 0]]})  # not adjacent steps


class TestAreas(unittest.TestCase):
    def test_burning_hands_hits_whoever_is_in_the_cone_including_allies(self):
        i, b = pc("ilsevel"), pc("brannoc")
        g1, g2 = mon("goblin_warrior", "g1", pos=(2, 0)), mon("goblin_warrior", "g2", pos=(3, 1))
        i.pos, b.pos = (0, 0), (2, -1)
        enc = Encounter([i, b, g1, g2], ScriptedDice([3, 3, 3, 5, 5, 5, 5]))
        enc.start(order=["ilsevel", "brannoc", "g1", "g2"])
        enc.act({"type": "cast", "spell": "burning_hands", "level": 1, "toward": [3, 0]})
        ev = last(enc, "cast")
        hit = {r["target"] for r in ev["results"]}
        self.assertEqual(hit, {"g1", "g2", "brannoc"})
        self.assertEqual(ev["allies_hit"], ["brannoc"])

    def test_menu_reports_friendly_fire(self):
        i, b = pc("ilsevel"), pc("brannoc")
        g1, g2 = mon("goblin_warrior", "g1", pos=(2, 0)), mon("goblin_warrior", "g2", pos=(3, 1))
        i.pos, b.pos = (0, 0), (2, -1)
        enc = Encounter([i, b, g1, g2], Dice("x"))
        enc.start(order=["ilsevel", "brannoc", "g1", "g2"])
        areas = [o for o in enc.legal_actions() if o.get("enemies_hit") is not None]
        self.assertTrue(any(o["allies_hit"] for o in areas))
        self.assertTrue(any(len(o["enemies_hit"]) == 2 and not o["allies_hit"] for o in areas))


class TestFlanking(unittest.TestCase):
    def setup(self, flanking):
        b, o, d = pc("brannoc"), pc("oriel"), dummy(pos=(1, 0), ac=12)
        b.pos, o.pos = (0, 0), (2, 0)
        enc = Encounter([b, o, d], ScriptedDice([5, 15, 2, 2]), options={"flanking": flanking})
        enc.start(order=["brannoc", "oriel", "dummy"])
        enc.act({"type": "attack", "attack": "longsword", "target": "dummy"})
        return last(enc, "attack")

    def test_off_by_default(self):
        self.assertEqual(self.setup(False)["advantage"], "none")

    def test_on_gives_advantage(self):
        self.assertEqual(self.setup(True)["advantage"], "advantage")


class TestRoles(unittest.TestCase):
    def test_roles(self):
        self.assertEqual([role_of(pc(n)) for n in ("brannoc", "tamsin", "ilsevel", "oriel")],
                         ["tank", "skirmisher", "artillery", "support"])
        self.assertEqual(role_of(mon("goblin_minion")), "archer")

    def test_rogue_shoots_the_target_an_ally_is_engaging(self):
        t, b = pc("tamsin"), pc("brannoc")
        g1, g2 = mon("goblin_warrior", "g1", pos=(8, 0)), mon("goblin_warrior", "g2", pos=(8, 6))
        t.pos, b.pos = (0, 3), (7, 0)
        enc = Encounter([t, b, g1, g2], Dice("x"))
        enc.start(order=["tamsin", "brannoc", "g1", "g2"])
        it = simple_policy(enc, t)
        self.assertEqual((it["type"], it["attack"], it["target"]), ("attack", "shortbow", "g1"))

    def test_wizard_escapes_melee_with_shocking_grasp(self):
        i, g = pc("ilsevel"), mon("goblin_warrior", "g", pos=(1, 0))
        i.pos = (0, 0)
        enc = Encounter([i, g], Dice("x"))
        enc.start(order=["ilsevel", "g"])
        it = simple_policy(enc, i)
        self.assertEqual(it["spell"], "shocking_grasp")

    def test_tank_moves_to_guard_the_wizard(self):
        b, i = pc("brannoc"), pc("ilsevel")
        g = mon("goblin_warrior", "g", pos=(6, 1))
        b.pos, i.pos = (0, 0), (5, 0)
        enc = Encounter([b, i, g], Dice("x"))
        enc.start(order=["brannoc", "ilsevel", "g"])
        it = simple_policy(enc, b)
        self.assertEqual(it["type"], "move")
        dest = tuple(it["to"])
        self.assertLessEqual(max(abs(dest[0] - 6), abs(dest[1] - 1)), 1)  # ends next to the goblin

    def test_party_wins_most_tutorial_fights(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import demo_combat
        wins = sum(demo_combat.build(f"TAC-{n}").run(simple_policy)["winner"] == "party" for n in range(30))
        self.assertGreaterEqual(wins, 20)


if __name__ == "__main__":
    unittest.main()


class TestTacticsV2(unittest.TestCase):
    """Tactics 2 (production/features.json "tactics_v2"): only for new episodes."""

    def run_turn(self, enc, limit=8):
        c = enc.current
        for _ in range(limit):
            it = simple_policy(enc, c)
            if it.get("type") == "end_turn":
                break
            enc.act(it)
        return [e for e in enc.events if e.get("actor") == c.id and e["t"] in ("disengage", "move", "attack")]

    def goblin_between(self, tactics):
        b, i = pc("brannoc"), pc("ilsevel")
        b.pos, i.pos = (0, 0), (3, 2)
        g = mon("goblin_warrior", "g", pos=(1, 0))
        enc = Encounter([b, i, g], Dice("V2-SLIP"), options={"tactics": tactics})
        enc.start(order=["g", "brannoc", "ilsevel"])
        return enc

    def test_goblin_slips_past_the_fighter_to_the_wizard(self):
        ev = self.run_turn(self.goblin_between(2))
        self.assertEqual(ev[0]["t"], "disengage")              # Nimble Escape (bonus action)
        self.assertEqual([e["target"] for e in ev if e["t"] == "attack"], ["ilsevel"])
        self.assertFalse(any(e.get("opportunity") for e in ev))

    def test_tactics_1_goblin_just_hits_the_fighter(self):
        ev = self.run_turn(self.goblin_between(1))
        self.assertNotIn("disengage", [e["t"] for e in ev])
        self.assertEqual([e["target"] for e in ev if e["t"] == "attack"], ["brannoc"])

    def thrower(self, tactics):
        i = pc("ilsevel")
        i.pos = (8, 0)                                        # 40 ft: long range for a thrown dagger (20/60)
        g = mon("goblin_minion", "g", pos=(0, 0))
        enc = Encounter([i, g], Dice("V2-RANGE"), options={"tactics": tactics})
        enc.start(order=["g", "ilsevel"])
        return enc

    def test_shooter_steps_in_to_normal_range(self):
        enc = self.thrower(2)
        ev = self.run_turn(enc)
        self.assertEqual(ev[0]["t"], "move")
        atk = next(e for e in ev if e["t"] == "attack")
        self.assertNotEqual(atk["advantage"], "disadvantage")
        self.assertLessEqual(enc.dist(enc.get("g"), enc.get("ilsevel")), 20)

    def test_tactics_1_shooter_throws_from_long_range(self):
        enc = self.thrower(1)
        ev = self.run_turn(enc)
        self.assertEqual(ev[0]["t"], "attack")
        self.assertEqual(ev[0]["advantage"], "disadvantage")
        self.assertFalse(any("close_range" in o.get("tags", []) for o in enc.legal_actions()))

    def opportunity(self, tactics, faces):
        t, b = pc("tamsin"), pc("brannoc")
        g = mon("goblin_warrior", "g", pos=(1, 0))
        t.pos, b.pos = (0, 0), (2, 0)                        # Brannoc is next to the goblin too
        enc = Encounter([t, b, g], ScriptedDice(faces), options={"tactics": tactics})
        enc.start(order=["g", "tamsin", "brannoc"])
        enc.reactions["brannoc"] = False
        enc.act({"type": "move", "to": [1, 3], "path": [[1, 1], [1, 2], [1, 3]]})
        return next(e for e in enc.events if e["t"] == "attack" and e.get("opportunity"))

    def test_sneak_attack_on_an_opportunity_attack(self):
        self.assertTrue(self.opportunity(2, [15, 3, 4]).get("sneak_attack"))   # d20, shortsword d6, Sneak Attack d6
        self.assertFalse(self.opportunity(1, [15, 3]).get("sneak_attack"))
