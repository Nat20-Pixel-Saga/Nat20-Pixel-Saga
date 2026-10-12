#!/usr/bin/env python3
"""Upload released episodes to YouTube and schedule their premieres.

Runs in GitHub Actions (.github/workflows/youtube.yml). One queue, in order of
publish time, holds everything released and not yet in the ledger
(wiki/data/youtube.json): the story's episodes (in episode order, each at its
premiere in production/schedule.json) and their Shorts, and every upload of the
other series in production/youtube.json `series` (The Pit: the times, titles and
descriptions come from the plan file in its GitHub release). Each run uploads the
first `max_per_run` of them: it downloads the MP4 and thumbnail from the release
(REST API, so drafts are found too), uploads and schedules the video, sets the
thumbnail and adds it to its playlist. Once a video's time has passed, `link`
marks it live so the wiki shows "Watch on YouTube".

    python scripts/youtube_upload.py check       # verify the credentials (prints the channel)
    python scripts/youtube_upload.py plan        # the whole queue, night by night (no upload, no credentials)
    python scripts/youtube_upload.py upload      # upload and schedule
    python scripts/youtube_upload.py link        # mark videos whose slot has passed as live
    python scripts/youtube_upload.py refresh     # re-check stored video IDs (YouTube's 30-day rule)
    python scripts/youtube_upload.py record 3 https://youtu.be/abc123 "2026-10-08 21:00"
                                                 # register a video uploaded by hand (Paris time)

Credentials come from the environment: YT_CLIENT_ID, YT_CLIENT_SECRET and
YT_REFRESH_TOKEN (see production/YOUTUBE.md). Uses only the standard library
(plus `gh` to download release assets).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "production" / "youtube.json"
LEDGER = ROOT / "wiki" / "data" / "youtube.json"
EPISODES = ROOT / "episodes"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
CHUNK = 8 * 1024 * 1024


# ------------------------------------------------------------------ config
def load_config() -> dict:
    return json.loads(CONFIG.read_text())


def load_ledger() -> dict:
    return json.loads(LEDGER.read_text()) if LEDGER.exists() else {}


def save_ledger(ledger: dict) -> None:
    LEDGER.write_text(json.dumps(dict(sorted(ledger.items())), indent=1, ensure_ascii=False) + "\n")


def notice(line: str, level: str = "notice") -> None:
    """Print a line; in GitHub Actions also show it on the run's summary page."""
    print(line, flush=True)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{level} title=YouTube::{line}", flush=True)


# ---------------------------------------------------------------- schedule
def next_slots(cfg: dict, after: dt.datetime, n: int) -> list[dt.datetime]:
    """The next n publishing slots strictly after `after` (aware datetimes, UTC)."""
    sch = cfg["schedule"]
    tz = ZoneInfo(sch["timezone"])
    hh, mm = (int(x) for x in sch["time"].split(":"))
    days = set(sch["weekdays"])            # 0 = Monday
    local = after.astimezone(tz)
    day = local.date()
    out = []
    while len(out) < n:
        if day.weekday() in days:
            slot = dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
            if slot > local:
                out.append(slot.astimezone(dt.timezone.utc))
        day += dt.timedelta(days=1)
    return out


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------- metadata
def clean_text(s: str, limit: int) -> str:
    # YouTube rejects angle brackets in titles and descriptions.
    s = s.replace("<", "(").replace(">", ")")
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def clean_tags(tags: list[str], limit: int = 480) -> list[str]:
    out, used = [], 0
    for t in tags:
        t = t.replace("<", "").replace(">", "").replace(",", " ").strip()
        cost = len(t) + (2 if " " in t else 0) + (1 if out else 0)   # quoted multi-word tags count their quotes
        if not t or used + cost > limit:
            continue
        out.append(t)
        used += cost
    return out


def video_body(pk: dict, cfg: dict, publish_at: dt.datetime | None) -> dict:
    status = {"selfDeclaredMadeForKids": bool(cfg.get("made_for_kids", False)),
              "containsSyntheticMedia": bool(cfg.get("contains_synthetic_media", False)),
              "license": "youtube", "embeddable": True}
    if publish_at is not None:
        status.update(privacyStatus="private", publishAt=iso(publish_at))
    else:
        status["privacyStatus"] = cfg.get("privacy", "public")
    snippet = {"title": clean_text(pk["title"], 100),
               "description": clean_text(pk.get("description_full") or pk["description"], 5000),
               "tags": clean_tags(pk.get("tags", [])),
               "categoryId": str(cfg.get("category_id", "24")),
               "defaultLanguage": cfg.get("language", "en"),
               "defaultAudioLanguage": cfg.get("language", "en")}
    return {"snippet": snippet, "status": status}


# -------------------------------------------------------------------- HTTP
def _request(method: str, url: str, token: str | None = None, data: bytes | None = None,
             headers: dict | None = None) -> tuple[int, dict, bytes]:
    h = dict(headers or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _json(status: int, body: bytes, what: str) -> dict:
    if status >= 400:
        raise SystemExit(f"{what} failed ({status}): {body.decode(errors='replace')[:2000]}")
    return json.loads(body) if body else {}


def access_token() -> str:
    missing = [k for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN") if not os.environ.get(k)]
    if missing:
        notice(f"Playlist(s) not found: {', '.join(missing)}", "error")
        raise SystemExit(f"Missing secrets: {', '.join(missing)} (see production/YOUTUBE.md)")
    form = urllib.parse.urlencode({"client_id": os.environ["YT_CLIENT_ID"],
                                   "client_secret": os.environ["YT_CLIENT_SECRET"],
                                   "refresh_token": os.environ["YT_REFRESH_TOKEN"],
                                   "grant_type": "refresh_token"}).encode()
    st, _, body = _request("POST", "https://oauth2.googleapis.com/token", data=form,
                           headers={"Content-Type": "application/x-www-form-urlencoded"})
    if st >= 400:
        raise SystemExit(f"Could not refresh the YouTube token ({st}): {body.decode(errors='replace')}\n"
                         "If it says invalid_grant, the refresh token expired or was revoked: make a new "
                         "one (production/YOUTUBE.md, step 4) and check the consent screen is 'In production'.")
    return json.loads(body)["access_token"]


def upload_video(token: str, path: Path, body: dict) -> str:
    size = path.stat().st_size
    st, hdr, resp = _request(
        "POST", f"{UPLOAD}/videos?uploadType=resumable&part=snippet,status&notifySubscribers=true",
        token, json.dumps(body).encode(),
        {"Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": "video/mp4",
         "X-Upload-Content-Length": str(size)})
    _json(st, resp, "Starting the upload")
    session = hdr.get("Location") or hdr.get("location")
    sent = 0
    with path.open("rb") as f:
        while True:
            f.seek(sent)
            chunk = f.read(CHUNK)
            end = sent + len(chunk) - 1
            for attempt in range(5):
                st, hdr, resp = _request("PUT", session, token, chunk,
                                         {"Content-Length": str(len(chunk)),
                                          "Content-Range": f"bytes {sent}-{end}/{size}"})
                if st in (200, 201, 308):
                    break
                if st >= 500 or st == 429:
                    time.sleep(2 ** attempt * 5)
                    continue
                _json(st, resp, "Uploading the video")
            else:
                _json(st, resp, "Uploading the video (gave up after retries)")
            if st in (200, 201):
                return json.loads(resp)["id"]
            rng = hdr.get("Range") or hdr.get("range")
            sent = int(rng.split("-")[1]) + 1 if rng else 0
            print(f"  {sent * 100 // size}% uploaded", flush=True)


def set_thumbnail(token: str, video_id: str, png: Path) -> None:
    data, ctype = png.read_bytes(), "image/png"
    if len(data) > 2_000_000:                      # YouTube's limit; convert big PNGs
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.open(png).convert("RGB").save(buf, "JPEG", quality=92)
        data, ctype = buf.getvalue(), "image/jpeg"
    st, _, resp = _request("POST", f"{UPLOAD}/thumbnails/set?videoId={video_id}", token, data,
                           {"Content-Type": ctype})
    if st >= 400:
        # Custom thumbnails need a phone-verified channel; the upload itself is fine.
        print(f"  thumbnail not set ({st}): {resp.decode(errors='replace')[:300]}", flush=True)


def add_to_playlist(token: str, playlist_id: str, video_id: str) -> None:
    body = {"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}
    st, _, resp = _request("POST", f"{API}/playlistItems?part=snippet", token, json.dumps(body).encode(),
                           {"Content-Type": "application/json"})
    if st >= 400:
        print(f"  not added to playlist ({st}): {resp.decode(errors='replace')[:300]}", flush=True)


# ---------------------------------------------------------------- releases
def repo() -> str:
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    return json.loads((ROOT / "wiki" / "data" / "site.json").read_text())["repo"]


def gh_api(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True).stdout
    return json.loads(out) if out.strip() else None


def all_releases() -> list[dict]:
    """Every release, drafts included (they need push access: the workflow's token has it).
    The REST API is used rather than `gh release view`, which cannot always find a draft."""
    out, page = [], 1
    while True:
        batch = gh_api(f"repos/{repo()}/releases?per_page=100&page={page}")
        if not batch:
            return out
        out += batch
        page += 1


def story_release(rels: list[dict], eid: str) -> dict | None:
    """The episode's release: tagged with its id, or (a draft that lost its tag) carrying its MP4."""
    for rel in rels:
        if rel.get("tag_name") == eid:
            return rel
    for rel in rels:
        if any(a["name"] == f"{eid}.mp4" for a in rel.get("assets", [])):
            return rel
    return None


def asset(rel: dict, name: str) -> dict | None:
    return next((a for a in rel.get("assets", []) if a["name"] == name), None)


def download(a: dict, dest: Path) -> Path:
    with dest.open("wb") as fh:
        subprocess.run(["gh", "api", "-H", "Accept: application/octet-stream",
                        f"repos/{repo()}/releases/assets/{a['id']}"], stdout=fh, check=True)
    return dest


def released_episodes(rels: list[dict] | None = None) -> list[str]:
    """Committed episodes that have a GitHub release, in order."""
    rels = all_releases() if rels is None else rels
    world = json.loads((ROOT / "state" / "world.json").read_text())
    reached = (world["series"]["campaign"], world["series"]["episode_in_campaign"])
    out = []
    for d in sorted(EPISODES.glob("C??-E???")):
        eid = d.name
        if (int(eid[1:3]), int(eid[-3:])) > reached or not (d / "packaging.json").exists():
            continue
        rel = story_release(rels, eid)
        if rel and asset(rel, f"{eid}.mp4"):
            out.append(eid)
    return out


def pending(ledger: dict, released: list[str]) -> list[str]:
    # Strictly in order: never upload E5 before E4 is uploaded.
    out = []
    for eid in released:
        if eid in ledger:
            if out:
                break
            continue
        out.append(eid)
    return out


def schedule_for(cfg: dict, ledger: dict, eids: list[str], now: dt.datetime) -> dict[str, dt.datetime | None]:
    if not cfg.get("schedule"):
        return {e: None for e in eids}
    if cfg.get("follow_release_schedule"):
        # The shared premiere schedule (production/schedule.json): YouTube, wiki and release together.
        sys.path.insert(0, str(ROOT))
        from pqc import schedule
        lead = dt.timedelta(hours=cfg["schedule"].get("min_lead_hours", 2))
        fixed = {e: schedule.premiere(e) for e in eids}
        if all(t is not None and t > now + lead for t in fixed.values()):
            return fixed
        # A premiere already passed (or too close): fall back to the next free slots below.
    lead = dt.timedelta(hours=cfg["schedule"].get("min_lead_hours", 2))
    after = now + lead
    last = [parse_iso(v["publish_at"]) for v in ledger.values() if v.get("publish_at")]
    if last:
        after = max(after, max(last))
    return dict(zip(eids, next_slots(cfg, after, len(eids))))


# ---------------------------------------------------------------- commands
def cmd_check(cfg: dict | None = None) -> int:
    cfg = cfg or load_config()
    token = access_token()
    st, _, body = _request("GET", f"{API}/channels?part=snippet,status&mine=true", token)
    data = _json(st, body, "Reading the channel")
    for ch in data.get("items", []):
        print(f"Authorised for channel: {ch['snippet']['title']} (id {ch['id']}); "
              f"long uploads: {ch.get('status', {}).get('longUploadsStatus', '?')}")
    if not data.get("items"):
        print("Authorised, but this Google account has no YouTube channel yet.")
    ledger = load_ledger()
    for pid, pl in check_playlists(token, cfg).items():
        have = playlist_videos(token, pid)
        want = set(playlist_members(cfg, ledger).get(pid, []))
        kinds = {}
        for key, v in ledger.items():
            if v["video_id"] in have:
                kinds.setdefault("Shorts" if key.endswith(("-short", "-trailer", "-a", "-b")) else "videos", []).append(key)
        notice(f"Playlist {pid}: {pl['snippet']['title']!r} ({pl['status']['privacyStatus']}, {len(have)} items): "
               f"{len(want & have)} of the {len(want)} it should hold; recorded Shorts in it: "
               f"{', '.join(sorted(kinds.get('Shorts', []))) or 'none'}; "
               f"{len(have - {v['video_id'] for v in ledger.values()})} not in the ledger")
    ids = sorted({v["video_id"] for v in ledger.values()})
    items = {}
    for i in range(0, len(ids), 50):                # read-only: videos.list, 1 unit per call
        st, _, body = _request("GET", f"{API}/videos?part=status,liveStreamingDetails&maxResults=50"
                                      f"&id={','.join(ids[i:i + 50])}", token)
        items.update({it["id"]: it for it in _json(st, body, "Reading the stored videos").get("items", [])})
    for key in sorted(ledger):
        notice(describe_status(key, ledger[key], items.get(ledger[key]["video_id"])))
    return 0


def describe_status(key: str, entry: dict, item: dict | None, now: dt.datetime | None = None) -> str:
    """One line on what viewers can see of a stored video right now, and whether it matches the plan."""
    now = now or dt.datetime.now(dt.timezone.utc)
    vid = entry["video_id"]
    if item is None:
        return f"{key} {vid}: not found (deleted, or not on this channel)"
    st = item.get("status", {})
    privacy, publish_at = st.get("privacyStatus"), st.get("publishAt")
    premiere = (item.get("liveStreamingDetails") or {}).get("scheduledStartTime")
    planned = entry.get("publish_at")

    def paris(t):
        return dt.datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Paris")).strftime(
            "%a %d %b %H:%M Paris")
    if privacy == "private" and publish_at:
        ok = planned is None or publish_at[:16] == planned[:16]
        return (f"{key} {vid}: SCHEDULED - private until {paris(publish_at)}"
                + ("" if ok else f" (the ledger says {paris(planned)})"))
    if privacy == "public" and premiere:
        return f"{key} {vid}: PREMIERE - listed now, plays from {paris(premiere)} (viewers see a countdown)"
    if privacy == "public":
        early = planned and dt.datetime.fromisoformat(planned.replace("Z", "+00:00")) > now
        return f"{key} {vid}: PUBLIC now" + (f" - planned for {paris(planned)}: check YouTube Studio!" if early else "")
    return f"{key} {vid}: {privacy}" + (f", no publish time set (planned {paris(planned)})" if planned else "")


# ------------------------------------------------------------------- queue
def parse_local(when: str, tz: str) -> dt.datetime:
    return dt.datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tz)).astimezone(dt.timezone.utc)


def story_items(cfg: dict, ledger: dict, rels: list[dict], released: list[str], now: dt.datetime) -> list[dict]:
    """The story's episodes still to upload (strictly in order, each at its premiere) and the
    Shorts of episodes that are up or about to be (each the day after its episode)."""
    sys.path.insert(0, str(ROOT))
    from pqc import schedule
    lead = dt.timedelta(hours=cfg.get("schedule", {}).get("min_lead_hours", 2))
    todo = pending(ledger, released)
    slots = schedule_for(cfg, ledger, todo, now)
    items = []
    for eid in todo:
        rel = story_release(rels, eid)
        items.append({"key": eid, "when": slots[eid], "file": f"{eid}.mp4", "release": rel, "short": False,
                      "thumbnail": f"{eid}-thumbnail.png", "playlist": cfg.get("playlist_id"),
                      "meta": lambda led, eid=eid: json.loads((EPISODES / eid / "packaging.json").read_text())})
    for eid in released:
        pk = json.loads((EPISODES / eid / "packaging.json").read_text())
        if f"{eid}-short" in ledger or not pk.get("short") or (eid not in ledger and eid not in todo):
            continue
        rel = story_release(rels, eid)
        if not rel or not asset(rel, f"{eid}-short.mp4"):
            continue
        when = schedule.short_premiere(eid)
        items.append({"key": f"{eid}-short", "when": when if when and when > now + lead else None,
                      "file": f"{eid}-short.mp4", "release": rel, "short": True, "needs": eid,
                      "thumbnail": f"{eid}-short-cover.png", "playlist": cfg.get("shorts_playlist_id"),
                      "meta": lambda led, eid=eid, pk=pk: story_short_meta(eid, pk, led)})
    return items


def story_short_meta(eid: str, pk: dict, ledger: dict) -> dict:
    from pqc.pipeline.packaging import short_description
    site = json.loads((ROOT / "wiki" / "data" / "site.json").read_text())
    desc = short_description(pk, {"id": eid}, site.get("site_url"), ledger[eid]["url"])
    return {"title": pk["short"]["title"], "description_full": desc, "tags": pk.get("tags", []) + ["shorts"]}


def series_items(scfg: dict, plan: list[dict], rel: dict, ledger: dict, now: dt.datetime, lead: dt.timedelta,
                 notes: list[str] | None = None) -> list[dict]:
    """Uploads of another series (The Pit) from its release's plan file: each at its own time.
    One without a time (the subscriber-unlock bonus) waits until `times` in the config gives it
    one; one whose time is already too close is left out and reported, never published early or late."""
    tz = scfg.get("timezone", "Europe/Paris")
    items = []
    for x in plan:
        key = f"{scfg['key']}-{x['id']}"
        if key in ledger:
            continue
        when_s = (scfg.get("times") or {}).get(x["id"], x.get("when"))
        if not when_s:
            if notes is not None:
                notes.append(f"{key}: held (no time yet; set it in production/youtube.json series times)")
            continue
        when = parse_local(when_s, tz)
        if when <= now + lead:
            if notes is not None:
                notes.append(f"{key}: its time ({when_s}) is too close or past, so it was not uploaded; "
                             f"set a new time in production/youtube.json series times")
            continue
        short = "short" in x.get("kind", "")
        tags = x.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        thumb = x.get("thumbnail") or (x["file"].removesuffix(".mp4") + ".cover.png" if short else None)
        meta = {"title": x["title"], "description_full": x["description"], "tags": tags}
        items.append({"key": key, "when": when, "file": x["file"], "release": rel, "short": short,
                      "thumbnail": thumb, "playlist": scfg.get("playlist_id"), "meta": lambda led, m=meta: m})
    return items


def series_plan(scfg: dict, rels: list[dict]) -> tuple[dict | None, list[dict]]:
    rel = next((r for r in rels if r.get("tag_name") == scfg["release"]), None)
    a = rel and asset(rel, scfg.get("plan", "plan.json"))
    if not a:
        return rel, []
    with tempfile.TemporaryDirectory() as tmp:
        return rel, json.loads(download(a, Path(tmp) / "plan.json").read_text())


def build_queue(cfg: dict, ledger: dict, rels: list[dict], now: dt.datetime,
                notes: list[str] | None = None, plans: dict | None = None) -> list[dict]:
    """Everything still to upload, in order of publish time (\"publish now\" first)."""
    lead = dt.timedelta(hours=cfg.get("schedule", {}).get("min_lead_hours", 2))
    items = story_items(cfg, ledger, rels, released_episodes(rels), now)
    for scfg in cfg.get("series", []):
        rel, plan = (plans or {}).get(scfg["key"]) or series_plan(scfg, rels)
        if rel is None and notes is not None:
            notes.append(f"{scfg['key']}: no release {scfg['release']!r} found")
        items += series_items(scfg, plan, rel, ledger, now, lead, notes)
    order = {id(it): i for i, it in enumerate(items)}
    return sorted(items, key=lambda it: (it["when"] or now, order[id(it)]))


def this_run(queue: list[dict], ledger: dict, cap: int) -> list[dict]:
    """The first `cap` uploads of the queue whose prerequisite (a Short's episode) is up or comes first."""
    out, done = [], set(ledger)
    for it in queue:
        if len(out) >= cap:
            break
        if it.get("needs") and it["needs"] not in done:
            continue
        out.append(it)
        done.add(it["key"])
    return out


def cmd_plan(cfg: dict) -> int:
    """The whole queue, run by run, without uploading (needs only `gh`)."""
    ledger, now, notes = load_ledger(), dt.datetime.now(dt.timezone.utc), []
    queue = build_queue(cfg, ledger, all_releases(), now, notes)
    cap, led, run = cfg.get("max_per_run", 2), dict(ledger), 1
    tz = ZoneInfo(cfg.get("schedule", {}).get("timezone", "Europe/Paris"))
    print(f"{'Enabled' if cfg.get('enabled') else 'DISABLED'}; {len(queue)} upload(s) queued, {cap} per run.")
    while True:
        batch = this_run([it for it in queue if it["key"] not in led], led, cap)
        if not batch:
            break
        for it in batch:
            when = it["when"].astimezone(tz).strftime("%a %d %b %H:%M") if it["when"] else "publish now"
            title = it["meta"]({**led, **{k: {"url": "(its URL)"} for k in [it.get("needs")] if k}}).get("title")
            print(f"run {run:2d}  {it['key']:22s} {when:17s} {'Short' if it['short'] else 'video':5s}  {title}")
            led[it["key"]] = {}
        run += 1
    for n in notes:
        print(n)
    return 0


def cmd_upload(cfg: dict) -> int:
    if not cfg.get("enabled"):
        print("YouTube uploads are disabled (production/youtube.json: enabled = false).")
        return 0
    ledger, now, notes = load_ledger(), dt.datetime.now(dt.timezone.utc), []
    queue = build_queue(cfg, ledger, all_releases(), now, notes)
    for n in notes:
        print(n, flush=True) if ": held" in n else notice(n, "warning")
    batch = this_run(queue, ledger, cfg.get("max_per_run", 2))
    token = access_token()
    check_playlists(token, cfg)                     # stops here, before uploading, if one is wrong
    sync_playlists(token, cfg, ledger)
    if not batch:
        print("Nothing to upload.")
        return 0
    for it in batch:
        upload_item(token, cfg, ledger, it, now)
    notice(f"{len(queue) - len(batch)} upload(s) left in the queue.")
    return 0


def upload_item(token: str, cfg: dict, ledger: dict, it: dict, now: dt.datetime) -> None:
    body = video_body(it["meta"](ledger), cfg, it["when"])
    with tempfile.TemporaryDirectory() as tmp:
        print(f"{it['key']}: uploading ({iso(it['when']) if it['when'] else 'publish now'})", flush=True)
        vid = upload_video(token, download(asset(it["release"], it["file"]), Path(tmp) / it["file"]), body)
        thumb = it.get("thumbnail") and asset(it["release"], it["thumbnail"])
        if thumb:
            set_thumbnail(token, vid, download(thumb, Path(tmp) / thumb["name"]))
    if it.get("playlist"):
        add_to_playlist(token, it["playlist"], vid)
    url = f"https://www.youtube.com/shorts/{vid}" if it["short"] else f"https://www.youtube.com/watch?v={vid}"
    ledger[it["key"]] = {"video_id": vid, "url": url, "publish_at": iso(it["when"] or now),
                         "linked": it["when"] is None}
    save_ledger(ledger)                             # saved after each video: a failure loses nothing
    notice(f"{it['key']}: {url} (public {iso(it['when']) if it['when'] else 'now'})")


# --------------------------------------------------------------- playlists
def playlist_members(cfg: dict, ledger: dict) -> dict[str, list[str]]:
    """playlist id -> the ledger's video ids that belong in it, in order: story episodes (and
    Shorts, if `shorts_playlist_id` is set) by episode, each series' uploads by publish time."""
    out: dict[str, list[str]] = {}
    for key in sorted(k for k in ledger if k.startswith("C")):
        pl = cfg.get("shorts_playlist_id") if key.endswith("-short") else cfg.get("playlist_id")
        if pl:
            out.setdefault(pl, []).append(ledger[key]["video_id"])
    for scfg in cfg.get("series", []):
        keys = sorted((k for k in ledger if k.startswith(scfg["key"] + "-")), key=lambda k: (ledger[k]["publish_at"], k))
        if scfg.get("playlist_id") and keys:
            out.setdefault(scfg["playlist_id"], []).extend(ledger[k]["video_id"] for k in keys)
    return out


def configured_playlists(cfg: dict) -> list[str]:
    ids = [cfg.get("playlist_id"), cfg.get("shorts_playlist_id")] + [s.get("playlist_id") for s in cfg.get("series", [])]
    return list(dict.fromkeys(i for i in ids if i))


def check_playlists(token: str, cfg: dict) -> dict[str, dict]:
    ids = configured_playlists(cfg)
    if not ids:
        return {}
    st, _, body = _request("GET", f"{API}/playlists?part=snippet,contentDetails,status&maxResults=50&id={','.join(ids)}", token)
    found = {it["id"]: it for it in _json(st, body, "Reading the playlists").get("items", [])}
    missing = [i for i in ids if i not in found]
    if missing:
        notice(f"Playlist(s) not found: {', '.join(missing)}", "error")
        raise SystemExit(f"Playlist(s) not found on this channel: {', '.join(missing)}. Nothing was uploaded. "
                         "Copy the full id (the list= part of the playlist's link) into production/youtube.json.")
    return found


def playlist_videos(token: str, pl: str) -> set[str]:
    have, page = set(), ""
    while True:
        st, _, body = _request("GET", f"{API}/playlistItems?part=contentDetails&maxResults=50&playlistId={pl}"
                                      + (f"&pageToken={page}" if page else ""), token)
        data = _json(st, body, "Reading a playlist")
        have |= {it["contentDetails"]["videoId"] for it in data.get("items", [])}
        page = data.get("nextPageToken")
        if not page:
            return have


def sync_playlists(token: str, cfg: dict, ledger: dict) -> None:
    """Add any recorded video missing from its playlist (videos uploaded by hand, or an earlier add
    that failed), in order, before new uploads are appended."""
    for pl, want in playlist_members(cfg, ledger).items():
        have = playlist_videos(token, pl)
        for vid in want:
            if vid not in have:
                add_to_playlist(token, pl, vid)
                notice(f"added {vid} (recorded earlier) to playlist {pl}")


def cmd_link(now: dt.datetime | None = None) -> int:
    """Mark videos whose premiere time has passed; prints how many changed."""
    now = now or dt.datetime.now(dt.timezone.utc)
    ledger = load_ledger()
    changed = 0
    for v in ledger.values():
        if not v.get("linked") and parse_iso(v["publish_at"]) <= now:
            v["linked"] = True
            changed += 1
    if changed:
        save_ledger(ledger)
    print(changed)
    return 0


def have_credentials() -> bool:
    return all(os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))


def cmd_refresh(now: dt.datetime | None = None) -> int:
    """YouTube API Services policy III.E.4: stored API data must be refreshed or deleted within
    30 days. Runs daily: re-checks every stored video ID with videos.list, stamps `refreshed_at`,
    and deletes the entry of any video that no longer exists."""
    now = now or dt.datetime.now(dt.timezone.utc)
    ledger = load_ledger()
    if not ledger:
        print("Nothing stored.")
        return 0
    if not have_credentials():
        print("No YouTube credentials yet: nothing was fetched from the API, nothing to refresh.")
        return 0
    token = access_token()
    ids = sorted({v["video_id"] for v in ledger.values()})
    found: set[str] = set()
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        st, _, body = _request("GET", f"{API}/videos?part=id&maxResults=50&id={','.join(chunk)}", token)
        data = _json(st, body, "Refreshing stored videos")        # stops before deleting anything on error
        found |= {it["id"] for it in data.get("items", [])}
    for eid in list(ledger):
        if ledger[eid]["video_id"] in found:
            ledger[eid]["refreshed_at"] = iso(now)
        else:
            print(f"{eid}: video {ledger[eid]['video_id']} no longer exists; entry deleted")
            del ledger[eid]
    save_ledger(ledger)
    print(f"{len(found)} stored video(s) refreshed")
    return 0


def video_id(text: str) -> str:
    """The 11-character id from a YouTube URL (watch, youtu.be, shorts, studio) or a bare id."""
    import re
    text = text.strip()
    m = re.search(r"(?:v=|youtu\.be/|shorts/|video/|live/)([A-Za-z0-9_-]{11})", text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    raise SystemExit(f"Not a YouTube video link or id: {text!r}")


def cmd_record(episode: str, video: str, when: str | None, tz: str = "Europe/Paris",
               now: dt.datetime | None = None) -> int:
    """Register a video uploaded by hand: the wiki links it once `when` has passed, and the
    uploader treats the episode as done."""
    short = episode.lower().endswith(("s", "-short"))       # "3s" or "C01-E003-short": the episode's Short
    base = episode[:-6] if episode.lower().endswith("-short") else (episode[:-1] if short else episode)
    eid = f"C01-E{int(base):03d}" if base.isdigit() else base
    if not (EPISODES / eid / "packaging.json").exists():
        raise SystemExit(f"No such episode: {eid}")
    vid = video_id(video)
    now = now or dt.datetime.now(dt.timezone.utc)
    if when and when.strip():
        local = dt.datetime.strptime(when.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tz))
        at = local.astimezone(dt.timezone.utc)
    else:
        at = now
    ledger = load_ledger()
    key = f"{eid}-short" if short else eid
    url = f"https://www.youtube.com/shorts/{vid}" if short else f"https://www.youtube.com/watch?v={vid}"
    ledger[key] = {"video_id": vid, "url": url, "publish_at": iso(at), "linked": at <= now, "uploaded": "by hand"}
    save_ledger(ledger)
    print(f"{key}: {url} (public from {iso(at)})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["check", "plan", "upload", "link", "record", "refresh"])
    ap.add_argument("args", nargs="*", help="record: <episode> <video link> [\"YYYY-MM-DD HH:MM\" Paris time]")
    a = ap.parse_args()
    cfg = load_config()
    if a.command == "record":
        if len(a.args) < 2:
            raise SystemExit("record needs: <episode> <video link> [\"YYYY-MM-DD HH:MM\"]")
        return cmd_record(a.args[0], a.args[1], " ".join(a.args[2:]) or None)
    return {"check": lambda: cmd_check(cfg), "plan": lambda: cmd_plan(cfg), "upload": lambda: cmd_upload(cfg),
            "link": cmd_link, "refresh": cmd_refresh}[a.command]()


if __name__ == "__main__":
    raise SystemExit(main())
