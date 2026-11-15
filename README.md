# ytkit

A free, self-hosted YouTube toolkit for the Grinder channel ([@grinder5](https://www.youtube.com/@grinder5)).
It replaces a paid vidIQ plan by using Google's own free YouTube Data, Analytics and Reporting APIs,
plus YouTube autocomplete for keyword ideas.

- Python 3.9+ standard library only. Nothing to install.
- Windows: double-click `connect-youtube.bat` once for the guided setup, then use `ytkit.bat <command>`.
- Full command list: [README.txt](README.txt), or `python ytkit.py -h`.
- Tests (offline, fake servers): `python tests/test_ytkit.py`, `python tests/test_social.py`, `python tests/test_editkit.py`.
- Extras: `editkit.py` (beats, scenes, beat-synced cut plans, trimming, loudness), `blender/` (API checker, procedural nature), `sfx/` (sound-effect generator), `ytkit seo`, and `ytkit post` for official-API cross-posting to Facebook, Instagram and TikTok.
- Open-source work reused, with licences: [THIRD_PARTY.md](THIRD_PARTY.md).

Anything public (replies, edits, thumbnails, publishing) only runs with `--yes`.
Uploads are private by default. There is no delete command.

Credentials are never stored in this repository (see `.gitignore`).

The pages for Google's sign-in screen (home, privacy, terms) are in [`docs/`](docs/) and served by GitHub Pages.
