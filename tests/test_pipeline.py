"""Phase 3: context, prompts, client accounting, resolution, assembly,
continuity, wiki and packaging. The end-to-end run replays fixtures/C01-E001."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import ROOT  # noqa: F401  (sets sys.path)

from pqc.dice import Dice
from pqc.pipeline import claude, context, prompts
from pqc.pipeline.assemble import assemble, split_box, walk_path
from pqc.pipeline.continuity import mechanical
from pqc.pipeline.packaging import chapters, fmt_time
from pqc.pipeline.resolve import apply_proposals, blocked_squares, check_roll_cues, resolve, triage, validate_plan
from pqc.state import GENESIS_DIR, GENESIS_PARTY_DIR as PARTY_DIR, load_json, load_party

FX = ROOT / "fixtures" / "C01-E001"
HAVE_PACK = (ROOT / "vendor" / "ninja-adventure" / "LICENSE.txt").exists()


def sheets():
    return {p.stem: load_json(p) for p in sorted(PARTY_DIR.glob("*.json"))}


def world():
    return load_json(GENESIS_DIR / "world.json")


def plan():
    return load_json(FX / "plan.json")


def script():
    return load_json(FX / "script.json")


class TestContext(unittest.TestCase):
    def test_strip_secrets(self):
        md = "# A\ntext\n> SECRET (reveal: C9): hidden\n> more hidden\n\nvisible\n## Secrets\n- gone\n## Next\nkept"
        out = context.strip_secrets(md)
        self.assertNotIn("hidden", out)
        self.assertNotIn("gone", out)
        self.assertIn("visible", out)
        self.assertIn("kept", out)

    def test_public_core_has_no_spoilers_and_dm_core_does(self):
        cp = context.ContextPack.build(1, 1, sheets(), world())
        self.assertEqual(cp.episode_id, "C01-E001")
        self.assertEqual(context.spoiler_hits(cp.public_core, 1), [])
        self.assertNotIn("SECRET", cp.public_core)
        self.assertIn("SECRET", cp.dm_core)
        self.assertTrue(context.spoiler_hits(cp.dm_core, 1))

    def test_public_world_hides_unnamed_and_unmet_npcs(self):
        w = world()
        w["npcs"]["npc.rusk"].update(status="captive", first_seen="C01-E001", name_known=False)
        self.assertNotIn("npc.rusk", context.world_brief(w, public=True))
        self.assertNotIn("npc.skarrow", context.world_brief(w, public=True))
        self.assertIn("npc.rusk", context.world_brief(w, public=False))


class TestPrompts(unittest.TestCase):
    def test_every_template_fills(self):
        values = dict(episode_id="C01-E001", seed="s", campaign_view="x", state_view="x", recap="x", stage_view="x",
                      plan="x", outcomes="x", mechanical="x", script="x", title="x", summary="x", actions="x",
                      arc="x", monsters="x", maps="x", short_moment="x", memories="x")
        for step, (template, *_rest) in prompts.STEPS.items():
            text = prompts.render(template, **values, feedback="")
            self.assertNotIn("{{", text, step)

    def test_shared_tool_prefix(self):
        a = prompts.build_request("plan", prompts.model_for("plan"), "CORE", episode_id="e", seed="s",
                                  campaign_view="", state_view="", recap="", stage_view="")
        b = prompts.build_request("script", prompts.model_for("script"), "CORE", episode_id="e", plan="", outcomes="",
                                  state_view="", recap="")
        self.assertEqual(a.prefix_key(), b.prefix_key())  # same model, tools and system: one cache
        body = a.body()
        self.assertEqual(body["tool_choice"], {"type": "tool", "name": "submit_plan"})
        self.assertEqual(len({t["name"] for t in body["tools"]}), len(prompts.STEPS))
        self.assertEqual(body["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("$schema", json.dumps(body["tools"]))

    def test_routing(self):
        self.assertEqual(prompts.model_for("script", {"milestone_level": None}), claude.MODELS["sonnet"])
        self.assertEqual(prompts.model_for("script", {"milestone_level": 2}), claude.MODELS["opus"])
        self.assertEqual(prompts.model_for("script", None, premiere_finale=True), claude.MODELS["opus"])
        self.assertEqual(prompts.model_for("continuity"), claude.MODELS["haiku"])
        self.assertEqual(prompts.model_for("campaign"), claude.MODELS["fable"])


class TestClaudeAccounting(unittest.TestCase):
    def test_usage_cost(self):
        u = claude.Usage("claude-sonnet-5-5", "plan", input_tokens=1_000_000, output_tokens=100_000)
        self.assertAlmostEqual(u.cost, 2.0 + 1.0)
        u.batch = True
        self.assertAlmostEqual(u.cost, 1.5)
        c = claude.Usage("claude-haiku-4-5-20251001", "x", cache_read_tokens=1_000_000, cache_write_tokens=1_000_000)
        self.assertAlmostEqual(c.cost, 0.10 + 1.25)

    def test_replay_warms_the_cache(self):
        led = claude.Ledger()
        rc = claude.ReplayClient(FX, led, batch=False)
        mk = lambda: prompts.build_request("continuity", prompts.model_for("continuity"), "CORE" * 2000,  # noqa: E731
                                           episode_id="e", mechanical="", plan="", outcomes="", script="",
                                           state_view="")
        rc.call(mk())
        rc.call(mk())
        self.assertGreater(led.entries[0].cache_write_tokens, 0)
        self.assertEqual(led.entries[1].cache_write_tokens, 0)
        self.assertEqual(led.entries[1].cache_read_tokens, led.entries[0].cache_write_tokens)
        self.assertLess(led.entries[1].cost, led.entries[0].cost)

    def test_tool_input_extraction(self):
        resp = {"content": [{"type": "text", "text": "hi"}, {"type": "tool_use", "name": "t", "input": {"a": 1}}]}
        self.assertEqual(claude._tool_input(resp, "t"), {"a": 1})
        with self.assertRaises(claude.ClaudeError):
            claude._tool_input({"content": []}, "t")


class TestValidation(unittest.TestCase):
    def test_fixture_plan_is_valid(self):
        self.assertEqual(validate_plan(plan(), sheets(), world()), [])

    def test_catches_bad_plans(self):
        p = plan()
        s4 = p["scenes"][3]
        s4["encounter"]["enemies"][0]["at"] = [9, 6]                # inside the Crooked Kettle
        s4["encounter"]["enemies"][1]["kind"] = "dragon"             # not in the monster list
        s4["encounter"]["enemies"][2]["at"] = [17, 14]               # adjacent to Tamsin at the start
        del s4["encounter"]["party_at"]["oriel"]
        p["scenes"][0]["checks"][0]["skill"] = "hacking"
        p["state_proposals"].append({"type": "flag", "id": "x", "if": "c99.success"})
        errs = "\n".join(validate_plan(p, sheets(), world()))
        for needle in ("inside a prop", "unknown monster", "adjacent", "missing oriel", "unknown skill",
                       "bad condition"):
            self.assertIn(needle, errs)

    def test_blocked_squares_match_props(self):
        b = blocked_squares("brindle_cross")
        self.assertIn((9, 6), b)       # inn
        self.assertNotIn((9, 8), b)    # inn door
        self.assertIn((21, 22), b)     # base of lantern 37


class TestResolve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = resolve(plan(), sheets(), world(), "C01-E001-1")

    def test_deterministic_and_verifiable(self):
        again = resolve(plan(), sheets(), world(), "C01-E001-1")
        self.assertEqual(again.outcomes, self.res.outcomes)
        self.assertTrue(Dice.verify_log("C01-E001-1", self.res.episode["rolls"]))
        other = resolve(plan(), sheets(), world(), "C01-E001-2")
        self.assertNotEqual(other.episode["rolls"], self.res.episode["rolls"])

    def test_record_valid_and_complete(self):
        from pqc.schema import validate_named
        self.assertEqual(validate_named(self.res.episode, "episode"), [])
        self.assertEqual({c["id"] for c in self.res.episode["checks"]}, {"c1", "c2", "c3", "c4"})
        self.assertEqual(len(self.res.episode["encounters"]), 1)
        ids = [r["id"] for r in self.res.episode["rolls"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_outcomes_match_rolls(self):
        rolls = {r["id"]: r for r in self.res.episode["rolls"]}
        for c in self.res.episode["checks"]:
            r = rolls[c["roll"]]
            self.assertEqual(c["success"], r["total"] >= c["dc"])

    def test_conditional_proposals(self):
        p = {"episode_id": "C01-E001", "scenes": [], "state_proposals": [
            {"type": "gold", "cp": 15, "to": "tamsin", "if": "c1.failure"},
            {"type": "bond", "a": "brannoc", "b": "oriel", "trust": 3},
            {"type": "lantern", "id": "lantern_road.037", "state": "dead"}]}
        sh, w = sheets(), world()
        log = apply_proposals(p, {"c1": "success"}, sh, w)
        self.assertFalse(log[0]["applied"])
        self.assertFalse(log[1]["applied"])
        self.assertIn("at most 1", log[1]["why"])
        self.assertTrue(log[2]["applied"])
        self.assertEqual(w["lanterns"]["lantern_road.037"], "dead")

    def test_triage_heals_the_downed(self):
        party = load_party(PARTY_DIR)
        party["ilsevel"].hp = 0
        party["ilsevel"].conditions = {"unconscious": None, "prone": None}
        out = triage(party, Dice("triage"))
        self.assertEqual(out[0]["who"], "oriel")
        self.assertEqual(out[0]["spell"], "healing_word")
        self.assertGreater(party["ilsevel"].hp, 0)
        self.assertEqual(party["oriel"].spellcasting["slots"]["1"]["current"], 1)

    def test_nonlethal_enemy_survives(self):
        end = self.res.outcomes["fights"][0]["end_state"]
        self.assertFalse(end["goblin-4"]["dead"])


class TestAssembly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan, cls.script, cls.sheets = plan(), script(), sheets()
        cls.res = resolve(cls.plan, cls.sheets, world(), "C01-E001-1")
        cls.cc = check_roll_cues(cls.res, cls.plan, cls.sheets)
        cls.asm = assemble(cls.plan, cls.script, cls.res, cls.cc, cls.sheets)

    def test_walk_path_avoids_props(self):
        blocked = blocked_squares("brindle_cross")
        path = walk_path("brindle_cross", [13, 8], [13, 12])  # around the inn lantern at (13, 11)
        pts = [[13, 8]] + path
        for a, b in zip(pts, pts[1:]):
            steps = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
            for k in range(1, steps + 1):
                sq = (a[0] + (b[0] - a[0]) * k // steps, a[1] + (b[1] - a[1]) * k // steps)
                self.assertNotIn(sq, blocked)
        self.assertEqual(path[-1], [13, 12])

    def test_split_box(self):
        long = "This sentence is fine. " * 10
        parts = split_box(long)
        self.assertTrue(all(len(p) <= 140 for p in parts))
        self.assertEqual(" ".join(parts), " ".join(long.split()))

    def test_timeline_valid_and_everything_placed(self):
        from pqc.schema import validate_named
        self.assertEqual(self.asm.problems, [])
        self.assertEqual(validate_named(self.asm.timeline, "timeline"), [])
        self.assertEqual(self.asm.placed, {"c1": 1, "c2": 1, "c3": 1, "e1": 1, "a1": 1, "c4": 1})
        ops = [c["op"] for c in self.asm.timeline["cues"]]
        self.assertEqual(ops[0], "title")
        self.assertIn("dm_intro", ops)
        self.assertEqual(self.asm.timeline["cues"][-3]["text"], "Next time: The goblin who talked.")

    def test_dice_tray_shows_the_logged_rolls(self):
        rolls = {r["id"]: r for r in self.res.episode["rolls"]}
        shown = [c for c in self.asm.timeline["cues"] if c["op"] in ("roll", "battle_attack")]
        self.assertTrue(shown)
        for c in shown:
            self.assertEqual(c["roll"]["total"], rolls[c["roll"]["id"]]["total"])

    def test_battle_narration_follows_its_action(self):
        cues = self.asm.timeline["cues"]
        k = next(i for i, c in enumerate(cues) if c.get("text", "").startswith("Brannoc's first swing"))
        actions = [c for c in cues[:k] if c["op"] in ("battle_attack", "battle_cast")]
        self.assertEqual(len(actions), 5)

    def test_unknown_speaker_is_reported(self):
        s = copy.deepcopy(self.script)
        s["scenes"][0]["cues"].insert(0, {"op": "say", "speaker": "skarrow", "text": "Boo."})
        asm = assemble(self.plan, s, self.res, self.cc, self.sheets)
        self.assertTrue(any("skarrow" in p for p in asm.problems))


class TestContinuity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan, cls.sheets = plan(), sheets()
        cls.res = resolve(cls.plan, cls.sheets, world(), "C01-E001-1")
        cls.cc = check_roll_cues(cls.res, cls.plan, cls.sheets)

    def blockers(self, s):
        return [i for i in mechanical(self.plan, s, self.res, self.cc, self.sheets) if i["severity"] == "blocker"]

    def test_fixture_script_passes(self):
        self.assertEqual(self.blockers(script()), [])

    def test_catches_problems(self):
        s = script()
        s1 = s["scenes"][0]["cues"]
        s1[:] = [c for c in s1 if c.get("id") != "c1"]                             # c1 never shown
        s1.insert(1, {"op": "say", "speaker": "tamsin", "text": "Okay, this is awesome."})  # slang
        s["scenes"][1]["cues"].insert(3, {"op": "narrate", "text": "She rolls a 22."})   # number after a roll
        s["scenes"][2]["cues"].append({"op": "narrate", "text": "The Gloamkey hums."})  # spoiler
        s["scenes"][4]["cues"].append({"op": "narrate", "text": "And the night goes on."})  # narrator ends
        text = json.dumps(self.blockers(s))
        for needle in ("c1 is placed 0 times", "slang", "number", "spoiler", "party member"):
            self.assertIn(needle, text)


class TestPackaging(unittest.TestCase):
    def test_fmt_time(self):
        self.assertEqual(fmt_time(65.4), "1:05")
        self.assertEqual(fmt_time(3725), "1:02:05")

    def test_chapters_start_at_zero_and_merge_short_ones(self):
        tl = {"chapters": [{"cue": 0, "title": "Title"}, {"cue": 1, "title": "A"}, {"cue": 2, "title": "B"},
                           {"cue": 3, "title": "C"}, {"cue": 4, "title": "Next time"}]}
        ch = chapters(tl, [0, 3, 50, 55, 120], 128)
        self.assertEqual([c["title"] for c in ch], ["A", "C"])
        self.assertEqual(ch[0]["time"], "0:00")


@unittest.skipUnless(HAVE_PACK, "asset pack not fetched")
class TestEndToEnd(unittest.TestCase):
    def test_offline_episode(self):
        from pqc.pipeline import episode as ep
        from pqc.pipeline import wiki
        live_before = (ROOT / "state" / "world.json").read_text()
        with tempfile.TemporaryDirectory() as d:
            eps = Path(d) / "episodes"
            with mock.patch.object(ep, "EPISODES", eps), mock.patch.object(wiki, "EPISODES", eps):
                out = ep.run_episode(ep.EpisodeConfig(1, 1, state_dir=GENESIS_DIR), log=lambda *_: None)
            o = out["dir"]
            for f in ("plan.json", "outcomes.json", "script.json", "continuity.json", "timeline.json",
                      "chapters.json", "wiki_facts.json", "packaging.json", "thumbnail.png", "episode.json",
                      "cost.json", "state_after/world.json", "wiki_preview/index.md"):
                self.assertTrue((o / f).exists(), f)
            self.assertTrue(300 <= out["duration"] <= 600, out["duration"])
            cost = json.loads((o / "cost.json").read_text())
            self.assertTrue(0.01 < cost["total_usd"] < 1.0)
            w = json.loads((o / "state_after" / "world.json").read_text())
            self.assertEqual(w["lanterns"]["lantern_road.037"], "dead")
            self.assertEqual(w["npcs"]["npc.rusk"]["status"], "captive")
            self.assertEqual(w["series"]["episode_in_campaign"], 1)
            pages = "\n".join(p.read_text() for p in (o / "wiki_preview").rglob("*.md"))
            self.assertNotIn("Rusk", pages)              # not named on screen yet
            self.assertNotIn("Gloamkey", pages)
            pk = json.loads((o / "packaging.json").read_text())
            self.assertIn("0:00", pk["description_full"])
            self.assertIn("C01-E001-1", pk["description_full"])
        # The real state was not touched.
        self.assertEqual((ROOT / "state" / "world.json").read_text(), live_before)

    def test_episodes_already_made_replay_unchanged(self):
        """Engine and pipeline updates are switched on per episode (production/features.json): replaying
        every committed episode from its archived state and fixtures must give back what was made."""
        from pqc.pipeline import episode as ep
        from pqc.pipeline import wiki
        known = {("C01-E009", "outcomes.json"), ("C01-E009", "state_after/party/oriel.json")}  # prone carried over by hand
        made = sorted(p.name for p in (ROOT / "episodes").glob("C01-E0*") if (p / "state_before").exists())
        with tempfile.TemporaryDirectory() as d:
            eps = Path(d) / "episodes"
            for eid in made:
                with mock.patch.object(ep, "EPISODES", eps), mock.patch.object(wiki, "EPISODES", eps):
                    out = ep.run_episode(ep.EpisodeConfig(1, int(eid[-3:]),
                                                          state_dir=ROOT / "episodes" / eid / "state_before"),
                                         log=lambda *_: None)["dir"]
                for f in ("plan.json", "script.json", "outcomes.json", "timeline.json", "chapters.json",
                          "state_after/world.json", *(f"state_after/party/{c}.json" for c in
                                                     ("brannoc", "ilsevel", "oriel", "tamsin"))):
                    if (eid, f) in known:
                        continue
                    self.assertEqual((out / f).read_text(), (ROOT / "episodes" / eid / f).read_text(), f"{eid} {f}")
                a = json.loads((out / "episode.json").read_text())
                b = json.loads((ROOT / "episodes" / eid / "episode.json").read_text())
                a.pop("status"), b.pop("status")
                self.assertEqual(a, b, eid)

    def test_wiki_refuses_spoilers(self):
        from pqc.pipeline import wiki
        with tempfile.TemporaryDirectory() as d:
            eps = Path(d) / "episodes"
            e = eps / "C01-E001"
            e.mkdir(parents=True)
            res = resolve(plan(), sheets(), world(), "C01-E001-1")
            (e / "episode.json").write_text(json.dumps(res.episode))
            facts = load_json(FX / "wiki_facts.json")
            facts["summary"] += " Tamsin's iron key is the Gloamkey."
            (e / "wiki_facts.json").write_text(json.dumps(facts))
            with mock.patch.object(wiki, "EPISODES", eps):
                with self.assertRaises(wiki.SpoilerLeak):
                    wiki.build_site(Path(d) / "docs")
            shutil.rmtree(e)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE_PACK, "asset pack not fetched")
class TestAgentMode(unittest.TestCase):
    """A Claude session plays the model: missing outputs become pending prompts."""

    def test_pending_prompts_and_rejection(self):
        from pqc.pipeline import episode as ep
        from pqc.pipeline import wiki
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            eps, fx = d / "episodes", d / "fixtures"
            (fx / "C01-E001").mkdir(parents=True)
            for f in ("plan.json", "continuity.json", "wiki_facts.json", "packaging.json"):
                shutil.copy(FX / f, fx / "C01-E001" / f)
            bad = script()
            bad["scenes"][0]["cues"] = [c for c in bad["scenes"][0]["cues"] if c.get("id") != "c1"]
            (fx / "C01-E001" / "script.json").write_text(json.dumps(bad))
            cfg = ep.EpisodeConfig(1, 1, mode="agent", state_dir=GENESIS_DIR)
            with mock.patch.object(ep, "EPISODES", eps), mock.patch.object(wiki, "EPISODES", eps), \
                    mock.patch.object(ep, "FIXTURES", fx), mock.patch.object(ep, "ROOT", d):
                with self.assertRaises(ep.NeedsAuthor) as need:
                    ep.run_episode(cfg, log=lambda *_: None)
                self.assertEqual(need.exception.step, "script")
                text = need.exception.prompt_path.read_text()
                self.assertIn("rejected", text)                 # the reasons come back
                self.assertIn("c1 is placed 0 times", text)
                self.assertIn('"result": "FAILURE"', text)      # the writer sees the dice
                self.assertTrue((fx / "C01-E001" / "script.rejected1.json").exists())
                shutil.copy(FX / "script.json", fx / "C01-E001" / "script.json")
                out = ep.run_episode(cfg, log=lambda *_: None)
            self.assertTrue((out["dir"] / "timeline.json").exists())
            self.assertFalse((out["dir"] / "pending").exists())
            self.assertEqual(json.loads((out["dir"] / "cost.json").read_text())["mode"], "agent")

    def test_public_step_prompt_says_no_secrets(self):
        from pqc.pipeline import episode as ep
        led = claude.Ledger()
        with tempfile.TemporaryDirectory() as d:
            client = ep.AgentClient(Path(d) / "fx", Path(d) / "pending", led)
            req = prompts.build_request("wiki_facts", prompts.model_for("wiki_facts"), "CORE", episode_id="e",
                                        script="", outcomes="", state_view="", recap="")
            with mock.patch.object(ep, "ROOT", Path(d)):
                with self.assertRaises(ep.NeedsAuthor) as need:
                    client.call(req)
            self.assertIn("PUBLIC step", need.exception.prompt_path.read_text())


class TestProductionQueue(unittest.TestCase):
    def test_queue_order_and_lock(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("production", ROOT / "scripts" / "production.py")
        prod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prod)
        with tempfile.TemporaryDirectory() as d:
            q = Path(d) / "queue.json"
            shutil.copy(ROOT / "production" / "queue.json", q)
            with mock.patch.object(prod, "QUEUE", q), mock.patch.object(prod, "LOG", Path(d) / "LOG.md"):
                data = prod.load()
                for t in data["tasks"]:   # judge the queue's shape, not how far tonight's shifts have got
                    t["status"] = "todo"
                data["lock"] = None
                prod.save(data)
                data = prod.load()
                ids = [t["id"] for t in data["tasks"]]
                for t in data["tasks"]:   # every prerequisite exists and comes earlier
                    for a in t.get("after", []):
                        self.assertIn(a, ids)
                        self.assertLess(ids.index(a), ids.index(t["id"]))
                self.assertEqual(prod.ready(data)[0]["id"], data["tasks"][0]["id"])
                self.assertEqual(prod.main(["lock", "s1"]), 0)
                self.assertEqual(prod.main(["lock", "s2"]), 1)      # fresh lock held by s1
                self.assertEqual(prod.main(["unlock", "s1"]), 0)
                self.assertEqual(prod.main(["lock", "s2"]), 0)
                prod.main(["done", "episode:2"])
                self.assertIn("episode:3", [t["id"] for t in prod.ready(prod.load())])
                self.assertNotIn("episode:4", [t["id"] for t in prod.ready(prod.load())])


class TestRelay(unittest.TestCase):
    """Change bundles: exact round trip, hash check, path rules."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("relay", ROOT / "scripts" / "relay.py")
        cls.relay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.relay)

    def bundle(self, files: dict) -> str:
        r = self.relay
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(r, "ROOT", Path(d)):
                for path, data in files.items():
                    (Path(d) / path).parent.mkdir(parents=True, exist_ok=True)
                    (Path(d) / path).write_bytes(data)
                blocks, refused = r._encode([("M", p) for p in files])
        self.assertEqual(refused, [])
        return "PQC-CHANGE 1\nname: change-x\nmessage: t\nrun: episode_commit 2\n" + "".join(blocks) + "=== END\n"

    def test_round_trip(self):
        files = {"fixtures/C01-E002/plan.json": json.dumps({"a": "quote \" and\nnewline === x"}).encode(),
                 "scripts/maps/x.py": b"print('hi')\n\n\n",
                 "assets/sprites/pell.png": bytes(range(256))}
        b = self.relay.parse(self.bundle(files))
        got = {p: d for _, p, d in b["ops"]}
        self.assertEqual(got["scripts/maps/x.py"], files["scripts/maps/x.py"])
        self.assertEqual(got["assets/sprites/pell.png"], files["assets/sprites/pell.png"])
        self.assertEqual(json.loads(got["fixtures/C01-E002/plan.json"]), json.loads(files["fixtures/C01-E002/plan.json"]))
        self.assertEqual(b["runs"], ["episode_commit 2"])

    def test_tampering_and_truncation_are_rejected(self):
        text = self.bundle({"fixtures/a.json": b'{"x": 1}\n'})
        with self.assertRaises(ValueError):
            self.relay.parse(text.replace('"x": 1', '"x": 2'))
        with self.assertRaises(ValueError):
            self.relay.parse(text.replace("=== END\n", ""))

    def test_path_rules(self):
        r = self.relay
        self.assertTrue(r.allowed("fixtures/C01-E002/script.json"))
        self.assertTrue(r.allowed("assets/manifest.json"))
        self.assertFalse(r.allowed("state/world.json"))          # derived: the Action regenerates it
        self.assertFalse(r.allowed("episodes/C01-E002/plan.json"))
        self.assertFalse(r.allowed(".github/workflows/relay.yml"))
        with self.assertRaises(ValueError):
            r.parse("PQC-CHANGE 1\n=== DELETE state/world.json\n=== END\n")


class TestClockProposals(unittest.TestCase):
    def test_lighting_presets_map_to_clock_values(self):
        from pqc.pipeline.resolve import clock_time
        self.assertEqual(clock_time("day"), "noon")
        self.assertEqual(clock_time("dusk"), "dusk")
        with self.assertRaises(ValueError):
            clock_time("teatime")


class TestRelayParts(unittest.TestCase):
    def test_parts_are_grouped_and_wait_for_each_other(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("relay", ROOT / "scripts" / "relay.py")
        r = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(r)
        t = lambda m: f"PQC-CHANGE 1\nmessage: {m}\n=== END\n"  # noqa: E731
        texts = {"c-001": t("plan"), "c-002": t("maps (part 1/2)"), "c-003": t("maps (part 2/2)"),
                 "c-004": t("episode")}
        self.assertEqual(r._group_parts(texts), [["c-001"], ["c-002", "c-003"], ["c-004"]])
        del texts["c-003"]
        self.assertEqual(r._group_parts(texts), [["c-001"], None])


class TestYouTube(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("youtube_upload", ROOT / "scripts" / "youtube_upload.py")
        cls.yt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.yt)
        cls.cfg = load_json(ROOT / "production" / "youtube.json")
        cls.cfg["schedule"].update(timezone="Europe/Madrid", time="17:00", weekdays=[0, 1, 2, 3, 4])
        cls.cfg["follow_release_schedule"] = False

    def test_config_starts_disabled(self):
        self.assertFalse(self.cfg["enabled"])

    def test_slots_are_weekdays_at_local_time(self):
        import datetime as dt
        from zoneinfo import ZoneInfo
        fri = dt.datetime(2026, 10, 9, 18, 0, tzinfo=ZoneInfo("Europe/Madrid"))   # Friday after the slot
        slots = self.yt.next_slots(self.cfg, fri, 3)
        local = [s.astimezone(ZoneInfo("Europe/Madrid")) for s in slots]
        self.assertEqual([(t.day, t.hour, t.weekday()) for t in local], [(12, 17, 0), (13, 17, 1), (14, 17, 2)])
        # Across the October clock change the local time stays 17:00.
        late = self.yt.next_slots(self.cfg, dt.datetime(2026, 10, 22, 18, tzinfo=ZoneInfo("Europe/Madrid")), 2)
        self.assertEqual([s.astimezone(ZoneInfo("Europe/Madrid")).hour for s in late], [17, 17])
        self.assertEqual([s.hour for s in late], [15, 16])

    def test_schedule_follows_last_premiere(self):
        import datetime as dt
        now = dt.datetime(2026, 10, 5, 8, tzinfo=dt.timezone.utc)
        ledger = {"C01-E001": {"publish_at": "2026-10-07T15:00:00Z"}}
        got = self.yt.schedule_for(self.cfg, ledger, ["C01-E002"], now)
        self.assertEqual(self.yt.iso(got["C01-E002"]), "2026-10-08T15:00:00Z")

    def test_pending_is_strictly_in_order(self):
        rel = ["C01-E001", "C01-E002", "C01-E003", "C01-E004"]
        self.assertEqual(self.yt.pending({"C01-E001": {}}, rel), ["C01-E002", "C01-E003", "C01-E004"])
        self.assertEqual(self.yt.pending({"C01-E001": {}, "C01-E003": {}}, rel), ["C01-E002"])

    def test_metadata_fits_youtube_limits(self):
        import datetime as dt
        for p in sorted((ROOT / "episodes").glob("C01-E*/packaging.json")):
            pk = load_json(p)
            body = self.yt.video_body(pk, self.cfg, dt.datetime(2026, 10, 7, 15, tzinfo=dt.timezone.utc))
            sn, st = body["snippet"], body["status"]
            self.assertLessEqual(len(sn["title"]), 100)
            self.assertLessEqual(len(sn["description"]), 5000)
            self.assertNotIn("<", sn["title"] + sn["description"])
            self.assertLessEqual(len(",".join(sn["tags"])), 500)
            self.assertIn("0:00", sn["description"])           # chapters survive
            self.assertEqual((st["privacyStatus"], st["publishAt"]), ("private", "2026-10-07T15:00:00Z"))
        tags = self.yt.clean_tags(["a<b>", "x, y", "z" * 600])
        self.assertEqual(tags, ["ab", "x  y"])

    def test_link_marks_passed_premieres_and_wiki_shows_them(self):
        import datetime as dt
        from pqc.pipeline import wiki
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "youtube.json"
            ledger.write_text(json.dumps({
                "C01-E001": {"video_id": "abc", "url": "https://www.youtube.com/watch?v=abc",
                             "publish_at": "2026-10-05T15:00:00Z", "linked": False},
                "C01-E002": {"video_id": "def", "url": "https://www.youtube.com/watch?v=def",
                             "publish_at": "2026-10-06T15:00:00Z", "linked": False}}))
            with mock.patch.object(self.yt, "LEDGER", ledger):
                self.yt.cmd_link(dt.datetime(2026, 10, 5, 16, tzinfo=dt.timezone.utc))
            got = json.loads(ledger.read_text())
            self.assertEqual((got["C01-E001"]["linked"], got["C01-E002"]["linked"]), (True, False))
            fake = Path(tmp) / "wiki"
            (fake / "data").mkdir(parents=True)
            shutil.copy(ledger, fake / "data" / "youtube.json")
            arch = {e["id"]: e for e in wiki.load_archive()}
            canon = wiki.build_canon(list(arch.values()))
            with mock.patch.object(wiki, "WIKI", fake):
                p1 = wiki._episode_page(arch["C01-E001"], canon, sheets())
                p2 = wiki._episode_page(arch["C01-E002"], canon, sheets())
            self.assertIn("watch?v=abc", p1)
            self.assertNotIn("YouTube", p2)


class TestTrailer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("trailer", ROOT / "scripts" / "trailer.py")
        cls.tr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.tr)
        cls.spec = load_json(ROOT / "assets" / "timelines" / "trailer_c01.json")

    def test_spec_points_at_real_cues_and_shorts_fit(self):
        wide = vertical = 0.0
        for s in self.spec["shots"]:
            if "ep" in s:
                tl = load_json(ROOT / "episodes" / f"C01-E{s['ep']:03d}" / "timeline.json")
                self.assertLess(s["cue"], len(tl["cues"]), s)
            wide += s["dur"]
            if not s.get("wide_only"):
                vertical += s["dur"]
        self.assertLess(vertical, 60)
        self.assertLess(wide, 120)

    def test_start_positions_skip_wide_only_shots_in_the_vertical_cut(self):
        shots = [{"card": ["a"], "dur": 2.0}, {"ep": 1, "cue": 1, "dur": 3.0, "wide_only": True},
                 {"ep": 1, "cue": 2, "dur": 1.0}]
        self.assertEqual(self.tr.start_pos("wide", shots, {}, 30, shots[1:], 1), [2.0, 5.0])
        self.assertEqual(self.tr.start_pos("vertical", shots, {}, 30, shots[1:], 1), [None, 2.0])


@unittest.skipUnless(HAVE_PACK, "needs vendor/ (fonts)")
class TestBrand(unittest.TestCase):
    def test_logo_and_intro_frames(self):
        import importlib.util
        from pqc.render import brand
        from pqc.render.assets import Assets
        a = Assets()
        self.assertEqual(brand.d20_mark(a, 2).size, (96, 96))
        self.assertGreater(brand.lockup(a, stacked=False, scale=1, tagline="x").width, 48)
        spec = importlib.util.spec_from_file_location("branding", ROOT / "scripts" / "branding.py")
        br = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(br)
        frames = list(br.intro_frames(a, (480, 270)))
        self.assertEqual(len(frames), 126)
        self.assertEqual(frames[0].size, (480, 270))
        self.assertEqual(len(list(br.outro_frames(a, (270, 480)))), 90)


class TestThumbnailSpec(unittest.TestCase):
    def test_specs_name_real_actors_and_split_titles(self):
        from pqc.pipeline.packaging import _split_title, thumbnail_spec
        from PIL import Image, ImageDraw, ImageFont
        d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        f = ImageFont.load_default()
        self.assertEqual(_split_title(d, "RUN!", f, 1000), ["RUN!"])
        self.assertEqual(_split_title(d, "THE LIGHT WAS TAKEN", f, 70), ["THE LIGHT", "WAS TAKEN"])
        manifest = load_json(ROOT / "assets" / "manifest.json")["actors"]
        for n in range(1, 11):
            spec = thumbnail_spec(f"C01-E{n:03d}")
            self.assertTrue(spec.get("text"))
            for who in spec.get("faces", []) + [spec.get("focus")]:
                self.assertIn(who, manifest, who)


class TestYouTubeRecord(unittest.TestCase):
    def test_record_by_hand(self):
        import datetime as dt
        import importlib.util
        spec = importlib.util.spec_from_file_location("youtube_upload2", ROOT / "scripts" / "youtube_upload.py")
        yt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(yt)
        for link in ("https://youtu.be/abcDEF12345", "https://www.youtube.com/watch?v=abcDEF12345&t=3",
                     "https://youtube.com/shorts/abcDEF12345", "abcDEF12345"):
            self.assertEqual(yt.video_id(link), "abcDEF12345")
        with self.assertRaises(SystemExit):
            yt.video_id("https://example.com/x")
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "youtube.json"
            now = dt.datetime(2026, 10, 7, 12, tzinfo=dt.timezone.utc)
            with mock.patch.object(yt, "LEDGER", ledger):
                yt.cmd_record("3", "https://youtu.be/abcDEF12345", "2026-10-08 21:00", now=now)
                yt.cmd_record("1", "https://youtu.be/zzzDEF12345", None, now=now)
            got = json.loads(ledger.read_text())
            self.assertEqual(got["C01-E003"]["publish_at"], "2026-10-08T19:00:00Z")   # 21:00 CEST
            self.assertFalse(got["C01-E003"]["linked"])
            self.assertTrue(got["C01-E001"]["linked"])
            self.assertEqual(yt.pending(got, ["C01-E001", "C01-E002", "C01-E003"]), ["C01-E002"])


class TestPremiereSchedule(unittest.TestCase):
    CFG = {"timezone": "Europe/Paris", "time": "21:00", "first_episode": "C01-E001", "first_date": "2026-10-12",
           "weekdays": [0, 1, 2, 3, 4], "skip_dates": ["2026-10-14"], "overrides": {"C01-E009": "2026-10-31 18:00"}}

    def test_one_per_weekday_with_skips_and_overrides(self):
        import datetime as dt
        from pqc import schedule
        p = lambda e: schedule.premiere(e, self.CFG).strftime("%a %d %H:%M")  # noqa: E731
        self.assertEqual(p("C01-E001"), "Mon 12 19:00")          # 21:00 Paris (CEST) = 19:00 UTC
        self.assertEqual(p("C01-E002"), "Tue 13 19:00")
        self.assertEqual(p("C01-E003"), "Thu 15 19:00")          # Wednesday 14 skipped
        self.assertEqual(p("C01-E005"), "Mon 19 19:00")          # weekend skipped
        self.assertEqual(p("C01-E010"), "Mon 26 20:00")          # after the clock change: still 21:00 Paris
        self.assertEqual(p("C01-E009"), "Sat 31 17:00")          # pinned
        self.assertEqual(schedule.ordinal("C02-E001"), 40)
        before = dt.datetime(2026, 10, 12, 18, 59, tzinfo=dt.timezone.utc)
        self.assertFalse(schedule.is_public("C01-E001", before, self.CFG))
        self.assertTrue(schedule.is_public("C01-E001", before + dt.timedelta(minutes=1), self.CFG))

    def test_public_wiki_hides_unreleased_episodes(self):
        import datetime as dt
        from pqc.pipeline import wiki
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("pqc.schedule.config", return_value=self.CFG):
                wiki.build_site(Path(tmp), public_only=True, now=dt.datetime(2026, 10, 13, 20, tzinfo=dt.timezone.utc))
            eps = sorted(p.name for p in (Path(tmp) / "episodes").glob("c01-*.md"))
            self.assertEqual(eps, ["c01-e001.md", "c01-e002.md"])
            home = (Path(tmp) / "index.md").read_text()
            self.assertIn("**Episode 3** premieres", home)
            text = "".join(p.read_text() for p in Path(tmp).rglob("*.md"))
            self.assertNotIn("Ironvow", text)                     # revealed only in Episode 10
            self.assertNotIn("Underbough", text)                  # never said on screen

    def test_chapters_allow_for_the_intro(self):
        from pqc.pipeline.packaging import with_bumpers
        chap = [{"time": "0:00", "seconds": 0.0, "title": "A"}, {"time": "1:58", "seconds": 118.2, "title": "B"}]
        out, total = with_bumpers(chap, 4.2, 3.0, 366.6)
        self.assertEqual([c["time"] for c in out], ["0:00", "2:02"])
        self.assertAlmostEqual(total, 373.8)


class TestReleaseIdentity(unittest.TestCase):
    def test_changing_a_map_or_its_art_re_renders_the_episode(self):
        import importlib.util
        import tempfile
        spec = importlib.util.spec_from_file_location("release_episodes", ROOT / "scripts" / "release_episodes.py")
        rel = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rel)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            m = tmp / "m.json"
            m.write_text(json.dumps({"id": "m", "props": [{"prop": "stone_lantern", "at": [1, 1]}]}))
            ep = tmp / "C09-E001"
            ep.mkdir()
            (ep / "timeline.json").write_text(json.dumps({"cues": [{"op": "scene", "map": str(m)}]}))
            first = rel.scene_digest(ep)
            self.assertEqual(first, rel.scene_digest(ep))
            m.write_text(json.dumps({"id": "m", "props": [{"prop": "lantern_post", "at": [1, 1]}]}))
            self.assertNotEqual(first, rel.scene_digest(ep))
        for n in range(1, 11):                                   # every committed episode can be digested
            self.assertEqual(len(rel.scene_digest(ROOT / "episodes" / f"C01-E{n:03d}")), 64)

    def test_drafts_are_found_by_their_video_and_duplicates_pruned(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("release_episodes", ROOT / "scripts" / "release_episodes.py")
        rel = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rel)
        a = {"id": 1, "tag_name": "untagged-abc", "draft": True, "assets": [{"name": "C01-E003.mp4"}]}
        b = {"id": 2, "tag_name": "C01-E003", "draft": True, "assets": [{"name": "C01-E003.mp4"}]}
        c = {"id": 3, "tag_name": "untagged-def", "draft": True, "assets": [{"name": "notes.txt"}]}
        self.assertEqual(rel.episode_of(a), "C01-E003")
        self.assertIsNone(rel.episode_of(c))
        calls = []

        def fake(path, method="GET", fields=None):
            calls.append((method, path))
            return [a, b, c] if path.endswith("&page=1") else []
        with mock.patch.object(rel, "gh_api", side_effect=fake):
            got = rel.all_releases("o/r")
        self.assertEqual(got["C01-E003"]["id"], 2)                 # the one tagged with the id is kept
        self.assertIn(("DELETE", "repos/o/r/releases/1"), calls)    # the stray draft is removed


class TestYouTubeRefresh(unittest.TestCase):
    def test_refresh_stamps_existing_and_deletes_missing(self):
        import datetime as dt
        import importlib.util
        spec = importlib.util.spec_from_file_location("youtube_upload3", ROOT / "scripts" / "youtube_upload.py")
        yt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(yt)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "youtube.json"
            ledger.write_text(json.dumps({
                "C01-E001": {"video_id": "aaaaaaaaaaa", "publish_at": "2026-10-12T19:00:00Z", "linked": True},
                "C01-E002": {"video_id": "bbbbbbbbbbb", "publish_at": "2026-10-13T19:00:00Z", "linked": False}}))
            env = {"YT_CLIENT_ID": "x", "YT_CLIENT_SECRET": "y", "YT_REFRESH_TOKEN": "z"}
            body = json.dumps({"items": [{"id": "aaaaaaaaaaa"}]}).encode()
            now = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
            with mock.patch.object(yt, "LEDGER", ledger), mock.patch.dict("os.environ", env), \
                    mock.patch.object(yt, "access_token", return_value="t"), \
                    mock.patch.object(yt, "_request", return_value=(200, {}, body)):
                yt.cmd_refresh(now)
            got = json.loads(ledger.read_text())
            self.assertEqual(list(got), ["C01-E001"])
            self.assertEqual(got["C01-E001"]["refreshed_at"], "2026-11-01T00:00:00Z")
            with mock.patch.object(yt, "LEDGER", ledger), mock.patch.dict("os.environ", env), \
                    mock.patch.object(yt, "access_token", return_value="t"), \
                    mock.patch.object(yt, "_request", return_value=(500, {}, b"boom")):
                with self.assertRaises(SystemExit):
                    yt.cmd_refresh(now)
            self.assertEqual(list(json.loads(ledger.read_text())), ["C01-E001"])   # nothing deleted on error


class TestShorts(unittest.TestCase):
    def test_highlight_windows_fit_a_short(self):
        from pqc.pipeline import highlight
        for n in range(1, 11):
            eid = f"C01-E{n:03d}"
            w = load_json(ROOT / "episodes" / eid / "short.json")
            tl = load_json(ROOT / "episodes" / eid / "timeline.json")
            self.assertLess(w["start_cue"], w["end_cue"])
            self.assertLessEqual(w["end_cue"], len(tl["cues"]))
            self.assertTrue(20 <= w["duration_s"] <= 60, (eid, w["duration_s"]))
            self.assertTrue(w["start_cue"] <= w["anchor_cue"] < w["end_cue"], eid)
            pk = load_json(ROOT / "episodes" / eid / "packaging.json")
            self.assertLessEqual(len(pk["short"]["hook"]), 32)
            self.assertIn("nat20pixelsaga.com/episodes/", pk["short"]["description_full"])
            self.assertIn("#shorts", pk["short"]["description_full"])
        # scoring: a natural 20 beats an ordinary roll, a party member going down beats a goblin
        hit = {"op": "battle_attack", "roll": {"natural": 20, "critical": True}, "label": "x"}
        plain = {"op": "roll", "roll": {"natural": 11}, "label": "Tamsin - Stealth"}
        self.assertGreater(highlight.score_cue(hit)[0], highlight.score_cue(plain)[0])
        self.assertEqual(highlight.score_cue({"op": "battle_faint", "actor": "oriel", "pc": True})[1], "down")
        self.assertEqual(highlight.score_cue({"op": "battle_faint", "actor": "goblin-2"})[1], "kill")

    def test_short_goes_up_the_next_day_at_lunchtime(self):
        from pqc import schedule
        cfg = {"timezone": "Europe/Paris", "time": "21:00", "first_episode": "C01-E001", "first_date": "2026-10-12",
               "weekdays": [0, 1, 2, 3, 4], "short_time": "13:00", "short_delay_days": 1}
        self.assertEqual(schedule.short_premiere("C01-E001", cfg).strftime("%a %d %H:%M"), "Tue 13 11:00")
        self.assertEqual(schedule.short_premiere("C01-E005", cfg).strftime("%a %d %H:%M"), "Sat 17 11:00")

    def test_record_a_short_by_hand(self):
        import datetime as dt
        import importlib.util
        spec = importlib.util.spec_from_file_location("youtube_upload4", ROOT / "scripts" / "youtube_upload.py")
        yt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(yt)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "youtube.json"
            with mock.patch.object(yt, "LEDGER", ledger):
                yt.cmd_record("1s", "https://youtube.com/shorts/abcDEF12345", "2026-10-13 13:00",
                              now=dt.datetime(2026, 10, 7, tzinfo=dt.timezone.utc))
            got = json.loads(ledger.read_text())
            self.assertEqual(list(got), ["C01-E001-short"])
            self.assertEqual(got["C01-E001-short"]["publish_at"], "2026-10-13T11:00:00Z")


class TestUpdatesForNewEpisodes(unittest.TestCase):
    """production/features.json: level-ups, the progress card, camps, memories (from C01-E011)."""

    def setUp(self):
        from pqc.state import load_json
        self.sheets = {p.stem: load_json(p) for p in (ROOT / "episodes" / "C01-E010" / "state_after" / "party").glob("*.json")}
        self.world = load_json(ROOT / "episodes" / "C01-E010" / "state_after" / "world.json")

    def plan(self, src, eid, **changes):
        p = json.loads((ROOT / "episodes" / src / "plan.json").read_text())
        p["episode_id"] = eid
        p.update(changes)
        return p

    def test_switches_by_episode(self):
        from pqc import features
        for name in ("tactics_v2", "level_ups", "progress_card", "memories", "camps", "xp_banner"):
            self.assertFalse(features.enabled(name, "C01-E010"), name)
            self.assertTrue(features.enabled(name, "C01-E011"), name)
            self.assertTrue(features.enabled(name, "C02-E001"), name)

    def test_milestone_levels_the_party_with_what_is_new(self):
        from pqc.pipeline.resolve import resolve
        res = resolve(self.plan("C01-E009", "C01-E015"), self.sheets, self.world, "C01-E015-1")
        ups = {r["id"]: r for r in res.episode["level_ups"]}
        self.assertEqual(sorted(ups), ["brannoc", "ilsevel", "oriel", "tamsin"])
        self.assertIn("Action Surge", ups["brannoc"]["new"])
        self.assertIn("Cunning Action", ups["tamsin"]["new"])
        self.assertIn("fog_cloud", res.sheets_after["ilsevel"]["spellcasting"]["spellbook"])
        self.assertIn("shield_of_faith", res.sheets_after["oriel"]["spellcasting"]["prepared"])
        self.assertIn("arcana", res.sheets_after["ilsevel"]["expertise"])
        self.assertEqual(res.sheets_after["brannoc"]["level"], 2)
        self.assertEqual(res.episode["progress"]["brannoc"]["xp_to_next"], 600)
        self.assertEqual(res.outcomes["level_ups"][0]["level"], 2)
        self.assertTrue(any(c.get("source", "").startswith("milestone") for c in res.episode["state_changes"]))
        from pqc.schema import validate_named
        self.assertEqual(validate_named(res.episode, "episode"), [])
        banner = next(c for c in res.battles["e1"]["cues"] if c["op"] == "battle_end")
        self.assertTrue(banner["banner"].endswith("XP each"))

    def test_no_level_up_without_the_xp(self):
        from pqc.pipeline.resolve import resolve
        res = resolve(self.plan("C01-E006", "C01-E012"), self.sheets, self.world, "C01-E012-1")
        self.assertEqual(res.episode["level_ups"], [])
        self.assertEqual(res.outcomes["party_after"]["oriel"]["xp_to_next"], 90)

    def test_progress_card_cue(self):
        from pqc.pipeline.assemble import progress_cue
        from pqc.pipeline.resolve import resolve
        res = resolve(self.plan("C01-E009", "C01-E015"), self.sheets, self.world, "C01-E015-1")
        cue = progress_cue("C01-E015", res, self.sheets)
        self.assertEqual(cue["op"], "progress")
        self.assertEqual([m["id"] for m in cue["party"]], ["brannoc", "ilsevel", "tamsin", "oriel"])
        b = cue["party"][0]
        self.assertEqual((b["level_before"], b["level"], b["xp"], b["next_at"]), (1, 2, 300, 900))
        self.assertGreater(cue["duration"], 6)
        quiet = resolve(self.plan("C01-E006", "C01-E013"), self.sheets, self.world, "C01-E013-1")
        self.assertIsNone(progress_cue("C01-E013", quiet, self.sheets))          # nothing changed, not a 3rd episode
        self.assertIsNotNone(progress_cue("C01-E012", quiet, self.sheets))      # every 3rd episode anyway
        self.assertIsNone(progress_cue("C01-E009", res, self.sheets))           # never in the episodes already made

    def test_camp_night_food_watches_and_unlight(self):
        from pqc.pipeline.resolve import resolve
        world = copy.deepcopy(self.world)
        world["location"]["unlight"] = "deep"
        p = self.plan("C01-E006", "C01-E016")
        rest = next(x for x in p["state_proposals"] if x["type"] == "rest")
        rest["camp"] = {"site": "wild", "watches": [["brannoc"], ["tamsin", "oriel"], ["ilsevel"]], "lantern_lit": False}
        res = resolve(p, self.sheets, world, "C01-E016-1")
        night = res.outcomes["nights"][0]
        self.assertEqual(night["watches"][1], ["tamsin", "oriel"])
        self.assertEqual(len(night["unlight"]), 4)                              # everyone saves; some may fail
        self.assertEqual(night["food"]["meals_each"], 1)
        rations = lambda sh: sum(i["qty"] for s in sh.values() for i in s.get("inventory", []) if i["id"] == "rations")
        self.assertEqual(rations(res.sheets_after), max(0, rations(self.sheets) - 4))
        saves = [r for r in res.episode["rolls"] if "Unlight" in r.get("purpose", "")]
        self.assertEqual(len(saves), 4)                                           # in the episode's public dice log

    def test_travel_and_short_rest(self):
        from pqc.pipeline.resolve import resolve
        p = self.plan("C01-E006", "C01-E017", state_proposals=[
            {"type": "travel", "days": 3, "to": "loc.waystation-nine"}, {"type": "rest", "kind": "short"}])
        sheets = copy.deepcopy(self.sheets)
        sheets["tamsin"]["hp"]["current"] = 2
        res = resolve(p, sheets, self.world, "C01-E017-1")
        trip, short = res.outcomes["nights"]
        self.assertEqual(trip["days"], 3)
        self.assertEqual(res.world_after["location"]["id"], "loc.waystation-nine")
        self.assertEqual(res.world_after["clock"]["day"], (self.world["clock"]["day"] + 3 - 1) % 30 + 1)
        self.assertEqual(short["kind"], "short")

    def test_surprise_from_the_watch(self):
        from pqc.combat import Encounter
        from pqc.dice import Dice
        from pqc.pipeline.resolve import _surprised
        enc = {"party_at": {"brannoc": [0, 0]}, "enemies": [{"id": "wolf-1"}], "surprise": {"party": "c1.failure",
                                                                                         "enemies": "c1.success"}}
        self.assertEqual(_surprised(enc, {"c1": "failure"}, {}), ["brannoc"])
        self.assertEqual(_surprised(enc, {"c1": "success"}, {}), ["wolf-1"])
        from helpers import mon, pc
        b, w = pc("brannoc"), mon("wolf", "wolf-1", pos=(5, 5))
        e = Encounter([b, w], Dice("SURPRISE"), options={"surprised": ["brannoc"]})
        e.start()
        roll = next(r for r in e.dice.export_log() if r["actor"] == "brannoc")
        self.assertIn("surprised", roll["purpose"])
        self.assertEqual(roll.get("advantage"), "disadvantage")

    def test_memories_from_the_archive(self):
        from pqc.pipeline import memories, wiki
        mem = memories.collect(wiki.load_archive(), self.world, before="C01-E011")
        text = "\n".join(mem["brannoc"])
        self.assertIn("C01-E009", text)
        self.assertTrue(any("went down" in x for x in mem["tamsin"]))
        self.assertTrue(all(x[:8] <= "C01-E010" for items in mem.values() for x in items))
        self.assertEqual(memories.collect(wiki.load_archive(), self.world, before="C01-E001"),
                         {c: [] for c in memories.PARTY})
