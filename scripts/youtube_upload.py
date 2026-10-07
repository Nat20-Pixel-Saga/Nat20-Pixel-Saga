#!/usr/bin/env python3
"""Upload released episodes to YouTube and schedule their premieres.

Runs in GitHub Actions (.github/workflows/youtube.yml). For every episode that
has a GitHub release but is not yet in the ledger (wiki/data/youtube.json), in
episode order, it downloads the release's MP4 and thumbnail, uploads the video
with the packaging's title, description, tags and chapters, sets the thumbnail,
adds it to the playlist, and schedules it for the next free slot in
production/youtube.json (weekdays at a fixed local time by default). Once a
video's slot has passed, `link` marks it live so the wiki shows "Watch on
YouTube".

    python scripts/youtube_upload.py check       # verify the credentials (prints the channel)
    python scripts/youtube_upload.py plan        # show what would be uploaded and when (no upload)
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


# ---------------------------------------------------------------- episodes
def released_episodes() -> list[str]:
    """Committed episodes that have a GitHub release, in order."""
    world = json.loads((ROOT / "state" / "world.json").read_text())
    reached = (world["series"]["campaign"], world["series"]["episode_in_campaign"])
    out = []
    for d in sorted(EPISODES.glob("C??-E???")):
        eid = d.name
        if (int(eid[1:3]), int(eid[-3:])) > reached or not (d / "packaging.json").exists():
            continue
        if subprocess.run(["gh", "release", "view", eid], capture_output=True).returncode == 0:
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
def cmd_check() -> int:
    token = access_token()
    st, _, body = _request("GET", f"{API}/channels?part=snippet,status&mine=true", token)
    data = _json(st, body, "Reading the channel")
    for ch in data.get("items", []):
        print(f"Authorised for channel: {ch['snippet']['title']} (id {ch['id']}); "
              f"long uploads: {ch.get('status', {}).get('longUploadsStatus', '?')}")
    if not data.get("items"):
        print("Authorised, but this Google account has no YouTube channel yet.")
    ledger = load_ledger()
    ids = sorted({v["video_id"] for v in ledger.values()})
    items = {}
    for i in range(0, len(ids), 50):                # read-only: videos.list, 1 unit per call
        st, _, body = _request("GET", f"{API}/videos?part=status,liveStreamingDetails&maxResults=50"
                                      f"&id={','.join(ids[i:i + 50])}", token)
        items.update({it["id"]: it for it in _json(st, body, "Reading the stored videos").get("items", [])})
    for key in sorted(ledger):
        line = describe_status(key, ledger[key], items.get(ledger[key]["video_id"]))
        print(line)
        if os.environ.get("GITHUB_ACTIONS"):            # also shown on the run's summary page
            print(f"::notice title=YouTube {key}::{line}")
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


def cmd_plan(cfg: dict) -> int:
    ledger = load_ledger()
    todo = pending(ledger, released_episodes())[: cfg.get("max_per_run", 5)]
    slots = schedule_for(cfg, ledger, todo, dt.datetime.now(dt.timezone.utc))
    for eid in todo:
        pk = json.loads((EPISODES / eid / "packaging.json").read_text())
        when = iso(slots[eid]) if slots[eid] else cfg.get("privacy", "public") + " now"
        print(f"{eid}  {when}  {pk['title']}")
    if not todo:
        print("Nothing to upload.")
    return 0


def cmd_upload(cfg: dict) -> int:
    if not cfg.get("enabled"):
        print("YouTube uploads are disabled (production/youtube.json: enabled = false).")
        return 0
    ledger = load_ledger()
    released = released_episodes()
    cap = cfg.get("max_per_run", 5)
    todo = pending(ledger, released)[:cap]
    shorts_todo = [e for e in released if e in ledger and f"{e}-short" not in ledger]
    if not todo and not shorts_todo:
        print("Nothing to upload.")
        return 0
    token = access_token()
    slots = schedule_for(cfg, ledger, todo, dt.datetime.now(dt.timezone.utc))
    for eid in todo:
        pk = json.loads((EPISODES / eid / "packaging.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["gh", "release", "download", eid, "-p", f"{eid}.mp4", "-p", f"{eid}-thumbnail.png",
                            "-D", tmp], check=True)
            print(f"{eid}: uploading ({slots[eid] and iso(slots[eid]) or 'publish now'})", flush=True)
            vid = upload_video(token, Path(tmp) / f"{eid}.mp4", video_body(pk, cfg, slots[eid]))
            set_thumbnail(token, vid, Path(tmp) / f"{eid}-thumbnail.png")
        if cfg.get("playlist_id"):
            add_to_playlist(token, cfg["playlist_id"], vid)
        ledger[eid] = {"video_id": vid, "url": f"https://www.youtube.com/watch?v={vid}",
                       "publish_at": iso(slots[eid] or dt.datetime.now(dt.timezone.utc)),
                       "linked": slots[eid] is None}
        save_ledger(ledger)                         # saved after each video: a failure loses nothing
        print(f"{eid}: https://youtu.be/{vid}", flush=True)
    # Shorts: each one after its episode is on YouTube, so its description can link to it.
    shorts_todo = [e for e in released if e in ledger and f"{e}-short" not in ledger][: max(0, cap - len(todo))]
    for eid in shorts_todo:
        upload_short(token, cfg, ledger, eid)
    return 0


def upload_short(token: str, cfg: dict, ledger: dict, eid: str) -> None:
    sys.path.insert(0, str(ROOT))
    from pqc import schedule
    from pqc.pipeline.packaging import short_description
    pk = json.loads((EPISODES / eid / "packaging.json").read_text())
    if not pk.get("short"):
        return
    with tempfile.TemporaryDirectory() as tmp:
        got = subprocess.run(["gh", "release", "download", eid, "-p", f"{eid}-short.mp4", "-D", tmp])
        path = Path(tmp) / f"{eid}-short.mp4"
        if got.returncode != 0 or not path.exists():
            print(f"{eid}: no Short in the release yet", flush=True)
            return
        site = json.loads((ROOT / "wiki" / "data" / "site.json").read_text())
        record = {"id": eid}
        desc = short_description(pk, record, site.get("site_url"), ledger[eid]["url"])
        now = dt.datetime.now(dt.timezone.utc)
        when = schedule.short_premiere(eid)
        lead = dt.timedelta(hours=cfg.get("schedule", {}).get("min_lead_hours", 2))
        slot = when if when and when > now + lead else None
        body = video_body({"title": pk["short"]["title"], "description_full": desc,
                           "tags": pk.get("tags", []) + ["shorts"]}, cfg, slot)
        print(f"{eid}: uploading the Short ({iso(slot) if slot else 'publish now'})", flush=True)
        vid = upload_video(token, path, body)
    if cfg.get("shorts_playlist_id"):
        add_to_playlist(token, cfg["shorts_playlist_id"], vid)
    ledger[f"{eid}-short"] = {"video_id": vid, "url": f"https://www.youtube.com/shorts/{vid}",
                              "publish_at": iso(slot or now), "linked": slot is None}
    save_ledger(ledger)
    print(f"{eid}: Short https://youtube.com/shorts/{vid}", flush=True)


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
    return {"check": cmd_check, "plan": lambda: cmd_plan(cfg), "upload": lambda: cmd_upload(cfg),
            "link": cmd_link, "refresh": cmd_refresh}[a.command]()


if __name__ == "__main__":
    raise SystemExit(main())
