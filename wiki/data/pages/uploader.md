# Nat 20 Pixels uploader

The **Nat 20 Pixels uploader** is the project's own tool for publishing its episodes on the
[@Nat20px](https://www.youtube.com/@Nat20px) YouTube channel. It uses **YouTube API Services**
(the YouTube Data API v3). It is an internal tool: it has no user interface and no other users,
and it only ever acts on the project's own channel.

## What it does

When an episode is finished, a GitHub Actions workflow
([`youtube.yml`](https://github.com/Nat20-Pixel-Saga/Nat20-Pixel-Saga/blob/main/.github/workflows/youtube.yml))
runs the uploader
([`scripts/youtube_upload.py`](https://github.com/Nat20-Pixel-Saga/Nat20-Pixel-Saga/blob/main/scripts/youtube_upload.py)), which:

1. signs in as the channel owner with OAuth 2.0 (a refresh token created once by the owner);
2. uploads the episode video with its title, description, chapters and tags, declared as not
   made for kids, and schedules its premiere (`videos.insert`, with `status.publishAt`);
3. sets the episode's custom thumbnail (`thumbnails.set`);
4. adds the video to the season playlist (`playlistItems.insert`);
5. every day, re-checks the IDs of the videos it uploaded (`videos.list`) so that nothing it has
   stored is older than 30 days, and links each premiered episode from this wiki.

`channels.list` is used only to confirm which channel the credentials belong to. One episode is
published per weekday, so it makes a handful of API calls a day.

## Your data

The uploader collects nothing about viewers or other YouTube users. See the
[privacy policy](privacy.md) for exactly what it accesses, stores and deletes, and the
[terms of service](terms.md). Use of the uploader is subject to the
[YouTube Terms of Service](https://www.youtube.com/t/terms) and the
[Google Privacy Policy](https://policies.google.com/privacy).

The account owner can revoke its access at any time from the Google account's
[third-party access settings](https://myaccount.google.com/permissions).

## Source

The complete source code is public:
<https://github.com/Nat20-Pixel-Saga/Nat20-Pixel-Saga>. Run history:
[Actions → youtube](https://github.com/Nat20-Pixel-Saga/Nat20-Pixel-Saga/actions/workflows/youtube.yml).
