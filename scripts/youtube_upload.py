#!/usr/bin/env python3
"""Upload released episodes to YouTube and schedule their premieres.

Runs in GitHub Actions (.github/workflows/youtube.yml). One queue, in order of
publish time, holds everything released and not yet in the ledger
(wiki/data/youtube.json): the story's episodes (in episode order, each at its
premiere in production/schedule.json) and their Shorts (unless `story` is false),
and every upload of the enabled series in production/youtube.json `series` (the
times, titles and descriptions come from a plan: a file in the series' GitHub
release, or, with `repo` and `plan_path`, a file in another repository, whose
releases then hold the videos). Each run uploads the first `max_per_run` of them:
it downloads the MP4 and thumbnail from the release (REST API, so drafts are found
too), uploads and schedules the video, sets the thumbnail and adds it to its
playlists (created on the channel the first time they are needed). Once a video's
time has passed, `link` marks it live so the wiki shows "Watch on YouTube".

Since 15 Nov 2026 the channel is Timeslip Ramen (@TimeslipRamenShop, formerly
@Nat20px): the story and The Pit are off, and series `tsr-s1` uploads Timeslip
Ramen's Season 1 from Nat20-Pixel-Saga/TimeSlipRamen. Every run keeps to a daily
quota budget (`daily_quota_budget`: units of YouTube's shared 10,000-a-day pool,
counted per Pacific day in wiki/data/youtube-quota.json; uploads have their own
bucket of 100 a day) and stops early rather than run out mid-way.

    python scripts/youtube_upload.py check       # verify the credentials (prints the channel)
    python scripts/youtube_upload.py plan        # the whole queue, night by night (no upload, no credentials)
    python scripts/youtube_upload.py upload      # upload and schedule
    python scripts/youtube_upload.py link        # mark videos whose slot has passed as live
    python scripts/youtube_upload.py refresh     # re-check stored video IDs (YouTube's 30-day rule)
    python scripts/youtube_upload.py record 3 https://youtu.be/abc123 "2026-10-08 21:00"
                                                 # register a video uploaded by hand (Paris time)
    python scripts/youtube_upload.py unschedule --series=pit-s1
                                                 # keep scheduled uploads from going public
    python scripts/youtube_upload.py hide [--dry-run]
                                                 # make private every video and playlist that is not the current show's

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
REPLACED = ROOT / "wiki" / "data" / "youtube-replaced.json"     # uploads swapped out by `requeue`
PLAYLISTS = ROOT / "wiki" / "data" / "youtube-playlists.json"   # series playlists created by the uploader
QUOTA = ROOT / "wiki" / "data" / "youtube-quota.json"           # API units spent today (Pacific day)
HIDDEN = ROOT / "wiki" / "data" / "youtube-hidden.json"         # videos and playlists made private by `hide`
PACIFIC = ZoneInfo("America/Los_Angeles")                       # YouTube's quota resets at midnight Pacific
QUOTA_TRACK = False                                             # main() turns it on (tests stay side-effect free)
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


def notice(line: str, level: str = "notice", title: str = "YouTube") -> None:
    """Print a line (or several); in GitHub Actions also show it on the run's summary page
    (one annotation, so a long report is not cut by the 10-per-step limit)."""
    print(line, flush=True)
    if os.environ.get("GITHUB_ACTIONS"):
        esc = line.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::{level} title={title}::{esc}", flush=True)


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


def retext(text: str, cfg: dict) -> str:
    """Apply the config's `retext` rules ({"find", "replace"}) to a description: sentences that stopped being
    true after upload (the story's weekday promise once Act 1 ended, the Pit's 100-subscriber unlock)."""
    for rule in cfg.get("retext", []):
        text = text.replace(rule["find"], rule["replace"])
    return text


def video_body(pk: dict, cfg: dict, publish_at: dt.datetime | None) -> dict:
    status = {"selfDeclaredMadeForKids": bool(cfg.get("made_for_kids", False)),
              "containsSyntheticMedia": bool(cfg.get("contains_synthetic_media", False)),
              "license": "youtube", "embeddable": True}
    if publish_at is not None:
        status.update(privacyStatus="private", publishAt=iso(publish_at))
    else:
        status["privacyStatus"] = cfg.get("privacy", "public")
    snippet = {"title": clean_text(pk["title"], 100),
               "description": clean_text(retext(pk.get("description_full") or pk["description"], cfg), 5000),
               "tags": clean_tags(pk.get("tags", [])),
               "categoryId": str(cfg.get("category_id", "24")),
               "defaultLanguage": cfg.get("language", "en"),
               "defaultAudioLanguage": cfg.get("language", "en")}
    return {"snippet": snippet, "status": status}


# -------------------------------------------------------------------- HTTP
def _quota_cost(method: str, url: str) -> int:
    """Units this call takes from the shared 10,000-a-day pool: 50 for a write (thumbnail, playlist, update).
    Uploads (videos.insert) have had their own bucket since June 2026, 100 a day at 1 unit each, so they cost
    nothing here; reads (1 unit each) are left out too, so a run that only reads changes nothing on disk, and
    the budget's margin below 10,000 covers them."""
    if not url.startswith(("https://www.googleapis.com/youtube/", "https://www.googleapis.com/upload/youtube/")):
        return 0
    if method == "GET" or url.startswith(f"{UPLOAD}/videos"):
        return 0
    return 50


def quota_today(now: dt.datetime | None = None) -> int:
    day = (now or dt.datetime.now(dt.timezone.utc)).astimezone(PACIFIC).date().isoformat()
    q = json.loads(QUOTA.read_text()) if QUOTA.exists() else {}
    return q.get("units", 0) if q.get("day") == day else 0


def spend(units: int, now: dt.datetime | None = None) -> None:
    if not units or not QUOTA_TRACK:
        return
    day = (now or dt.datetime.now(dt.timezone.utc)).astimezone(PACIFIC).date().isoformat()
    QUOTA.write_text(json.dumps({"day": day, "units": quota_today(now) + units}) + "\n")


def _request(method: str, url: str, token: str | None = None, data: bytes | None = None,
             headers: dict | None = None) -> tuple[int, dict, bytes]:
    spend(_quota_cost(method, url))
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
        notice(f"{video_id}: thumbnail not set ({st}): {resp.decode(errors='replace')[:300]}", "warning")


def ensure_playlists(token: str, cfg: dict) -> dict[str, dict[str, str]]:
    """series key -> {playlist name: id} for the enabled series' named playlists (`playlists` in a series'
    config: name -> id, or null to have the uploader find the playlist by its title on the channel or create
    it, public, with the description given in `playlist_descriptions`). Ids are kept in
    wiki/data/youtube-playlists.json. Quota: 1 unit per 50 playlists read, 50 per playlist created."""
    stored = json.loads(PLAYLISTS.read_text()) if PLAYLISTS.exists() else {}
    mine: dict[str, str] | None = None
    changed = False
    for scfg in active_series(cfg):
        want = scfg.get("playlists") or {}
        have = stored.setdefault(scfg["key"], {})
        for name, pid in want.items():
            if pid and have.get(name) != pid:
                have[name], changed = pid, True
        for name in [n for n in want if not have.get(n)]:
            if mine is None:
                mine, page = {}, ""
                while True:
                    st, _, body = _request("GET", f"{API}/playlists?part=snippet&mine=true&maxResults=50"
                                                  + (f"&pageToken={page}" if page else ""), token)
                    data = _json(st, body, "Reading the channel's playlists")
                    for it in data.get("items", []):
                        mine.setdefault(it["snippet"]["title"], it["id"])
                    page = data.get("nextPageToken")
                    if not page:
                        break
            if name in mine:
                have[name] = mine[name]
            else:
                body = {"snippet": {"title": clean_text(name, 150),
                                    "description": clean_text((scfg.get("playlist_descriptions") or {}).get(name, ""), 5000),
                                    "defaultLanguage": scfg.get("language", cfg.get("language", "en"))},
                        "status": {"privacyStatus": "public"}}
                st, _, resp = _request("POST", f"{API}/playlists?part=snippet,status", token,
                                       json.dumps(body).encode(), {"Content-Type": "application/json"})
                have[name] = _json(st, resp, f"Creating the playlist {name!r}")["id"]
                notice(f"created playlist {name!r}: {have[name]}")
            changed = True
    if changed:
        PLAYLISTS.write_text(json.dumps(stored, indent=1, ensure_ascii=False) + "\n")
    return stored


def add_to_playlist(token: str, playlist_id: str, video_id: str) -> None:
    body = {"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}
    st, _, resp = _request("POST", f"{API}/playlistItems?part=snippet", token, json.dumps(body).encode(),
                           {"Content-Type": "application/json"})
    if st >= 400:
        notice(f"{video_id}: not added to playlist {playlist_id} ({st}): {resp.decode(errors='replace')[:300]}", "warning")


# ---------------------------------------------------------------- releases
def repo() -> str:
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    return json.loads((ROOT / "wiki" / "data" / "site.json").read_text())["repo"]


def gh_api(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True).stdout
    return json.loads(out) if out.strip() else None


def all_releases(r: str | None = None) -> list[dict]:
    """Every release of this repository (or of `r`), drafts included (they need push access: the workflow's
    token has it). The REST API is used rather than `gh release view`, which cannot always find a draft."""
    out, page = [], 1
    while True:
        batch = gh_api(f"repos/{r or repo()}/releases?per_page=100&page={page}")
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
    url = a.get("url", "")
    path = url.split("api.github.com/", 1)[1] if "api.github.com/" in url else f"repos/{repo()}/releases/assets/{a['id']}"
    with dest.open("wb") as fh:
        subprocess.run(["gh", "api", "-H", "Accept: application/octet-stream", path], stdout=fh, check=True)
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
    ledger, report = load_ledger(), []
    for pid, pl in check_playlists(token, cfg).items():
        have = playlist_videos(token, pid)
        want = set(playlist_members(cfg, ledger).get(pid, []))
        missing = [k for k in sorted(ledger) if ledger[k]["video_id"] in want - have]
        report.append(f"Playlist {pid}: {pl['snippet']['title']!r} ({pl['status']['privacyStatus']}, {len(have)} items): "
                      f"holds {len(want & have)} of the {len(want)} recorded videos that belong in it"
                      + (f" (missing: {', '.join(missing)}; the next upload run adds them)" if missing else "")
                      + f"; {len(have - {v['video_id'] for v in ledger.values()})} other videos")
    ids = sorted({v["video_id"] for v in ledger.values()})
    items = {}
    for i in range(0, len(ids), 50):                # read-only: videos.list, 1 unit per call
        st, _, body = _request("GET", f"{API}/videos?part=status,liveStreamingDetails&maxResults=50"
                                      f"&id={','.join(ids[i:i + 50])}", token)
        items.update({it["id"]: it for it in _json(st, body, "Reading the stored videos").get("items", [])})
    for key in sorted(ledger):
        report.append(describe_status(key, ledger[key], items.get(ledger[key]["video_id"])))
    notice("\n".join(report), title="YouTube status")
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


BODY_KEYS = ("category_id", "language", "made_for_kids", "contains_synthetic_media")


def series_items(scfg: dict, plan: list[dict], rels, ledger: dict, now: dt.datetime, lead: dt.timedelta,
                 notes: list[str] | None = None) -> list[dict]:
    """Uploads of a series from its plan: each at its own time (`when`, or `date` and `time`), from its
    release (`release` in the item, else the series'). One without a time (the subscriber-unlock bonus)
    waits until `times` in the config gives it one; one whose time is already too close is left out and
    reported, never published early or late. Thumbnail: `thumbnail` or `thumb_a` (or a Short's `thumb`,
    unless `short_thumbnails` is false); playlists: the series' `playlist_id` and the item's `playlists`
    (names); tags: the item's, its `visitors`, then the series' `tags`."""
    tz = scfg.get("timezone", "Europe/Paris")
    if isinstance(rels, dict) or rels is None:
        rels = [rels] if rels else []
    by_tag = {r.get("tag_name"): r for r in rels}
    body = {k: scfg[k] for k in BODY_KEYS if k in scfg}
    items = []
    for x in plan:
        key = f"{scfg['key']}-{x['id']}"
        if key in ledger:
            continue
        own = x.get("when") or (f"{x['date']} {x['time']}" if x.get("date") and x.get("time") else None)
        when_s = (scfg.get("times") or {}).get(x["id"], own)
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
        tag = x.get("release") or scfg.get("release")
        rel = by_tag.get(tag) or (rels[0] if len(rels) == 1 and not x.get("release") else None)
        if rel is None:
            if notes is not None:
                notes.append(f"{key}: release {tag!r} not found, so it was not uploaded")
            continue
        short = "short" in x.get("kind", "")
        tags = x.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        tags = list(tags) + list(x.get("visitors") or []) + list(scfg.get("tags") or [])
        if short and scfg.get("tags"):
            tags.append("shorts")
        if short and scfg.get("short_thumbnails") is False:
            thumb = None
        else:
            thumb = (x.get("thumbnail") or x.get("thumb_a") or x.get("thumb")
                     or (x["file"].removesuffix(".mp4") + ".cover.png" if short else None))
        meta = {"title": x["title"], "description_full": x["description"], "tags": tags}
        items.append({"key": key, "when": when, "file": x["file"], "release": rel, "short": short,
                      "thumbnail": thumb, "playlist": scfg.get("playlist_id"), "playlists": list(x.get("playlists") or []),
                      "series": scfg["key"], "body": body, "meta": lambda led, m=meta: m})
    return items


def active_series(cfg: dict) -> list[dict]:
    return [s for s in cfg.get("series", []) if s.get("enabled", True)]


def series_plan(scfg: dict, rels: list[dict]) -> tuple[list[dict], list[dict]]:
    """The series' releases and its plan: the plan file in its release, or (`repo` + `plan_path`) a file on
    the default branch of the series' own repository, whose releases then hold the videos."""
    srels = all_releases(scfg["repo"]) if scfg.get("repo") else rels
    if scfg.get("repo") and scfg.get("plan_path"):
        raw = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.raw",
                              f"repos/{scfg['repo']}/contents/{scfg['plan_path']}"],
                             capture_output=True, text=True, check=True).stdout
        return srels, json.loads(raw)
    rel = next((r for r in srels if r.get("tag_name") == scfg["release"]), None)
    a = rel and asset(rel, scfg.get("plan", "plan.json"))
    if not a:
        return ([rel] if rel else []), []
    with tempfile.TemporaryDirectory() as tmp:
        return [rel], json.loads(download(a, Path(tmp) / "plan.json").read_text())


def build_queue(cfg: dict, ledger: dict, rels: list[dict], now: dt.datetime,
                notes: list[str] | None = None, plans: dict | None = None) -> list[dict]:
    """Everything still to upload, in order of publish time (\"publish now\" first)."""
    lead = dt.timedelta(hours=cfg.get("schedule", {}).get("min_lead_hours", 2))
    items = story_items(cfg, ledger, rels, released_episodes(rels), now) if cfg.get("story", True) else []
    for scfg in active_series(cfg):
        srels, plan = (plans or {}).get(scfg["key"]) or series_plan(scfg, rels)
        if not srels and notes is not None:
            notes.append(f"{scfg['key']}: no release {scfg.get('release') or scfg.get('repo')!r} found")
        items += series_items(scfg, plan, srels, ledger, now, lead, notes)
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
    cap = int(os.environ.get("MAX_PER_RUN") or cfg.get("max_per_run", 2))
    batch = this_run(queue, ledger, cap)
    token = access_token()
    check_playlists(token, cfg)                     # stops here, before uploading, if one is wrong
    plmaps = ensure_playlists(token, cfg)
    sync_playlists(token, cfg, ledger)
    if not batch:
        print("Nothing to upload.")
        return 0
    budget, done = int(cfg.get("daily_quota_budget", 9000)), 0
    for it in batch:
        cost = (50 if it.get("thumbnail") else 0) + 50 * (len(it.get("playlists", [])) + bool(it.get("playlist")))
        if QUOTA_TRACK and quota_today() + cost > budget:
            notice(f"Stopped before {it['key']}: today's YouTube quota budget ({budget} units, {quota_today()} spent) "
                   "would run out; the next run carries on.", "warning")
            break
        upload_item(token, cfg, ledger, it, now, plmaps.get(it.get("series"), {}))
        done += 1
    notice(f"{len(queue) - done} upload(s) left in the queue.")
    return 0


def upload_item(token: str, cfg: dict, ledger: dict, it: dict, now: dt.datetime,
                plmap: dict[str, str] | None = None) -> None:
    body = video_body(it["meta"](ledger), {**cfg, **(it.get("body") or {})}, it["when"])
    with tempfile.TemporaryDirectory() as tmp:
        print(f"{it['key']}: uploading ({iso(it['when']) if it['when'] else 'publish now'})", flush=True)
        vid = upload_video(token, download(asset(it["release"], it["file"]), Path(tmp) / it["file"]), body)
        thumb = it.get("thumbnail") and asset(it["release"], it["thumbnail"])
        if thumb:
            set_thumbnail(token, vid, download(thumb, Path(tmp) / thumb["name"]))
    named = [(plmap or {}).get(n) for n in it.get("playlists", [])]
    for n, pid in zip(it.get("playlists", []), named):
        if not pid:
            notice(f"{it['key']}: playlist {n!r} has no id, so the video was not added to it", "warning")
    pls = ([it["playlist"]] if it.get("playlist") else []) + [p for p in named if p]
    for pid in pls:
        add_to_playlist(token, pid, vid)
    url = f"https://www.youtube.com/shorts/{vid}" if it["short"] else f"https://www.youtube.com/watch?v={vid}"
    ledger[it["key"]] = {"video_id": vid, "url": url, "publish_at": iso(it["when"] or now),
                         "linked": it["when"] is None}
    if it.get("playlists"):
        ledger[it["key"]]["playlists"] = [p for p in named if p]
    save_ledger(ledger)                             # saved after each video: a failure loses nothing
    notice(f"{it['key']}: {url} (public {iso(it['when']) if it['when'] else 'now'})")


# --------------------------------------------------------------- playlists
def playlist_members(cfg: dict, ledger: dict) -> dict[str, list[str]]:
    """playlist id -> the ledger's video ids that belong in it, in order: story episodes (and
    Shorts, if `shorts_playlist_id` is set) by episode, each series' uploads by publish time."""
    out: dict[str, list[str]] = {}
    for key in sorted(k for k in ledger if k.startswith("C") and cfg.get("story", True)):
        pl = cfg.get("shorts_playlist_id") if key.endswith("-short") else cfg.get("playlist_id")
        if pl:
            out.setdefault(pl, []).append(ledger[key]["video_id"])
    for scfg in active_series(cfg):
        keys = sorted((k for k in ledger if k.startswith(scfg["key"] + "-") and not ledger[k].get("unscheduled")),
                      key=lambda k: (ledger[k]["publish_at"], k))
        if scfg.get("playlist_id") and keys:
            out.setdefault(scfg["playlist_id"], []).extend(ledger[k]["video_id"] for k in keys)
        for k in keys:
            for pid in ledger[k].get("playlists", []):
                out.setdefault(pid, []).append(ledger[k]["video_id"])
    return out


def configured_playlists(cfg: dict) -> list[str]:
    ids = ([cfg.get("playlist_id"), cfg.get("shorts_playlist_id")] if cfg.get("story", True) else []) + \
          [s.get("playlist_id") for s in active_series(cfg)]
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
        if not v.get("linked") and not v.get("unscheduled") and not v.get("hidden") and parse_iso(v["publish_at"]) <= now:
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


def cmd_retext(cfg: dict) -> int:
    """Apply the `retext` rules to the descriptions of videos already on YouTube (every video in the ledger,
    public or scheduled). Idempotent: a description the rules no longer change is left alone. Quota: 1 unit per 50
    videos read, 50 per video changed."""
    rules = cfg.get("retext", [])
    ledger = load_ledger()
    if not rules or not ledger:
        print("No retext rules, or nothing stored.")
        return 0
    if not have_credentials():
        print("No YouTube credentials: nothing changed.")
        return 0
    token = access_token()
    keys = {v["video_id"]: k for k, v in ledger.items()}
    ids = sorted(keys)
    changed = failed = 0
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        st, _, body = _request("GET", f"{API}/videos?part=snippet&maxResults=50&id={','.join(chunk)}", token)
        for item in _json(st, body, "Reading descriptions").get("items", []):
            sn = item["snippet"]
            new = clean_text(retext(sn.get("description", ""), cfg), 5000)
            if new == sn.get("description", ""):
                continue
            snippet = {k: sn[k] for k in ("title", "tags", "categoryId", "defaultLanguage", "defaultAudioLanguage")
                       if k in sn}
            snippet["description"] = new
            st2, _, resp = _request("PUT", f"{API}/videos?part=snippet", token,
                                    json.dumps({"id": item["id"], "snippet": snippet}).encode(),
                                    {"Content-Type": "application/json"})
            if st2 >= 400:
                failed += 1
                notice(f"{keys[item['id']]}: description not updated ({st2}): {resp.decode(errors='replace')[:300]}",
                       "warning")
            else:
                changed += 1
                print(f"{keys[item['id']]}: description updated", flush=True)
    notice(f"retext: {changed} description(s) updated" + (f", {failed} failed" if failed else ""))
    return 0


STATUS_KEEP = ("license", "embeddable", "publicStatsViewable", "selfDeclaredMadeForKids", "containsSyntheticMedia")


def cmd_requeue(keys: list[str], now: dt.datetime | None = None) -> int:
    """Swap out scheduled uploads so the next upload run uploads them again from the current release (after a
    re-render). Each old upload is made private with no publish time, so it never goes public, and its title
    gets "[old cut] " in front so it is easy to find and delete in Studio; its ledger entry moves to
    wiki/data/youtube-replaced.json. Refuses anything already public. Quota: 1 unit to read, 50 per video."""
    now = now or dt.datetime.now(dt.timezone.utc)
    if not keys:
        raise SystemExit("requeue needs one or more ledger keys, e.g. pit-s1-e07-full")
    ledger = load_ledger()
    unknown = [k for k in keys if k not in ledger]
    if unknown:
        raise SystemExit(f"Not in the ledger: {', '.join(unknown)}")
    public = [k for k in keys if parse_iso(ledger[k]["publish_at"]) <= now + dt.timedelta(minutes=30)]
    if public:
        raise SystemExit(f"Already public (or about to be), left alone: {', '.join(public)}")
    if not have_credentials():
        raise SystemExit("No YouTube credentials: nothing changed.")
    token = access_token()
    ids = {ledger[k]["video_id"]: k for k in keys}
    st, _, body = _request("GET", f"{API}/videos?part=snippet,status&id={','.join(ids)}", token)
    found = {it["id"]: it for it in _json(st, body, "Reading the uploads").get("items", [])}
    replaced = json.loads(REPLACED.read_text()) if REPLACED.exists() else {}
    for vid, key in ids.items():
        it = found.get(vid)
        if it:
            sn, stt = it["snippet"], it["status"]
            snippet = {k: sn[k] for k in ("title", "description", "tags", "categoryId", "defaultLanguage",
                                          "defaultAudioLanguage") if k in sn}
            if not snippet["title"].startswith("[old cut] "):
                snippet["title"] = ("[old cut] " + snippet["title"])[:100]
            status = {k: stt[k] for k in STATUS_KEEP if k in stt}
            status["privacyStatus"] = "private"            # no publishAt: it stays private
            st2, _, resp = _request("PUT", f"{API}/videos?part=snippet,status", token,
                                    json.dumps({"id": vid, "snippet": snippet, "status": status}).encode(),
                                    {"Content-Type": "application/json"})
            _json(st2, resp, f"{key}: unscheduling {vid}")
            print(f"{key}: {vid} is now private, unscheduled, titled '{snippet['title']}'", flush=True)
        else:
            print(f"{key}: {vid} no longer exists on YouTube", flush=True)
        replaced.setdefault(key, []).append({**ledger.pop(key), "replaced_at": iso(now)})
    save_ledger(ledger)
    REPLACED.write_text(json.dumps(dict(sorted(replaced.items())), indent=1, ensure_ascii=False) + "\n")
    notice(f"requeue: {len(ids)} upload(s) swapped out; the next upload run uploads them again")
    return 0


def cmd_unschedule(args: list[str], now: dt.datetime | None = None) -> int:
    """Keep scheduled uploads from going public (a series dropped, the channel changed): each becomes private
    with no publish time; its ledger entry stays, marked `unscheduled`, so it is never uploaded again.
    `--series=KEY` takes every upload of that series that is not public yet. Undo in Studio (give it a time
    or make it public). Quota: 1 unit per 50 videos read, 50 per video changed."""
    now = now or dt.datetime.now(dt.timezone.utc)
    ledger = load_ledger()
    keys: list[str] = []
    for a in args:
        if a.startswith("--series="):
            keys += sorted(k for k in ledger if k.startswith(a.split("=", 1)[1] + "-"))
        else:
            keys.append(a)
    keys = list(dict.fromkeys(keys))
    if not keys:
        raise SystemExit("unschedule needs ledger keys or --series=KEY")
    unknown = [k for k in keys if k not in ledger]
    if unknown:
        raise SystemExit(f"Not in the ledger: {', '.join(unknown)}")
    soon = now + dt.timedelta(minutes=30)
    todo = [k for k in keys if not ledger[k].get("unscheduled") and parse_iso(ledger[k]["publish_at"]) > soon]
    left = [k for k in keys if k not in todo and not ledger[k].get("unscheduled")]
    if left:
        print(f"Already public (or about to be), left alone: {', '.join(left)}")
    if not todo:
        print("Nothing to unschedule.")
        return 0
    if not have_credentials():
        raise SystemExit("No YouTube credentials: nothing changed.")
    token = access_token()
    ids = {ledger[k]["video_id"]: k for k in todo}
    found: dict[str, dict] = {}
    vids = list(ids)
    for i in range(0, len(vids), 50):
        st, _, body = _request("GET", f"{API}/videos?part=status&id={','.join(vids[i:i + 50])}", token)
        found |= {it["id"]: it for it in _json(st, body, "Reading the uploads").get("items", [])}
    done = 0
    for vid, key in ids.items():
        it = found.get(vid)
        if it:
            status = {k: it["status"][k] for k in STATUS_KEEP if k in it["status"]}
            status["privacyStatus"] = "private"            # no publishAt: it stays private
            st2, _, resp = _request("PUT", f"{API}/videos?part=status", token,
                                    json.dumps({"id": vid, "status": status}).encode(),
                                    {"Content-Type": "application/json"})
            _json(st2, resp, f"{key}: unscheduling {vid}")
            print(f"{key}: {vid} is now private, with no publish time", flush=True)
        else:
            print(f"{key}: {vid} no longer exists on YouTube", flush=True)
        ledger[key].update(unscheduled=iso(now), linked=False)
        save_ledger(ledger)
        done += 1
    notice(f"unschedule: {done} upload(s) will not go public")
    return 0


def _paged(token: str, url: str, what: str) -> list[dict]:
    out, page = [], ""
    while True:
        st, _, body = _request("GET", url + (f"&pageToken={page}" if page else ""), token)
        data = _json(st, body, what)
        out += data.get("items", [])
        page = data.get("nextPageToken")
        if not page:
            return out


def cmd_hide(args: list[str], now: dt.datetime | None = None) -> int:
    """Make private every video and playlist on the channel that is not the current show's: everything except
    the uploads of the enabled series (their ledger entries) and their playlists. For when a channel changes
    hands (15 Nov 2026: Nat20 Pixels Saga became Timeslip Ramen). Videos already private are left alone. Each
    one changed is listed, with its earlier visibility, in wiki/data/youtube-hidden.json, so it can be undone in
    Studio; its ledger entry (if any) is marked `hidden` and loses its wiki link. `--dry-run` only lists.
    Quota: a few units to read, 50 per video or playlist changed."""
    now = now or dt.datetime.now(dt.timezone.utc)
    dry = "--dry-run" in args
    cfg, ledger = load_config(), load_ledger()
    if not have_credentials():
        raise SystemExit("No YouTube credentials: nothing changed.")
    token = access_token()
    keep_keys = {k for s in active_series(cfg) for k in ledger if k.startswith(s["key"] + "-")}
    keep = {ledger[k]["video_id"] for k in keep_keys}
    stored = json.loads(PLAYLISTS.read_text()) if PLAYLISTS.exists() else {}
    keep_pl = {pid for s in active_series(cfg) for pid in list((stored.get(s["key"]) or {}).values())
               + list((s.get("playlists") or {}).values()) + [s.get("playlist_id")] if pid}
    st, _, body = _request("GET", f"{API}/channels?part=contentDetails,snippet&mine=true", token)
    ch = _json(st, body, "Reading the channel")["items"][0]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f"Channel: {ch['snippet']['title']}; keeping {len(keep)} upload(s) of "
          f"{', '.join(s['key'] for s in active_series(cfg))} and {len(keep_pl)} playlist(s)", flush=True)
    ids = list(dict.fromkeys(it["contentDetails"]["videoId"] for it in
               _paged(token, f"{API}/playlistItems?part=contentDetails&maxResults=50&playlistId={uploads}", "Listing uploads")))
    videos: list[dict] = []
    for i in range(0, len(ids), 50):
        st, _, body = _request("GET", f"{API}/videos?part=snippet,status&id={','.join(ids[i:i + 50])}", token)
        videos += _json(st, body, "Reading the uploads").get("items", [])
    todo = [v for v in videos if v["id"] not in keep and v["status"]["privacyStatus"] != "private"]
    pls = _paged(token, f"{API}/playlists?part=snippet,status&mine=true&maxResults=50", "Listing playlists")
    todo_pl = [p for p in pls if p["id"] not in keep_pl and p["status"]["privacyStatus"] != "private"]
    print(f"{len(videos)} video(s) on the channel, {len(todo)} to make private; "
          f"{len(pls)} playlist(s), {len(todo_pl)} to make private", flush=True)
    by_vid = {v["video_id"]: k for k, v in ledger.items()}
    hidden = json.loads(HIDDEN.read_text()) if HIDDEN.exists() else {"videos": [], "playlists": []}
    for v in todo:
        was = v["status"]["privacyStatus"]
        line = f"{v['id']} ({was}) {v['snippet']['title']}"
        if dry:
            print(f"would hide {line}", flush=True)
            continue
        status = {k: v["status"][k] for k in STATUS_KEEP if k in v["status"]}
        status["privacyStatus"] = "private"
        st2, _, resp = _request("PUT", f"{API}/videos?part=status", token,
                                json.dumps({"id": v["id"], "status": status}).encode(), {"Content-Type": "application/json"})
        if st2 >= 400:
            notice(f"{v['id']}: not made private ({st2}): {resp.decode(errors='replace')[:300]}", "warning")
            continue
        hidden["videos"].append({"id": v["id"], "title": v["snippet"]["title"], "was": was, "at": iso(now)})
        if v["id"] in by_vid:
            ledger[by_vid[v["id"]]].update(hidden=iso(now), linked=False)
        print(f"hid {line}", flush=True)
    for p in todo_pl:
        was = p["status"]["privacyStatus"]
        line = f"playlist {p['id']} ({was}) {p['snippet']['title']}"
        if dry:
            print(f"would hide {line}", flush=True)
            continue
        st2, _, resp = _request("PUT", f"{API}/playlists?part=snippet,status", token, json.dumps(
            {"id": p["id"], "snippet": {k: p["snippet"][k] for k in ("title", "description", "defaultLanguage")
                                        if k in p["snippet"]}, "status": {"privacyStatus": "private"}}).encode(),
            {"Content-Type": "application/json"})
        if st2 >= 400:
            notice(f"{p['id']}: playlist not made private ({st2}): {resp.decode(errors='replace')[:300]}", "warning")
            continue
        hidden["playlists"].append({"id": p["id"], "title": p["snippet"]["title"], "was": was, "at": iso(now)})
        print(f"hid {line}", flush=True)
    if not dry:
        save_ledger(ledger)
        HIDDEN.write_text(json.dumps(hidden, indent=1, ensure_ascii=False) + "\n")
        notice(f"hide: {len([h for h in hidden['videos'] if h['at'] == iso(now)])} video(s) and "
               f"{len([h for h in hidden['playlists'] if h['at'] == iso(now)])} playlist(s) made private")
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
    ap.add_argument("command", choices=["check", "plan", "upload", "link", "record", "refresh", "retext", "requeue",
                                        "unschedule", "hide"])
    ap.add_argument("args", nargs="*", help="record: <episode> <video link> [\"YYYY-MM-DD HH:MM\" Paris time]; "
                                             "requeue: <ledger key> ...; unschedule: <ledger key> ... or --series=KEY")
    a, extra = ap.parse_known_args()
    if extra and a.command not in ("requeue", "unschedule", "hide"):
        ap.error(f"unrecognized arguments: {' '.join(extra)}")
    a.args += extra                                 # e.g. unschedule --series=pit-s1
    global QUOTA_TRACK
    QUOTA_TRACK = True
    cfg = load_config()
    if a.command == "record":
        if len(a.args) < 2:
            raise SystemExit("record needs: <episode> <video link> [\"YYYY-MM-DD HH:MM\"]")
        return cmd_record(a.args[0], a.args[1], " ".join(a.args[2:]) or None)
    if a.command == "requeue":
        return cmd_requeue([k for arg in a.args for k in arg.replace(",", " ").split()])
    if a.command == "unschedule":
        return cmd_unschedule([k for arg in a.args for k in arg.replace(",", " ").split()])
    if a.command == "hide":
        return cmd_hide(a.args)
    return {"check": lambda: cmd_check(cfg), "plan": lambda: cmd_plan(cfg), "upload": lambda: cmd_upload(cfg),
            "link": cmd_link, "refresh": cmd_refresh, "retext": lambda: cmd_retext(cfg)}[a.command]()


if __name__ == "__main__":
    raise SystemExit(main())
