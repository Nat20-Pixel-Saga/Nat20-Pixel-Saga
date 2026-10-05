"""One episode, end to end.

    plan (Sonnet) -> validate -> resolve (engine, seeded dice) -> script (Sonnet/Opus)
    -> continuity (mechanical + Haiku) -> assemble timeline -> render
    -> wiki facts (Haiku) -> packaging (Haiku) -> archive, state, wiki

Everything lands in ``episodes/<id>/``. The state in ``state/`` is only
replaced with ``commit=True``, after the episode has been fully produced.

Modes: ``offline`` replays ``fixtures/<id>/`` (CI, tests); ``live`` calls the
Claude API; ``record`` calls it and saves the outputs as fixtures; ``agent``
is for a Claude session doing the writing itself: whenever a step's output is
missing, the full prompt and schema are written to
``episodes/<id>/pending/<step>.md`` and the run stops (exit code 3); the
session writes ``fixtures/<id>/<step>.json`` and runs again. Rejected outputs
are moved aside and the next prompt carries the reasons.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from ..schema import validate_named
from ..state import PARTY_DIR, ROOT, STATE_DIR, load_json, save_json
from . import prompts
from .assemble import assemble
from .claude import ClaudeError, Client, Ledger, RecordingClient, ReplayClient
from .context import ContextPack, party_brief, spoiler_hits, world_brief
from .continuity import format_issues, mechanical, merge
from .resolve import check_roll_cues, resolve, validate_plan
from .wiki import EPISODES, build_site

FIXTURES = ROOT / "fixtures"


class EpisodeError(RuntimeError):
    pass


class NeedsAuthor(EpisodeError):
    """Agent mode: a step's output must be written before the run can continue."""

    def __init__(self, step: str, prompt_path: Path, fixture_path: Path):
        super().__init__(f"needs {step}: read {prompt_path}, write {fixture_path}")
        self.step, self.prompt_path, self.fixture_path = step, prompt_path, fixture_path


DM_CONTEXT_NOTE = """The API call for this step also sends, as a cached system prompt, the series bible
(DM copy, with SECRET blocks) and the party dossiers: read `bible/00`, `01`, `06`, `08`, `10`,
`bible/RETCONS.md` and the four `dossiers/*.md` before writing. Foreshadow secrets; never reveal them."""
PUBLIC_CONTEXT_NOTE = """This is a PUBLIC step: the API call only sends the spoiler-free context (bible/01 sections
1-3 and 6-8, bible/08 without SECRET blocks, the dossiers' "At a glance" tables). Do NOT open the full bible,
the dossiers or any SECRET material while writing it: use only what is in this prompt."""


class AgentClient:
    """A Claude session is the model: outputs come from fixtures it writes."""

    def __init__(self, fixtures: Path, pending: Path, ledger: Ledger):
        self.fixtures, self.pending, self.ledger = Path(fixtures), Path(pending), ledger
        self._replay = ReplayClient(fixtures, ledger, batch=True)  # same usage estimate, for the cost report

    def call(self, req):
        fx = self.fixtures / f"{req.step}.json"
        if fx.exists():
            return self._replay.call(req)
        self.pending.mkdir(parents=True, exist_ok=True)
        path = self.pending / f"{req.step}.md"
        public = prompts.STEPS[req.step][3] == "public"
        path.write_text("\n\n".join([
            f"# Pending step: {req.step} ({req.model} in production)",
            f"Write the result as JSON to `{_rel(fx)}`, valid against "
            f"`schemas/{prompts.STEPS[req.step][1]}.schema.json` (reproduced below), then run the episode again.",
            PUBLIC_CONTEXT_NOTE if public else DM_CONTEXT_NOTE,
            "---", req.user, "---", "## Output schema", "```json",
            json.dumps(req.schema, indent=1, ensure_ascii=False), "```"]), encoding="utf-8")
        raise NeedsAuthor(req.step, path, fx)

    def reject(self, step: str) -> None:
        fx = self.fixtures / f"{step}.json"
        if fx.exists():
            n = len(list(self.fixtures.glob(f"{step}.rejected*.json"))) + 1
            fx.rename(self.fixtures / f"{step}.rejected{n}.json")


@dataclass
class EpisodeConfig:
    campaign: int
    episode: int
    mode: str = "offline"            # offline (fixtures) | live | record (live + save fixtures) | agent
    render: str = "none"             # none | preview (960x540) | full (1080p)
    commit: bool = False             # replace state/ and rebuild wiki/docs
    batch: bool = True               # price live calls at Batch API rates (and submit them as batches)
    attempt: int = 1
    max_retries: int = 2
    wiki_url: str | None = None
    state_dir: Path | None = None    # default: episodes/<id>/state_before if archived, else state/


def make_client(cfg: EpisodeConfig, eid: str):
    fx = FIXTURES / eid
    if cfg.mode == "agent":
        return AgentClient(fx, EPISODES / eid / "pending", Ledger())
    if cfg.mode == "offline":
        return ReplayClient(fx, Ledger(), batch=cfg.batch)
    live = Client(ledger=Ledger())
    return RecordingClient(live, fx) if cfg.mode == "record" else live


def _call(client, req, batch: bool):
    if batch and isinstance(client, Client):
        bid = client.submit_batch([req])
        return client.batch_results(bid, [req], poll=20)[0]
    return client.call(req)


def _load_state(d: Path) -> tuple[dict, dict]:
    sheets = {p.stem: load_json(p) for p in sorted((d / "party").glob("*.json"))}
    return sheets, load_json(d / "world.json")


def run_episode(cfg: EpisodeConfig, log=print) -> dict:
    t0 = time.time()
    eid = f"C{cfg.campaign:02d}-E{cfg.episode:03d}"
    out = EPISODES / eid
    archived = out / "state_before"
    state_dir = Path(cfg.state_dir) if cfg.state_dir else archived if (archived / "world.json").exists() else STATE_DIR
    sheets, world = _load_state(state_dir)
    if cfg.commit:
        live_sheets, live_world = _load_state(STATE_DIR)
        s = live_world["series"]
        if (s["campaign"], s["episode_in_campaign"]) != (cfg.campaign, cfg.episode - 1):
            raise EpisodeError(f"Can't commit {eid}: the live state is at C{s['campaign']}E{s['episode_in_campaign']}")
        if (live_sheets, live_world) != (sheets, world):
            raise EpisodeError(f"{eid} was archived from a different state than the live one; not committing")
    ctx = ContextPack.build(cfg.campaign, cfg.episode, sheets, world)
    seed = f"{eid}-{cfg.attempt}"
    out.mkdir(parents=True, exist_ok=True)
    if not (archived / "world.json").exists():
        save_json(archived / "world.json", world)
        for cid, sh in sheets.items():
            save_json(archived / "party" / f"{cid}.json", sh)
    client = make_client(cfg, eid)
    agent = cfg.mode == "agent"
    retries = 5 if agent else cfg.max_retries
    batch = cfg.batch and cfg.mode != "offline"
    premiere = cfg.episode in (1, len(ctx.campaign["episodes"]))
    log(f"[{eid}] {ctx.entry['title']} - seed {seed} - state from {_rel(state_dir)}")

    def rejected(step: str, i: int, problems: list[str], what: str) -> str:
        """Decide what happens to a bad output: retry with feedback, or stop."""
        log(f"  {step} attempt {i + 1}: {len(problems)} problems")
        if agent and i < retries:
            client.reject(step)
            return problems_text(what, problems)
        if cfg.mode == "offline" or i >= retries:
            raise EpisodeError(f"{step} rejected:\n" + "\n".join(problems))
        return problems_text(what, problems)

    # 1. Plan ---------------------------------------------------------------
    feedback = ""
    for i in range(retries + 1):
        req = prompts.build_request("plan", prompts.model_for("plan"), ctx.dm_core, episode_id=eid, seed=seed,
                                    campaign_view=ctx.campaign_view(), state_view=ctx.state_view(),
                                    recap=ctx.recap(), stage_view=ctx.stage_view(), feedback=feedback)
        plan = _call(client, req, batch)
        errors = validate_plan(plan, sheets, world)
        if not errors:
            break
        feedback = rejected("plan", i, errors, "plan")
    save_json(out / "plan.json", plan)
    log(f"  plan: {len(plan['scenes'])} scenes, "
        f"{sum(len(s.get('checks', [])) for s in plan['scenes'])} checks, "
        f"{sum(1 for s in plan['scenes'] if s.get('encounter'))} fight(s)")

    # 2. Resolve: the dice decide -------------------------------------------
    res = resolve(plan, sheets, world, seed, cfg.attempt)
    check_cues = check_roll_cues(res, plan, sheets)
    save_json(out / "outcomes.json", res.outcomes)
    for c in res.outcomes["checks"]:
        log(f"  {c['id']} {c['what']} vs DC {c['dc']}: {c['result']}")
    for f in res.outcomes["fights"]:
        log(f"  {f['id']}: {f['winner']} in {f['rounds']} rounds, {len(f['actions'])} log lines")
    log(f"  {len(res.episode['rolls'])} rolls in all")

    # 3. Script + continuity --------------------------------------------------
    feedback = ""
    for i in range(retries + 1):
        req = prompts.build_request("script", prompts.model_for("script", ctx.entry, premiere), ctx.dm_core,
                                    episode_id=eid, plan=json.dumps(plan, ensure_ascii=False, indent=1),
                                    outcomes=res.outcomes_text(), state_view=ctx.state_view(), recap=ctx.recap(),
                                    feedback=feedback)
        script = _call(client, req, batch)
        mech = mechanical(plan, script, res, check_cues, sheets)
        review = None
        if not any(m["severity"] == "blocker" for m in mech):  # mechanical blockers go straight back
            req = prompts.build_request("continuity", prompts.model_for("continuity"), ctx.dm_core, episode_id=eid,
                                        mechanical=format_issues(mech), plan=json.dumps(plan, ensure_ascii=False),
                                        outcomes=res.outcomes_text(), script=json.dumps(script, ensure_ascii=False),
                                        state_view=ctx.state_view())
            review = _call(client, req, batch)
        cont = merge(mech, review, eid)
        blockers = [x for x in cont["issues"] if x["severity"] == "blocker"]
        log(f"  script attempt {i + 1}: {len(blockers)} blockers, {len(cont['issues']) - len(blockers)} warnings")
        if cont["ok"]:
            break
        save_json(out / "continuity.json", cont)
        if agent and review is not None:
            client.reject("continuity")  # the review belonged to the rejected script
        feedback = rejected("script", i, [format_issues([b]) for b in blockers], "script")
    save_json(out / "script.json", script)
    save_json(out / "continuity.json", cont)

    # 4. Assemble -----------------------------------------------------------
    asm = assemble(plan, script, res, check_cues, sheets)
    tl = asm.timeline
    tl_errors = validate_named(tl, "timeline")
    if tl_errors or asm.problems:
        raise EpisodeError(f"Timeline problems: {tl_errors + asm.problems}")
    save_json(out / "timeline.json", tl)
    mark_seen(script, res.world_after, eid)

    # 5. Measure, render ----------------------------------------------------
    from ..render.assets import Assets
    from ..render.timeline import Runner
    from .packaging import chapters, full_description, render_thumbnail, thumbnail_spec, thumbnail_time, with_bumpers
    assets = Assets()
    runner = Runner(tl, assets)
    duration = runner.duration()
    from ..render.brand import INTRO_S, OUTRO_S
    chap, video_s = with_bumpers(chapters(tl, runner.cue_times, duration), INTRO_S, OUTRO_S, duration)
    save_json(out / "chapters.json", chap)      # times in the published video (intro included)
    log(f"  timeline: {len(tl['cues'])} cues, {duration / 60:.1f} min")
    if not 300 <= duration <= 600:
        log(f"  WARNING: {duration / 60:.1f} min is outside the 5-10 minute target")
    video = None
    tl_hash = hashlib.sha256(json.dumps(tl, sort_keys=True).encode()).hexdigest()
    stamp = out / "video.json"
    if cfg.render != "none":
        from ..render.video import render
        video = out / "video.mp4"
        info = render(tl, video, assets=assets, scale=4 if cfg.render == "full" else 2,
                      preset="medium" if cfg.render == "full" else "veryfast", log=lambda *_: None)
        save_json(stamp, {"timeline_sha256": tl_hash, "frames": info["frames"], "render": cfg.render})
        log(f"  rendered {video.name}: {info['frames']} frames")
    elif (out / "video.mp4").exists() and stamp.exists() and load_json(stamp)["timeline_sha256"] == tl_hash:
        video = out / "video.mp4"  # an earlier render of exactly this timeline
        log("  video.mp4 is up to date with this timeline")

    # 6. Wiki facts (public context only) ---------------------------------------
    public_state = "## Party\n" + party_brief(res.sheets_after) + "\n\n## World\n" + world_brief(res.world_after, True)
    public_outcomes = json.dumps({"checks": [{k: c[k] for k in ("id", "who", "what", "dc", "result")}
                                             for c in res.outcomes["checks"]],
                                  "aftermath": [{k: a[k] for k in ("id", "what", "result")}
                                                for a in res.outcomes["aftermath"]],
                                  "fights": [{"id": f["id"], "winner": f["winner"], "rounds": f["rounds"],
                                              "actions": f["actions"]} for f in res.outcomes["fights"]]},
                                 ensure_ascii=False, indent=1)
    feedback = ""
    for i in range(retries + 1):
        req = prompts.build_request("wiki_facts", prompts.model_for("wiki_facts"), ctx.public_core, episode_id=eid,
                                    script=json.dumps(script, ensure_ascii=False), outcomes=public_outcomes,
                                    state_view=public_state, recap=ctx.recap(), feedback=feedback)
        facts = _call(client, req, batch)
        problems = validate_named(facts, "wiki_facts") + \
            [f"spoiler {h['phrase']!r}" for h in spoiler_hits(json.dumps(facts), cfg.campaign)] + \
            _quote_problems(facts, script)
        if not problems:
            break
        feedback = rejected("wiki_facts", i, problems, "wiki facts")
    save_json(out / "wiki_facts.json", facts)

    # 7. Packaging --------------------------------------------------------------
    actions = "\n".join(a for f in res.outcomes["fights"] for a in f["actions"])
    feedback = ""
    for i in range(retries + 1):
        req = prompts.build_request("packaging", prompts.model_for("packaging"), ctx.public_core, episode_id=eid,
                                    title=plan["title"], summary=facts["summary"],
                                    script=json.dumps(script, ensure_ascii=False), actions=actions, feedback=feedback)
        pk = _call(client, req, batch)
        errs = validate_named(pk, "packaging") + \
            [f"spoiler {h['phrase']!r}" for h in spoiler_hits(json.dumps(pk), cfg.campaign)]
        if not errs:
            break
        feedback = rejected("packaging", i, errs, "packaging")
    record = dict(res.episode, status="rendered" if video else "scripted")
    published = {}
    if (out / "packaging.json").exists():  # keep links added by scripts/publish_video.py
        prev = load_json(out / "packaging.json")
        published = {k: prev[k] for k in ("video_url", "release_url") if k in prev}
    pk_full = {**pk, **published, "chapters": chap, "duration_s": round(video_s, 1),
               "description_full": full_description(pk, record, chap, cfg.wiki_url)}
    save_json(out / "packaging.json", pk_full)
    t_thumb = thumbnail_time(pk.get("thumbnail_moment"), tl, runner.cue_times, plan)
    render_thumbnail(tl, t_thumb, pk["thumbnail_text"], f"CAMPAIGN {cfg.campaign}  -  EPISODE {cfg.episode}", out / "thumbnail.png",
                     assets, spec=thumbnail_spec(record["id"]))

    # 8. Archive, cost, state, wiki ---------------------------------------------
    save_json(out / "episode.json", record)
    state_after = out / "state_after"
    save_json(state_after / "world.json", res.world_after)
    for cid, s in res.sheets_after.items():
        save_json(state_after / "party" / f"{cid}.json", s)
    cost = client.ledger.summary()
    cost["episode"] = eid
    cost["minutes"] = round(duration / 60, 2)
    save_json(out / "cost.json", cost)
    cost["mode"] = cfg.mode
    save_json(out / "cost.json", cost)
    if agent and (out / "pending").exists():
        shutil.rmtree(out / "pending")
    if cfg.commit:
        save_json(STATE_DIR / "world.json", res.world_after)
        for cid, sh in res.sheets_after.items():
            save_json(PARTY_DIR / f"{cid}.json", sh)
        pages = build_site()
        log(f"  committed state; wiki rebuilt ({len(pages)} files)")
    else:
        preview = out / "wiki_preview"
        if preview.exists():
            shutil.rmtree(preview)
        pages = build_site(preview, state_dir=state_after)
        log(f"  wiki preview: {len(pages)} files in {preview}")
    log(f"  cost: ${cost['total_usd']:.4f}" + (" (estimated)" if cost["estimated"] else "") +
        f" - done in {time.time() - t0:.0f} s")
    return {"id": eid, "dir": out, "duration": duration, "cost": cost, "video": video, "chapters": chap}


def _rel(path: Path) -> str:
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return str(path)


def problems_text(what: str, problems: list[str]) -> str:
    return (f"\n### Your previous {what} was rejected. Fix exactly these problems and resubmit the whole thing:\n"
            + "\n".join(f"- {p}" for p in problems))


def _quote_problems(facts: dict, script: dict) -> list[str]:
    """Quotes must be copied exactly from the script."""
    lines = {c.get("text", "") for s in script["scenes"] for c in s["cues"] if c.get("op") == "say"}
    return [f"quote not in script: {q['text'][:50]!r}" for q in facts.get("quotes", []) if q["text"] not in lines]


def mark_seen(script: dict, world: dict, eid: str) -> None:
    """NPCs who speak or are spawned on screen have now been seen."""
    ids = set()
    for s in script["scenes"]:
        for c in s["cues"]:
            for key in ("speaker", "sprite"):
                if c.get(key):
                    ids.add("npc." + c[key].replace("_", "-"))
    for nid in ids:
        if nid in world["npcs"]:
            n = world["npcs"][nid]
            n["first_seen"] = n.get("first_seen") or eid
            n["last_seen"] = eid
            if n["status"] == "unmet":
                n["status"] = "alive"


__all__ = ["EpisodeConfig", "run_episode", "EpisodeError", "NeedsAuthor", "ClaudeError"]
