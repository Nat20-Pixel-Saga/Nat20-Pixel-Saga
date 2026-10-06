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

The project uses **YouTube API Services** through a small uploader of its own
(`scripts/youtube_upload.py` in the [source repository](https://github.com/Nat20-Pixel-Saga/Nat20-Pixel-Saga)).

- It is used only by the project itself, to upload the series' own episodes to the project's own
  YouTube channel, set their thumbnails, add them to the channel's playlists and schedule their
  premieres. No other person signs in to it.
- It accesses only the project's own YouTube channel, through Google sign-in (OAuth 2.0). It does
  not access, collect or store any information about viewers or any other YouTube user.
- The only credentials are those of the project's own Google account. They are kept as encrypted
  secrets of the repository's GitHub Actions and are not shared with anyone. The only data it
  stores is the list of uploaded video IDs and publication times, which is public in the
  repository (`wiki/data/youtube.json`).
- Access can be revoked at any time from the Google account's
  [security settings](https://myaccount.google.com/permissions).

By watching the series on YouTube you use YouTube itself, under the
[YouTube Terms of Service](https://www.youtube.com/t/terms) and the
[Google Privacy Policy](https://policies.google.com/privacy).

## Contact

Questions about this policy: open an issue in the
[project repository](https://github.com/Nat20-Pixel-Saga/Nat20-Pixel-Saga/issues).
