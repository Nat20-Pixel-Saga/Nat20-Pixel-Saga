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
