"""Timeline cues -> frames.

A timeline is a list of cues (see ``schemas/timeline.schema.json``). Each cue
becomes a task. Blocking cues (the default for most) advance time until they
finish; cues with ``"wait": false`` run alongside whatever comes next.

    runner = Runner(timeline, assets)
    for frame in runner.frames(): ...      # PIL RGB 480x270 images
    runner.stage.audio                     # timed audio events for the mixer
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterator

from PIL import Image

from .assets import Assets
from .stage import Fx, Projectile, Stage, tile_to_px
from .tilemap import T

# Reading pace. Text types out at TYPE_CPS, then stays up long enough to be
# read comfortably: HOLD_BASE + HOLD_PER_CHAR per character (about 5.5 s for a
# 60-character line in total). Timelines can override with "reading": {...}.
TYPE_CPS = 22.0
HOLD_BASE = 1.6
HOLD_PER_CHAR = 0.03


class Task:
    blocking = True

    def __init__(self, cue: dict):
        self.cue = cue
        self.t0 = 0.0
        if "wait" in cue:
            self.blocking = bool(cue["wait"])

    def start(self, st: Stage):
        self.t0 = st.t

    def update(self, st: Stage) -> bool:
        return True

    def elapsed(self, st: Stage) -> float:
        return st.t - self.t0


# ------------------------------------------------------------- world cues
class SceneTask(Task):
    def start(self, st):
        super().start(st)
        c = self.cue
        st.set_map(c["map"])
        st.actors.clear()
        st.unlight.clear()
        st.preset = c.get("time_of_day", "day")
        st.preset_blend = 1.0
        if "camera" in c:
            x, y = tile_to_px(*c["camera"])
            st.camera = [x, y - 8]
        st.follow = c.get("follow")


class SpawnTask(Task):
    def start(self, st):
        super().start(st)
        c = self.cue
        st.spawn(c["actor"], c.get("sprite", c["actor"]), *c["at"], facing=c.get("facing", "down"),
                 name=c.get("name", ""))


class DespawnTask(Task):
    def start(self, st):
        super().start(st)
        st.actors.pop(self.cue["actor"], None)


class FaceTask(Task):
    def start(self, st):
        super().start(st)
        st.actors[self.cue["actor"]].facing = self.cue["facing"]


class MoveTask(Task):
    def start(self, st):
        super().start(st)
        a = st.actors[self.cue["actor"]]
        self.speed = self.cue.get("speed", 4.0) * T  # px / s
        self.points = [tile_to_px(*p) for p in self.cue["path"]]
        self.i = 0
        a.state = "walk"

    def update(self, st):
        a = st.actors[self.cue["actor"]]
        dt = 1.0 / st.fps
        a.anim_t += dt
        step = self.speed * dt
        while step > 0 and self.i < len(self.points):
            tx, ty = self.points[self.i]
            dx, dy = tx - a.x, ty - a.y
            dist = math.hypot(dx, dy)
            if dist > 0.01:
                a.facing = ("right" if dx > 0 else "left") if abs(dx) > abs(dy) else ("down" if dy > 0 else "up")
            if dist <= step:
                a.x, a.y = tx, ty
                step -= dist
                self.i += 1
            else:
                a.x += dx / dist * step
                a.y += dy / dist * step
                step = 0
        if self.i >= len(self.points):
            a.state = "idle"
            if "face" in self.cue:
                a.facing = self.cue["face"]
            return True
        return False


class CameraTask(Task):
    def start(self, st):
        super().start(st)
        c = self.cue
        if "follow" in c:
            st.follow = c["follow"]
            st.camera_tween = None
            return
        st.follow = None
        x, y = tile_to_px(*c["to"])
        st.camera_tween = {"t0": st.t, "dur": c.get("duration", 1.0), "x0": st.camera[0], "y0": st.camera[1],
                           "x1": x, "y1": y - 8}

    def update(self, st):
        return "follow" in self.cue or self.elapsed(st) >= self.cue.get("duration", 1.0)


class SayTask(Task):
    def start(self, st):
        super().start(st)
        c = self.cue
        speaker = c.get("speaker")
        face = None
        name = c.get("name")
        pitch = 240
        if speaker:
            if c.get("sprite"):
                spr = st.a.actor(c["sprite"])
            elif speaker in st.actors:      # on stage: use the sprite it was spawned with (e.g. goblin-1)
                spr = st.actors[speaker].sprites
            else:
                spr = st.a.actor(speaker)
            face = spr.faceset
            pitch = spr.voice_pitch
            name = name or (st.actors[speaker].name if speaker in st.actors else speaker).split(" ")[0].capitalize()
        kind = "say" if c["op"] == "say" else "narrate"
        pace = getattr(st, "reading", {})
        cps = c.get("cps", pace.get("cps", TYPE_CPS))
        ds = st.ui.make_dialog(kind, speaker, name, c["text"], st.t, cps, face if kind == "say" else None)
        st.ui.dialog = ds
        self.type_time = ds.total_chars / ds.cps
        hold_base, hold_per_char = pace.get("hold_base", HOLD_BASE), pace.get("hold_per_char", HOLD_PER_CHAR)
        self.dur = c.get("duration", self.type_time + hold_base + hold_per_char * ds.total_chars)
        # A line too long for the box goes on to a second page within the same time on screen.
        ds.schedule(self.dur, hold_base, hold_per_char)
        # Typewriter blips: one every 2 visible characters (silent for narration).
        if kind == "say":
            for start, n in zip(ds.page_starts, ds.page_chars()):
                for k in range(0, n, 2):
                    st.audio.append({"type": "blip", "t": st.t + start + k / ds.cps, "pitch": pitch})
        if speaker and c.get("emote") and speaker in st.actors:
            a = st.actors[speaker]
            a.emote = st.a.emote(c["emote"])
            a.emote_until = st.t + min(self.dur, 1.6)

    def update(self, st):
        if self.elapsed(st) >= self.dur:
            if st.ui.dialog and st.ui.dialog.t0 == self.t0:
                st.ui.dialog = None
            return True
        return False


class DmIntroTask(Task):
    """The Storyteller's opening: a parchment panel over the dimmed scene with
    the episode title, campaign/level/date line and a short framing paragraph."""

    def start(self, st):
        super().start(st)
        from .ui import wrap
        c = self.cue
        pace = getattr(st, "reading", {})
        cps = c.get("cps", pace.get("cps", TYPE_CPS))
        lines = wrap(c["text"], st.ui.f_text, 480 - 88 - 36)
        n = sum(len(l) for l in lines)
        self.dur = c.get("duration", 0.5 + n / cps + 2.5 + 0.015 * n)
        st.ui.dm = {"title": c.get("title", ""), "subtitle": c.get("subtitle", ""), "lines": lines[:10],
                    "t0": st.t, "dur": self.dur, "cps": cps}
        st.sfx("transition", volume=0.6)

    def update(self, st):
        return self.elapsed(st) >= self.dur


class EmoteTask(Task):
    blocking = False

    def start(self, st):
        super().start(st)
        a = st.actors[self.cue["actor"]]
        a.emote = st.a.emote(self.cue["emote"])
        a.emote_until = st.t + self.cue.get("duration", 1.2)
        if self.cue.get("sfx"):
            st.sfx(self.cue["sfx"])

    def update(self, st):
        return (not self.blocking) or self.elapsed(st) >= self.cue.get("duration", 1.2)


class WaitTask(Task):
    def update(self, st):
        return self.elapsed(st) >= self.cue["seconds"]


class LocationCardTask(Task):
    blocking = False

    def start(self, st):
        super().start(st)
        st.ui.card = {"text": self.cue["text"], "t0": st.t, "dur": self.cue.get("duration", 2.6)}

    def update(self, st):
        return (not self.blocking) or self.elapsed(st) >= self.cue.get("duration", 2.6)


class TitleTask(Task):
    def start(self, st):
        super().start(st)
        st.ui.title = {"lines": self.cue["lines"], "t0": st.t, "dur": self.cue.get("duration", 3.0),
                       "backdrop": self.cue.get("backdrop", True)}

    def update(self, st):
        return self.elapsed(st) >= self.cue.get("duration", 3.0)


class ProgressTask(Task):
    """The party's levels and XP before the outro (pqc/pipeline/assemble.progress_cue)."""

    def start(self, st):
        super().start(st)
        c = self.cue
        up = any(m["level"] > m["level_before"] for m in c["party"])
        self.dur = c.get("duration", 7.5 if up else 5.5)
        faces = {}
        for m in c["party"]:
            try:
                faces[m["id"]] = st.a.actor(m["id"]).faceset
            except Exception:
                faces[m["id"]] = None
        st.ui.progress = {**c, "t0": st.t, "dur": self.dur, "faces": faces}
        st.ui.dialog = None
        if up:
            st.sfx("level_up", st.t + 2.0)

    def update(self, st):
        return self.elapsed(st) >= self.dur


class LanternTask(Task):
    """Change a lantern's light. ``dead`` lanterns can spawn an Unlight zone."""

    def start(self, st):
        super().start(st)
        c = self.cue
        p = st.map.prop_by_id(c["id"])
        self.p = p
        self.final = c["state"]
        self.flicker_for = c.get("flicker", 1.6 if c["state"] == "dead" else 0.0)
        if self.flicker_for > 0:
            p.light = "flicker"
        else:
            p.light = self.final
        if c.get("sfx", True) and c["state"] == "dead":
            st.sfx("lantern_out", st.t + self.flicker_for * 0.8)
        self.zone_added = False

    def update(self, st):
        c = self.cue
        if self.elapsed(st) >= self.flicker_for:
            self.p.light = self.final
            if self.final == "dead" and c.get("unlight") and not self.zone_added:
                cx, cy = self.p.light_center()
                st.unlight.append({"x": cx, "y": cy, "radius": c["unlight"].get("radius", 60) , "t0": st.t,
                                   "grow": c["unlight"].get("grow", 2.5), "strength": c["unlight"].get("strength", 0.85)})
                self.zone_added = True
            return self.elapsed(st) >= self.flicker_for + c.get("hold", 0.0)
        return False


class TimeOfDayTask(Task):
    def start(self, st):
        super().start(st)
        st.preset = self.cue["preset"]
        st.preset_blend = 0.0 if self.cue.get("duration", 0) > 0 else 1.0

    def update(self, st):
        d = self.cue.get("duration", 0)
        st.preset_blend = 1.0 if d <= 0 else min(1.0, self.elapsed(st) / d)
        return st.preset_blend >= 1.0


class MusicTask(Task):
    blocking = False

    def start(self, st):
        super().start(st)
        c = self.cue
        if c["op"] == "music":
            st.audio.append({"type": "music", "id": c["track"], "t": st.t, "fade_in": c.get("fade_in", 0.5),
                             "volume": c.get("volume", 0.55)})
        else:
            st.audio.append({"type": "music_stop", "t": st.t, "fade_out": c.get("fade_out", 1.0)})


class SfxTask(Task):
    blocking = False

    def start(self, st):
        super().start(st)
        st.sfx(self.cue["id"], volume=self.cue.get("volume", 1.0))


class FadeTask(Task):
    def start(self, st):
        super().start(st)
        if "from" in self.cue:
            st.fade = 1.0 if self.cue["from"] == "black" else 0.0
        self.f0 = st.fade
        self.f1 = 1.0 if self.cue.get("to", "black") == "black" else 0.0

    def update(self, st):
        d = self.cue.get("duration", 1.0)
        p = min(1.0, self.elapsed(st) / max(d, 1e-6))
        st.fade = self.f0 + (self.f1 - self.f0) * p
        return p >= 1.0


# ------------------------------------------------------------ battle cues
class BattleStartTask(Task):
    """Start a fight. With positions (``at``) it happens on the current map with
    a grid; otherwise it wipes to the side-view arena."""

    DUR = 0.9

    def start(self, st):
        super().start(st)
        c = self.cue
        self.on_map = st.map is not None and all("at" in x for x in c["party"] + c["enemies"]) and not c.get("arena")
        st.sfx("transition")
        if self.on_map:
            st.start_battle(c["party"], c["enemies"], on_map=True)
            st.ui.banner = {"text": c.get("banner", "Roll for initiative!"), "t0": st.t, "dur": 1.6}
            self.dur = 0.8
        else:
            st.wipe = {"t0": st.t, "dur": self.DUR}
            self.dur = self.DUR
        if c.get("music"):
            st.audio.append({"type": "music", "id": c["music"], "t": st.t + (0.1 if self.on_map else self.DUR / 2),
                             "fade_in": 0.1, "volume": 0.5})
        self.switched = self.on_map

    def update(self, st):
        if not self.switched and self.elapsed(st) >= self.DUR / 2:
            st.start_battle(self.cue["party"], self.cue["enemies"], on_map=False)
            self.switched = True
        if self.elapsed(st) >= self.dur:
            st.wipe = None
            return True
        return False


class InitiativeTask(Task):
    """Show the initiative order (rolled by the engine) for a moment."""

    def start(self, st):
        super().start(st)
        self.dur = self.cue.get("duration", 3.0)
        st.ui.initiative = {"order": self.cue["order"], "t0": st.t, "dur": self.dur}
        st.sfx("dice_roll")

    def update(self, st):
        return self.elapsed(st) >= self.dur


class BattleTurnTask(Task):
    """Mark whose turn it is: pulsing square on the grid plus a short banner."""

    def start(self, st):
        super().start(st)
        c = self.cue
        if st.battle:
            st.battle.active = c["actor"]
        name = st.battle.names.get(c["actor"], c["actor"]) if st.battle else c["actor"]
        st.ui.banner = {"text": f"Round {c.get('round', 1)}  -  {name}", "t0": st.t, "dur": c.get("duration", 1.0)}
        self.dur = c.get("hold", 0.45)

    def update(self, st):
        return self.elapsed(st) >= self.dur


class BattleMoveTask(Task):
    """Walk a creature along its engine path, square by square."""

    def start(self, st):
        super().start(st)
        a = st.actors[self.cue["actor"]]
        self.points = [tile_to_px(*p) for p in self.cue["path"][1:]] or [tile_to_px(*self.cue["path"][0])]
        self.speed = self.cue.get("speed", 5.0) * T
        self.i = 0
        a.state = "walk"

    def update(self, st):
        a = st.actors[self.cue["actor"]]
        dt = 1.0 / st.fps
        a.anim_t += dt
        step = self.speed * dt
        while step > 0 and self.i < len(self.points):
            tx, ty = self.points[self.i]
            dx, dy = tx - a.x, ty - a.y
            dist = math.hypot(dx, dy)
            if dist > 0.01:
                a.facing = ("right" if dx > 0 else "left") if abs(dx) > abs(dy) else ("down" if dy > 0 else "up")
            if dist <= step:
                a.x, a.y = tx, ty
                step -= dist
                self.i += 1
            else:
                a.x += dx / dist * step
                a.y += dy / dist * step
                step = 0
        if self.i >= len(self.points):
            a.state = "idle"
            return True
        return False


class BattleEndTask(Task):
    DUR = 0.9

    def start(self, st):
        super().start(st)
        self.on_map = bool(st.battle and st.battle.arena is None)
        if self.cue.get("result", "victory") == "victory":
            st.audio.append({"type": "music_stop", "t": st.t, "fade_out": 0.3})
            st.sfx("victory")
            st.ui.banner = {"text": self.cue.get("banner", f"Victory!  +{self.cue.get('xp', 0)} XP"), "t0": st.t,
                            "dur": self.cue.get("hold", 2.4), "font": self.cue.get("banner_font")}
        if st.battle:
            st.battle.active = None
            st.battle.grid_target = 0.0
        self.hold = self.cue.get("hold", 2.4)
        self.switched = False

    def update(self, st):
        e = self.elapsed(st)
        if self.on_map:
            if e >= self.hold:
                st.end_battle()
                return True
            return False
        if e >= self.hold and st.wipe is None and not self.switched:
            st.wipe = {"t0": st.t, "dur": self.DUR}
        if st.wipe and not self.switched and st.t - st.wipe["t0"] >= self.DUR / 2:
            st.end_battle()
            self.switched = True
        if self.switched and st.wipe and st.t - st.wipe["t0"] >= self.DUR:
            st.wipe = None
            return True
        return False


def _facing(a, tg) -> str:
    dx, dy = tg.x - a.x, tg.y - a.y
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"


def _center(st: Stage, aid: str) -> tuple[float, float]:
    a = st.actors[aid]
    return a.x + a.dx, a.y - a.sprites.size[1] / 2


def _popup(st: Stage, aid: str, text: str, color, t: float, big=False):
    from .stage import ZOOM
    x, y = _center(st, aid)
    cx, cy = st._camera()
    st.ui.popups.append({"text": text, "x": (x - cx) * ZOOM, "y": (y - 12 - cy) * ZOOM, "t0": t, "dur": 1.1, "color": color, "big": big})


def _apply_hp(st: Stage, aid: str, hp_after):
    if hp_after is not None and st.battle and aid in st.battle.hp:
        st.battle.hp[aid][0] = max(0, int(hp_after))


class BattleAttackTask(Task):
    """Melee or ranged attack with the dice tray. Cue fields: actor, target,
    roll (logged roll dict), hit, critical, damage, hp_after, ranged, label, line."""

    SPIN = 0.7
    IMPACT = 1.0
    DUR = 2.0

    def start(self, st):
        super().start(st)
        c = self.cue
        self.a = st.actors[c["actor"]]
        self.tg = st.actors[c["target"]]
        self.ranged = c.get("ranged", False)
        roll = c.get("roll") or {}
        st.ui.dice.append({"roll": roll, "t0": st.t, "dur": self.DUR + 0.3, "spin": self.SPIN,
                           "label": c.get("label", ""), "line": c.get("line", "")})
        st.sfx("dice_roll")
        st.sfx("dice_land", st.t + self.SPIN)
        if roll.get("critical"):
            st.sfx("nat20", st.t + self.SPIN + 0.05)
        elif roll.get("natural") == 1:
            st.sfx("nat1", st.t + self.SPIN + 0.05)
        self.home = (self.a.x, self.a.y)
        self.done_impact = False
        if self.ranged:
            ax, ay = _center(st, c["actor"])
            tx, ty = _center(st, c["target"])
            st.projectiles.append(Projectile(st.a.fx(c.get("projectile", "proj_arrow")), ax, ay, tx, ty,
                                             self.t0 + self.IMPACT - 0.25, 0.25, arc=6))
            st.sfx("arrow", self.t0 + self.IMPACT - 0.25)

    def update(self, st):
        e = self.elapsed(st)
        c = self.cue
        a, tg = self.a, self.tg
        on_map = bool(st.battle and st.battle.arena is None)
        if e < 0.05:
            a.facing = _facing(a, tg)
        if not self.ranged and on_map:
            # Creatures stay in their squares: a short bump towards the target.
            dx, dy = tg.x - self.home[0], tg.y - self.home[1]
            n = max(1.0, math.hypot(dx, dy))
            p = math.sin(min(1.0, max(0.0, (e - 0.75) / 0.4)) * math.pi)
            a.dx, a.dy = dx / n * 6 * p, dy / n * 6 * p
            a.state = "attack" if 0.8 <= e < 1.15 else "idle"
        elif not self.ranged:
            gap = (tg.x + (14 if tg.x < a.x else -14)) - self.home[0]
            gy = tg.y - self.home[1]
            if e < 0.35:
                p = e / 0.35
            elif e < 1.3:
                p = 1.0
            elif e < 1.6:
                p = 1 - (e - 1.3) / 0.3
            else:
                p = 0.0
            a.dx = gap * p
            a.dy = gy * p
            a.state = "attack" if 0.8 <= e < 1.15 else ("walk" if 0 < p < 1 else "idle")
            a.anim_t += 1 / st.fps
        else:
            a.state = "attack" if 0.65 <= e < 1.0 else "idle"
        if not self.done_impact and e >= self.IMPACT:
            self.done_impact = True
            tx, ty = _center(st, c["target"])
            if c.get("hit"):
                fx_id = c.get("fx", "claw" if c.get("claw") else "slash")
                if not self.ranged or c.get("fx"):
                    st.fx.append(Fx(st.a.fx(fx_id), tx, ty, st.t, fps=16, flip=tg.x < a.x))
                tg.flash_until = st.t + 0.35
                tg.shake_until = st.t + 0.3
                st.sfx("crit" if c.get("critical") else "hit")
                dmg = c.get("damage", 0)
                txt = f"-{dmg}" + ("!" if c.get("critical") else "")
                _popup(st, c["target"], ("CRIT " if c.get("critical") else "") + txt, (230, 90, 70, 255), st.t,
                       big=bool(c.get("critical")))
                if c.get("sneak_attack"):
                    _popup(st, c["actor"], "Sneak Attack", (242, 201, 76, 255), st.t + 0.1)
                _apply_hp(st, c["target"], c.get("hp_after"))
            else:
                st.sfx("miss")
                tg.dy = -4
                _popup(st, c["target"], "MISS", (195, 192, 214, 255), st.t)
        if self.done_impact and e > self.IMPACT + 0.2:
            tg.dy = 0
        if e >= self.DUR:
            a.dx = a.dy = 0
            a.state = "idle"
            return True
        return False


class BattleCastTask(Task):
    """Cue fields: actor, spell, results [{target, hit|saved, damage, hp_after, heal}], roll (optional)."""

    SPIN = 0.7
    IMPACT = 1.15
    DUR = 2.1

    def start(self, st):
        super().start(st)
        c = self.cue
        self.a = st.actors[c["actor"]]
        self.spec = st.a.spell_fx(c["spell"])
        roll = c.get("roll")
        if roll:
            st.ui.dice.append({"roll": roll, "t0": st.t, "dur": self.DUR + 0.3, "spin": self.SPIN,
                               "label": c.get("label", ""), "line": c.get("line", "")})
            st.sfx("dice_roll")
            st.sfx("dice_land", st.t + self.SPIN)
            if roll.get("critical"):
                st.sfx("nat20", st.t + self.SPIN + 0.05)
        elif c.get("label"):
            st.ui.dice.append({"roll": {"kind": "text"}, "t0": st.t, "dur": self.DUR, "spin": 0.2,
                               "label": c.get("label", ""), "line": c.get("line", "")})
        ax, ay = _center(st, c["actor"])
        st.fx.append(Fx(st.a.fx("boost"), ax, ay, st.t + 0.2, fps=18, front=True))
        snd = self.spec.get("sfx", ["magic"])
        st.sfx(snd[0], st.t + 0.3)
        preset = self.spec["preset"]
        targets = [r["target"] for r in c.get("results", [])] or c.get("targets", [])
        if preset in ("projectile", "beam"):
            dur = 0.2 if preset == "beam" else 0.38
            count = c.get("count", 1)
            frames = st.a.fx(self.spec["projectile"])
            for i, tid in enumerate(targets * count if count > 1 and len(targets) == 1 else targets):
                tx, ty = _center(st, tid)
                st.projectiles.append(Projectile(frames, ax, ay, tx, ty, self.t0 + self.IMPACT - dur + i * 0.08, dur,
                                                 arc=8 if preset == "projectile" else 0))
        self.targets = targets
        self.done_impact = False
        self.area_shown = False
        aim = None
        if c.get("toward"):
            aim = tile_to_px(*c["toward"])
        elif targets and targets[0] in st.actors and targets[0] != c["actor"]:
            t0 = st.actors[targets[0]]
            aim = (t0.x, t0.y)
        if aim:
            dx, dy = aim[0] - self.a.x, aim[1] - self.a.y
            self.a.facing = ("right" if dx > 0 else "left") if abs(dx) >= abs(dy) else ("down" if dy > 0 else "up")

    def update(self, st):
        e = self.elapsed(st)
        c = self.cue
        self.a.state = "special1" if 0.25 <= e < 1.2 else "idle"
        if c.get("area") and st.battle and not self.area_shown and e >= 0.3:
            st.battle.area = [tuple(q) for q in c["area"]]
            self.area_shown = True
        if self.area_shown and e >= 1.9 and st.battle:
            st.battle.area = None
        if not self.done_impact and e >= self.IMPACT:
            self.done_impact = True
            snd = self.spec.get("sfx", ["magic"])
            if len(snd) > 1:
                st.sfx(snd[1])
            for r in c.get("results", []):
                tid = r["target"]
                if tid not in st.actors:
                    continue
                tx, ty = _center(st, tid)
                impact = self.spec.get("impact")
                if impact:
                    st.fx.append(Fx(st.a.fx(impact, self.spec.get("tint")), tx, ty, st.t, fps=16))
                if r.get("heal") is not None:
                    _popup(st, tid, f"+{r['heal']}", (166, 214, 92, 255), st.t)
                    _apply_hp(st, tid, r.get("hp_after"))
                elif r.get("effect"):
                    _popup(st, tid, r["effect"].replace("_", " ").title(), (242, 201, 76, 255), st.t)
                elif r.get("damage") is not None and r.get("damage") > 0:
                    st.actors[tid].flash_until = st.t + 0.35
                    st.actors[tid].shake_until = st.t + 0.3
                    label = f"-{r['damage']}"
                    if r.get("saved"):
                        label += " (save)"
                    _popup(st, tid, label, (230, 90, 70, 255), st.t)
                    _apply_hp(st, tid, r.get("hp_after"))
                elif r.get("saved") or r.get("hit") is False:
                    _popup(st, tid, "SAVED" if r.get("saved") else "MISS", (195, 192, 214, 255), st.t)
        if e >= self.DUR:
            self.a.state = "idle"
            return True
        return False


class BattleNoteTask(Task):
    """A short word over a creature: Dash, Dodge, Disengage, Hidden..."""

    def start(self, st):
        super().start(st)
        if self.cue["actor"] in st.actors:
            _popup(st, self.cue["actor"], self.cue["text"], (242, 201, 76, 255), st.t)
        self.dur = self.cue.get("duration", 0.7)

    def update(self, st):
        return self.elapsed(st) >= self.dur


class BattleFaintTask(Task):
    DUR = 0.8

    def start(self, st):
        super().start(st)
        self.a = st.actors[self.cue["actor"]]
        st.sfx("faint")
        self.pc = self.cue.get("pc", False)

    def update(self, st):
        e = self.elapsed(st)
        if self.pc:
            self.a.state = "down"
        else:
            self.a.alpha = max(0.0, 1 - e / self.DUR) if int(e * 16) % 2 == 0 else 0.0
        if e >= self.DUR:
            if not self.pc:
                self.a.visible = False
            return True
        return False


class BattleReviveTask(Task):
    def start(self, st):
        super().start(st)
        a = st.actors[self.cue["actor"]]
        a.state = "idle"
        a.visible = True
        a.alpha = 1.0
        _popup(st, a.id, "Back up!", (166, 214, 92, 255), st.t + 0.2) if self.cue.get("popup") else None


class RollTask(Task):
    """Show a logged roll in the dice tray (checks, saves, death saves)."""

    SPIN = 0.7

    def start(self, st):
        super().start(st)
        c = self.cue
        self.dur = c.get("duration", 2.0)
        st.ui.dice.append({"roll": c["roll"], "t0": st.t, "dur": self.dur + 0.2, "spin": self.SPIN,
                           "label": c.get("label", ""), "line": c.get("line", "")})
        st.sfx("dice_roll")
        st.sfx("dice_land", st.t + self.SPIN)
        if c["roll"].get("kind") == "d20" and c["roll"].get("natural") == 20:
            st.sfx("nat20", st.t + self.SPIN + 0.05)
        elif c["roll"].get("kind") == "d20" and c["roll"].get("natural") == 1:
            st.sfx("nat1", st.t + self.SPIN + 0.05)

    def update(self, st):
        return self.elapsed(st) >= self.dur


TASKS = {
    "scene": SceneTask, "spawn": SpawnTask, "despawn": DespawnTask, "face": FaceTask, "move": MoveTask,
    "camera": CameraTask, "say": SayTask, "narrate": SayTask, "emote": EmoteTask, "wait": WaitTask,
    "location_card": LocationCardTask, "title": TitleTask, "progress": ProgressTask, "lantern": LanternTask, "time_of_day": TimeOfDayTask,
    "music": MusicTask, "music_stop": MusicTask, "sfx": SfxTask, "fade": FadeTask,
    "battle_start": BattleStartTask, "battle_end": BattleEndTask, "battle_attack": BattleAttackTask,
    "battle_cast": BattleCastTask, "battle_faint": BattleFaintTask, "battle_revive": BattleReviveTask,
    "roll": RollTask, "dm_intro": DmIntroTask, "initiative": InitiativeTask, "battle_turn": BattleTurnTask, "battle_move": BattleMoveTask,
    "battle_note": BattleNoteTask,
}


class Runner:
    def __init__(self, timeline: dict, assets: Assets, fps: int | None = None):
        self.timeline = timeline
        self.stage = Stage(assets, fps or timeline.get("fps", 30))
        self.stage.reading = timeline.get("reading", {})
        self.frame_count = 0
        self.cue_times: list[float] = []  # start time of each cue (for chapters and thumbnails)

    @classmethod
    def from_file(cls, path: str | Path, assets: Assets) -> "Runner":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f), assets)

    def _tick(self, active: list[Task]) -> list[Task]:
        st = self.stage
        still = [t for t in active if not t.update(st)]
        return still

    def _frame(self, render: bool):
        if render:
            return self.stage.render()
        self.stage._camera()  # the camera eases every frame, drawn or not
        return None

    def frames(self, render: bool = True) -> Iterator[Image.Image | None]:
        st = self.stage
        dt = 1.0 / st.fps
        active: list[Task] = []
        for cue in self.timeline["cues"]:
            self.cue_times.append(st.t)
            cls = TASKS.get(cue["op"])
            if cls is None:
                raise ValueError(f"Unknown cue op {cue['op']!r}")
            task = cls(cue)
            task.start(st)
            active.append(task)
            if not task.blocking:
                continue
            guard = 0
            while True:
                active = self._tick(active)
                if task not in active:
                    break
                yield self._frame(render)
                self.frame_count += 1
                st.t = self.frame_count * dt
                guard += 1
                if guard > st.fps * 120:
                    raise RuntimeError(f"Cue never finished: {cue}")
        tail = self.timeline.get("tail", 0.5)
        end = st.t + tail
        while st.t < end or active:
            active = self._tick(active)
            yield self._frame(render)
            self.frame_count += 1
            st.t = self.frame_count * dt
            if st.t > end + 30:
                break

    def duration(self) -> float:
        """Run the timeline without drawing and return its length in seconds."""
        for _ in self.frames(render=False):
            pass
        return self.stage.t
