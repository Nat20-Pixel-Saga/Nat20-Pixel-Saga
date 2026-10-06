# Privacy policy

*Last updated: 6 October 2026*

Nat 20 Pixels Saga is a pixel-art fantasy series published on YouTube
([@Nat20px](https://www.youtube.com/@Nat20px)) together with this wiki. This page explains what
information the project handles.

## This website

- This wiki is a static website hosted by GitHub Pages. It has no accounts, no comments, no
  forms, no advertising, no analytics and no cookies of its own.
- GitHub, as the host, processes technical data such as your IP address to deliver the pages and
  keep the service secure. See the [GitHub General Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).

## The Nat 20 Pixels uploader (YouTube API Services)

The project uses **YouTube API Services** through a small uploader of its own, the
[Nat 20 Pixels uploader](uploader.md) (`scripts/youtube_upload.py` in the
[source repository](https://github.com/Nat20-Pixel-Saga/Nat20-Pixel-Saga)).

- It is used only by the project itself, to upload the series' own episodes to the project's own
  YouTube channel, set their thumbnails, add them to the channel's playlists and schedule their
  premieres. No other person signs in to it.
- It accesses only the project's own YouTube channel, through Google sign-in (OAuth 2.0). It does
  not access, collect or store any information about viewers or any other YouTube user.
- **What it accesses:** the project's own YouTube channel only (its name and ID, to confirm the
  account; the videos it uploads; the channel's playlists). It requests the YouTube scope
  `https://www.googleapis.com/auth/youtube` for the channel owner alone.
- **What it stores:** the OAuth credentials of the project's own Google account, kept as encrypted
  GitHub Actions secrets and never shared; and, for each episode it publishes, the video ID and
  premiere time (public in the repository, `wiki/data/youtube.json`), used to link each episode
  page of this wiki to its video. No personal data, no data about viewers, no statistics.
- **Retention and deletion:** every stored video ID is re-checked against the YouTube API every
  day; an entry whose video no longer exists is deleted at once, so nothing obtained from the API
  is kept for more than 30 days without being refreshed. Deleting a video from the channel
  removes its entry at the next daily check. To have anything removed sooner, use the contact
  below.
- **Revoking access:** the account owner can revoke the uploader's access at any time from the
  Google account's [third-party access settings](https://myaccount.google.com/permissions).
  Revoking it stops all uploads immediately.

By watching the series on YouTube you use YouTube itself, under the
[YouTube Terms of Service](https://www.youtube.com/t/terms) and the
[Google Privacy Policy](https://policies.google.com/privacy).

## Contact

Questions about this policy: open an issue in the
[project repository](https://github.com/Nat20-Pixel-Saga/Nat20-Pixel-Saga/issues).
