"""Renderer tests. Skipped when the asset pack hasn't been fetched."""
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT  # noqa: F401  (sets sys.path)

PACK = ROOT / "vendor" / "ninja-adventure" / "LICENSE.txt"
HAVE_PACK = PACK.exists()
HAVE_FFMPEG = shutil.which("ffmpeg") is not None


class TestAutotileLogic(unittest.TestCase):
    """Pure logic: no assets needed."""

    def test_quarter_sources(self):
        from pqc.render.tilemap import CENTER, INNER, OUTER, quarter_source
        self.assertEqual(quarter_source("tl", True, True, True), CENTER)
        self.assertEqual(quarter_source("tl", True, True, False), INNER["tl"])
        self.assertEqual(quarter_source("br", False, False, True), OUTER["br"])
        self.assertEqual(quarter_source("tr", True, False, True), (2, 1))   # right edge
        self.assertEqual(quarter_source("bl", False, True, True), (1, 2))   # bottom edge

    def test_tile_to_px(self):
        from pqc.render.stage import tile_to_px
        self.assertEqual(tile_to_px(2, 3), (40.0, 64.0))

    def test_lighting_presets(self):
        import numpy as np
        from pqc.render import lighting
        frame = np.full((10, 10, 3), 200, dtype=np.uint8)
        self.assertTrue((lighting.apply(frame, "day", [], []) == frame).all())
        night = lighting.apply(frame, "night", [], [])
        self.assertLess(night.mean(), frame.mean())
        lit = lighting.apply(frame, "night", [lighting.Light(5, 5, 6, 1.0)], [])
        self.assertGreater(lit[5, 5].mean(), night[5, 5].mean())
        grey = lighting.apply(np.dstack([np.full((10, 10), 200), np.full((10, 10), 40), np.full((10, 10), 40)]).astype(np.uint8),
                              "day", [], [lighting.UnlightZone(5, 5, 50, 1.0)])
        self.assertLess(int(grey[5, 5].max()) - int(grey[5, 5].min()), 30)

    def test_text_wrap(self):
        class F:
            def getlength(self, s):
                return len(s) * 6
        from pqc.render.ui import wrap
        self.assertEqual(wrap("one two three four", F(), 60), ["one two", "three four"])

    def test_blip_audio(self):
        from pqc.render.audio import blip
        b = blip(260, 0)
        self.assertEqual(b.shape[1], 2)
        self.assertLessEqual(float(abs(b).max()), 0.08)


@unittest.skipUnless(HAVE_PACK, "asset pack not fetched (run scripts/fetch_assets.sh)")
class TestAssets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pqc.render.assets import Assets
        cls.a = Assets()

    def test_manifest_files_exist(self):
        self.assertEqual(self.a.missing_files(), [])

    def test_licence_is_cc0(self):
        self.assertIn("CC0 1.0 Universal", PACK.read_text())

    def test_party_and_monsters_load(self):
        for aid in ("brannoc", "ilsevel", "tamsin", "oriel", "goblin_warrior", "goblin_minion", "wolf", "skeleton"):
            s = self.a.actor(aid)
            self.assertEqual(len(s.walk["down"]), 4, aid)
            self.assertIsNotNone(s.faceset, aid)

    def test_recolour_changes_pixels(self):
        from pqc.render.assets import recolor
        base = self.a.image("Actor/Character/SorcererOrange/SpriteSheet.png")
        spec = self.a.manifest["actors"]["ilsevel"]
        self.assertNotEqual(recolor(base, spec["recolor"]).tobytes(), base.tobytes())

    def test_every_spell_has_fx(self):
        from pqc import data
        sf = self.a.manifest["spell_fx"]
        for name in ("fire_bolt", "magic_missile", "cure_wounds", "healing_word", "bless", "guiding_bolt", "sacred_flame"):
            self.assertIn(name, sf)
        for spec in sf.values():
            if isinstance(spec, dict):
                for key in ("impact", "projectile"):
                    if spec.get(key):
                        self.assertTrue(self.a.fx(spec[key]), spec[key])
        self.assertTrue(set(data.spells()) - set(sf) <= set(data.spells()))  # unknown spells fall back to _default

    def test_maps_validate_and_render(self):
        from pqc.render.tilemap import TileMap
        from pqc.schema import validate_named
        for p in (ROOT / "assets" / "maps").glob("*.json"):
            d = json.loads(p.read_text())
            self.assertEqual(validate_named(d, "map"), [], p.name)
            tm = TileMap.from_dict(d, self.a)
            self.assertEqual(tm.ground.size, (d["size"][0] * 16, d["size"][1] * 16))
            from pqc.pipeline.resolve import blocked_squares
            blocked = blocked_squares(d["id"])
            for name, xy in d.get("points", {}).items():  # named marks must be standable
                self.assertNotIn(tuple(xy), blocked, f"{p.name}: point {name}")


@unittest.skipUnless(HAVE_PACK, "asset pack not fetched")
class TestThirdPartyArt(unittest.TestCase):
    """Kenney, Dungeon Crawl and Painterly art imported by scripts/import_art.py."""

    @classmethod
    def setUpClass(cls):
        from pqc.render.assets import Assets
        cls.a = Assets()

    def test_licences_sit_beside_the_art(self):
        tp = ROOT / "assets" / "thirdparty"
        self.assertIn("Creative Commons Zero", (tp / "kenney_roguelike" / "License.txt").read_text())
        self.assertIn("CC0", (tp / "dcss" / "LICENSE.txt").read_text())
        self.assertIn("CC-BY 3.0", (tp / "painterly" / "README.txt").read_text())
        self.assertIn("J. W. Bjerk", (ROOT / "assets" / "CREDITS.md").read_text())

    def test_outline_matches_the_pack(self):
        from pqc.render.assets import INK, outline
        from PIL import Image
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        img.paste((200, 100, 50, 255), (5, 5, 11, 11))
        out = outline(img)
        self.assertEqual(out.getpixel((4, 7))[:3], INK)          # ring outside the shape
        self.assertEqual(out.getpixel((7, 7))[:3], (200, 100, 50))  # inside untouched
        self.assertEqual(out.getpixel((0, 0))[3], 0)
        k = self.a.prop("royal_banner")
        self.assertEqual(k.size, (16, 48))
        raw = self.a.image(self.a.prop_spec("royal_banner")["sheet"]).crop((50 * 16, 0, 51 * 16, 48))
        self.assertNotEqual(k.tobytes(), raw.tobytes())

    def test_animated_props(self):
        for pid, n in (("campfire_lit", 8), ("barn_ablaze", 8), ("wall_torch", 4), ("standing_torch", 2)):
            frames, fps = self.a.prop_frames(pid)
            self.assertEqual(len(frames), n, pid)
            self.assertTrue(fps > 0)
            self.assertEqual(frames[0].size, self.a.prop(pid).size, pid)
            self.assertGreater(len({f.tobytes() for f in frames}), 1, pid)
        for pid in ("campfire", "barn_burning", "stone_lantern"):   # the props released episodes use are still
            self.assertIsNone(self.a.prop_frames(pid), pid)

    def test_prop_instance_frames_and_dead_lanterns(self):
        from pqc.render.tilemap import TileMap
        d = {"id": "t", "size": [6, 4], "props": [{"prop": "campfire_lit", "at": [0, 0]},
                                                   {"prop": "lantern_post", "at": [3, 0], "id": "l"},
                                                   {"prop": "barrel", "at": [5, 0]}]}
        tm = TileMap.from_dict(d, self.a)
        fire, post, barrel = tm.props
        self.assertNotEqual(fire.frame(0.0).tobytes(), fire.frame(0.1).tobytes())
        self.assertIs(barrel.frame(3.0), barrel.image)
        self.assertEqual(post.light, "lit")
        lit = post.frame(1.0)
        post.light = "dead"
        self.assertEqual(post.frame(1.0).tobytes(), self.a.prop("lantern_post_dead").tobytes())
        self.assertNotEqual(lit.tobytes(), post.frame(1.0).tobytes())

    def test_card_art(self):
        for aid in ("item:lantern_lit", "item:lantern_dead", "item:black_glass_pendant", "item:crystal_pendant",
                    "creature:goblin", "creature:wolf", "creature:worg", "creature:zombie", "spell:fire_bolt"):
            img = self.a.art(aid)
            self.assertIsNotNone(img.getbbox(), aid)
        self.assertEqual(self.a.spell_icon("cure_wounds").size, (64, 64))
        self.assertEqual(self.a.spell_icon("no_such_spell").tobytes(), self.a.art("spell:_default").tobytes())
        for spell in self.a.manifest["spell_fx"]:                 # every spell the show animates has an icon
            if not spell.startswith("_"):
                self.assertIn(spell, self.a.art_ids("spell"), spell)


@unittest.skipUnless(HAVE_PACK, "asset pack not fetched")
class TestTimeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        import make_gate_scene
        from pqc.render.assets import Assets
        cls.a = Assets()
        cls.tl = make_gate_scene.timeline()

    def test_gate_timeline_valid_and_reasonable_length(self):
        from pqc.render.timeline import Runner
        from pqc.schema import validate_named
        self.assertEqual(validate_named(self.tl, "timeline"), [])
        dur = Runner(self.tl, self.a).duration()
        self.assertGreater(dur, 60)
        self.assertLess(dur, 200)

    def test_director_uses_logged_rolls(self):
        import make_gate_scene
        result, _ = make_gate_scene.fight()
        logged = {r["id"]: r for r in result["rolls"]}
        attacks = [c for c in self.tl["cues"] if c["op"] == "battle_attack"]
        self.assertTrue(attacks)
        for c in attacks:
            self.assertEqual(c["roll"], logged[c["roll"]["id"]])
            self.assertIn(str(c["roll"]["total"]), c["line"])
        self.assertTrue(any(c["op"] == "battle_end" for c in self.tl["cues"]))

    def test_rendering_is_deterministic(self):
        from pqc.render.timeline import Runner
        short = {**self.tl, "cues": self.tl["cues"][:12]}

        def digest():
            h = hashlib.sha256()
            for i, f in enumerate(Runner(short, self.a).frames()):
                if i % 15 == 0:
                    h.update(f.tobytes())
                if i > 150:
                    break
            return h.hexdigest()

        self.assertEqual(digest(), digest())

    def test_frame_size(self):
        from pqc.render.timeline import Runner
        f = next(iter(Runner({**self.tl, "cues": self.tl["cues"][:3]}, self.a).frames()))
        self.assertEqual(f.size, (480, 270))

    def test_audio_events_reference_known_ids(self):
        from pqc.render.timeline import Runner
        r = Runner(self.tl, self.a)
        r.duration()
        for e in r.stage.audio:
            if e["type"] == "sfx":
                self.assertIn(e["id"], self.a.manifest["sfx"])
            if e["type"] == "music":
                self.assertIn(e["id"], self.a.manifest["music"])

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
    def test_short_mp4_render(self):
        from pqc.render.video import render
        short = {**self.tl, "cues": self.tl["cues"][:9], "tail": 0.2}
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "clip.mp4"
            info = render(short, out, assets=self.a, scale=2, preset="ultrafast", log=lambda *_: None)
            self.assertTrue(out.exists())
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
                                    "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout
            self.assertIn("video,960,540", probe)
            self.assertIn("audio", probe)
            self.assertGreater(info["frames"], 30)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE_PACK, "asset pack not fetched")
class TestProgressCard(unittest.TestCase):
    def test_card_draws_and_levels_up(self):
        from pqc.render.assets import Assets
        from pqc.render.timeline import Runner
        from pqc.schema import validate_named
        m = {"id": "brannoc", "name": "Brannoc", "title": "Dwarf Fighter", "level_before": 1, "level": 2,
             "xp_before": 278, "xp": 300, "from_start": 0, "from_next": 300, "level_start": 300, "next_at": 900,
             "new": ["Action Surge", "Tactical Mind"]}
        card = {"op": "progress", "title": "The party", "subtitle": "After Episode 15", "party": [m], "duration": 3.0}
        tl = {"schema": "pqc/timeline@1", "id": "t", "title": "t", "fps": 30, "seed": "s", "tail": 0.1,
              "cues": [{"op": "scene", "map": "brindle_cross", "time_of_day": "day", "camera": [19, 11]},
                       {"op": "wait", "seconds": 0.3}, card]}
        self.assertEqual(validate_named(tl, "timeline"), [])
        frames = list(Runner(tl, Assets()).frames())
        before, during = frames[3], frames[int(0.3 * 30) + 75]
        self.assertGreater(sum(abs(a - b) for a, b in zip(before.convert("L").getdata(), during.convert("L").getdata())),
                           100000)
        r = Runner(tl, Assets())
        list(r.frames())
        self.assertTrue(any(e.get("id") == "level_up" for e in r.stage.audio))


@unittest.skipUnless(HAVE_PACK, "asset pack not fetched")
class TestDialogPages(unittest.TestCase):
    """A line too long for the dialog box (3 lines with a portrait, 4 without) goes on to a second
    page within the same time on screen, instead of losing its last words."""

    LONG = ("I will go. Inspecting those lanterns is the task the Order gave me, and the ledger for "
            "Thirty-Seven is wrong. I intend to know why.")

    @classmethod
    def setUpClass(cls):
        from pqc.render.assets import Assets
        from pqc.render.ui import UI
        cls.a = Assets()
        cls.ui = UI(cls.a)

    @staticmethod
    def _boxes(tl, assets):
        """Every dialog box of a timeline as the renderer lays it out: {start: DialogState}."""
        from pqc.render.timeline import Runner
        r, boxes = Runner(tl, assets), {}
        for _ in r.frames(render=False):
            ds = r.stage.ui.dialog
            if ds is not None:
                boxes.setdefault(ds.t0, ds)
        return r, boxes

    def test_pages_keep_every_word_and_fit_the_box(self):
        from pqc.render.ui import paginate, wrap
        texts = [c["text"] for p in sorted((ROOT / "episodes").glob("C??-E???/timeline.json"))
                 for c in json.loads(p.read_text())["cues"] if c["op"] in ("say", "narrate")]
        texts += [self.LONG, "Short.", "word " * 120, "No. " + "a very long sentence without a stop " * 6]
        for text in texts:
            for width, max_lines in ((236, 3), (448, 4)):
                pages = paginate(text, self.ui.f_text, width, max_lines)
                self.assertEqual(" ".join(w for p in pages for l in p for w in l.split()), " ".join(text.split()))
                self.assertTrue(all(0 < len(p) <= max_lines for p in pages), (text, pages))
                if len(wrap(text, self.ui.f_text, width)) <= max_lines:
                    self.assertEqual(pages, [wrap(text, self.ui.f_text, width)])   # boxes that fit are unchanged

    def test_long_line_turns_the_page_at_a_sentence(self):
        face = self.a.actor("ilsevel").faceset
        ds = self.ui.make_dialog("say", "ilsevel", "Ilsevel", self.LONG, 0.0, 22.0, face)
        self.assertEqual(len(ds.pages), 2)
        self.assertTrue(ds.pages[0][-1].endswith("is wrong."))
        self.assertEqual(ds.pages[1], ["I intend to know why."])

    def test_paged_box_keeps_its_time_and_shows_the_end(self):
        from pqc.render.timeline import HOLD_BASE, HOLD_PER_CHAR, TYPE_CPS
        tl = {"schema": "pqc/timeline@1", "id": "t", "title": "t", "fps": 30, "seed": "s", "tail": 0.0,
              "cues": [{"op": "scene", "map": "brindle_cross", "time_of_day": "day", "camera": [19, 11]},
                       {"op": "say", "speaker": "ilsevel", "text": self.LONG}]}
        r, boxes = self._boxes(tl, self.a)
        (ds,) = boxes.values()
        n = ds.total_chars
        self.assertEqual(n, sum(len(l) for l in ds.lines))           # timing from the unpaged wrap
        dur = n / TYPE_CPS + HOLD_BASE + HOLD_PER_CHAR * n
        self.assertAlmostEqual(r.stage.t - r.cue_times[1], dur, delta=1.5 / 30)
        first, last = ds.page_starts[1] - ds.page_chars()[0] / TYPE_CPS, dur - ds.page_starts[1] - ds.page_chars()[1] / TYPE_CPS
        self.assertGreater(first, 1.5)                                   # page 1 stays up to be read
        self.assertGreater(last, HOLD_BASE)                              # and so does the end of the line
        self.assertEqual(ds.page_at(ds.t0 + dur - 0.05), (1, ds.page_chars()[1]))
        blips = [e for e in r.stage.audio if e.get("type") == "blip"]
        self.assertEqual(len(blips), sum((k + 1) // 2 for k in ds.page_chars()))

    def test_episodes_made_before_pages_are_re_rendered_where_they_change(self):
        """Episodes rendered before dialog pages existed carry a render revision (so the release run
        re-renders them) exactly where one of their boxes now turns a page."""
        revs = json.loads((ROOT / "production" / "render_revisions.json").read_text())["episodes"]
        for p in sorted((ROOT / "episodes").glob("C01-E0*/timeline.json")):
            eid = p.parent.name
            if eid > "C01-E010":
                continue
            _, boxes = self._boxes(json.loads(p.read_text()), self.a)
            paged = any(len(ds.pages) > 1 for ds in boxes.values())
            self.assertEqual("dialog-pages" in revs.get(eid, []), paged, eid)
