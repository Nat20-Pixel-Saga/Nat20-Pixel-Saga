# Publishing to YouTube automatically

Channel: [@Nat20px](https://www.youtube.com/@Nat20px) · wiki: <https://nat20pixelsaga.com>

## Uploading by hand (until the automation is on)

After you upload and schedule an episode in YouTube Studio, register it so the wiki
links it once it goes public (and so the automatic uploader never uploads it again):
**Actions → youtube → Run workflow**, command **record**, the episode number, the
video's link, and when it goes public in Paris time (e.g. `2026-10-08 21:00`; leave it
empty if it is already public). The daily run adds the "Watch on YouTube" link to the
episode's wiki page after that time.

Once this is set up, every new episode goes from story to YouTube with no one
touching it:

```
shift writes episode → relay commits it → release.yml renders the MP4 and makes the GitHub release
  → youtube.yml uploads it, sets the thumbnail, adds it to the playlist and schedules the premiere
  → daily youtube.yml run after the premiere → wiki episode page gets "Watch on YouTube"
```

Episodes premiere **in order, one per weekday at 15:00 New York time** (21:00 in Paris most of the year) (change it in
`production/youtube.json`). A backlog is spread over the following weekdays, so
the ten episodes already released fill two weeks.

Everything below is done once. Steps 1-6 take about 30 minutes; step 7 (Google's
audit) can take a few weeks, and uploads stay locked as private until it passes.

## 1. Create the channel

1. Sign in to YouTube with the Google account that will own the show, then go to
   **Settings → Add or manage your channel(s) → Create a channel**. Picking a
   *brand account* channel keeps it separate from your personal one and lets you
   add managers later.
2. Set the name, handle, picture and banner. Under **Settings → Channel → Feature
   eligibility**, verify by phone: custom thumbnails need it.
3. In YouTube Studio create a playlist, e.g. *Campaign 1: The Lantern Road*. Its id
   is the `list=` part of its URL; you'll need it in step 8.

## 2. Make a Google Cloud project with the YouTube API

1. Go to <https://console.cloud.google.com>, create a project (e.g. `pqc-youtube`).
2. **APIs & Services → Library → YouTube Data API v3 → Enable.**

## 3. Set up the OAuth consent screen and client

1. **Google Auth Platform → Branding** (older consoles: *OAuth consent screen*):
   app name *Nat 20 Pixels uploader*, your support email.
2. **Audience**: user type *External*, then **Publish app** so the status is
   **In production**. This matters: while it says *Testing*, Google expires the
   refresh token after 7 days and uploads stop.
3. **Data access**: add the scope `https://www.googleapis.com/auth/youtube`.
4. **Clients → Create client** → type **Web application**, and under *Authorized
   redirect URIs* add `https://developers.google.com/oauthplayground`. Copy the
   **Client ID** and **Client secret**.

## 4. Get a refresh token (one time)

1. Open <https://developers.google.com/oauthplayground>.
2. Gear icon (top right) → tick **Use your own OAuth credentials** → paste the
   client id and secret.
3. In *Step 1*, type `https://www.googleapis.com/auth/youtube` in the box and press
   **Authorize APIs**. Sign in with the channel's account and, if asked, pick the
   channel. Google warns the app is unverified: **Advanced → Go to … (unsafe)** is
   fine, it is your own app.
4. *Step 2* → **Exchange authorization code for tokens** → copy the **Refresh
   token**. Treat it like a password.

## 5. Store the three secrets in GitHub

Repository **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Value |
| --- | --- |
| `YT_CLIENT_ID` | client id from step 3 |
| `YT_CLIENT_SECRET` | client secret from step 3 |
| `YT_REFRESH_TOKEN` | refresh token from step 4 |

## 6. Test it

**Actions → youtube → Run workflow**, command **check**: the log prints the
channel's name. Then run it with **plan**: it lists the episodes it would upload
and the premiere time of each, without uploading anything.

## 7. Pass Google's audit (needed for public videos)

Videos uploaded through the API by a project that hasn't been audited are locked
as private. Apply with the **YouTube API Services – Audit and Quota Extension
Form**: <https://support.google.com/youtube/contact/yt_api_form>. What to say:

* It's an internal tool that uploads videos **to its owner's own channel only**;
  no other users sign in.
* It stores nothing except the uploaded video ids, in the public repository
  (`wiki/data/youtube.json`); the source is
  <https://github.com/Nat20-Pixel-Saga/Nat20-Pixel-Saga> (`scripts/youtube_upload.py`).
* API calls: `videos.insert`, `thumbnails.set`, `playlistItems.insert`,
  `channels.list`, a handful a day.

Until it's approved, publish by hand if you want to start: download the MP4 and
thumbnail from the episode's GitHub release, upload in YouTube Studio, paste the
release text as the description, and schedule it.

## 8. Switch it on

Edit `production/youtube.json`: `"enabled": true`, and `"playlist_id": "PL…"`
from step 1. Commit. The next run (after the next release, every day at 20:37
UTC, or **Run workflow → upload**) uploads everything released and not yet on
YouTube, up to five per run.

## Settings (`production/youtube.json`)

| Key | Meaning |
| --- | --- |
| `enabled` | Uploads happen only when true. |
| `schedule` | `timezone`, `time`, `weekdays` (0 = Monday), `min_lead_hours`. `null` publishes at once with `privacy`. |
| `category_id` | 20 Gaming (default), 24 Entertainment, 1 Film & Animation. |
| `made_for_kids` | false: the show has combat and peril; YouTube asks every channel to declare this. |
| `contains_synthetic_media` | YouTube's "altered or synthetic content" label is for realistic footage that could mislead; a pixel-art fantasy cartoon doesn't need it. Set true if you prefer to label anyway. |
| `max_per_run` | Upload cap per run. |

Quota: each project gets 100 `videos.insert` calls a day in their own bucket, plus
10,000 units for everything else (`thumbnails.set` costs 50). A daily show uses a
tiny fraction.

## If something goes wrong

* `invalid_grant` in the log: the refresh token was revoked or expired (consent
  screen still in *Testing*?). Redo step 4 and update `YT_REFRESH_TOKEN`.
* Thumbnail not set: the channel isn't phone-verified (step 1.2). The video is fine.
* A video went up wrong: delete it in Studio, remove its line from
  `wiki/data/youtube.json`, and run the workflow again. It will take the next free
  slot. To keep the order, also remove the lines of every later episode and delete
  those videos.
