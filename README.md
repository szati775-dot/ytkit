# ytkit

A free, self-hosted YouTube toolkit for the Grinder channel ([@grinder5](https://www.youtube.com/@grinder5)).
It replaces a paid vidIQ plan by using Google's own free YouTube Data, Analytics and Reporting APIs,
plus YouTube autocomplete for keyword ideas.

- Python 3.9+ standard library only. Nothing to install.
- Windows: double-click `connect-youtube.bat` once for the guided setup, then use `ytkit.bat <command>`.
- Full command list: [README.txt](README.txt), or `python ytkit.py -h`.
- Optional local AI: double-click `setup-deepseek.bat` to install [Ollama](https://ollama.com) and a DeepSeek-R1 model on your PC
  (free, private, offline) and chat with it. Run it again any time to chat; pass a size such as `setup-deepseek.bat 14b`.
- Tests (offline, fake Google server): `python tests/test_ytkit.py`.

Anything public (replies, edits, thumbnails, publishing) only runs with `--yes`.
Uploads are private by default. There is no delete command.

Credentials are never stored in this repository (see `.gitignore`).

The pages for Google's sign-in screen (home, privacy, terms) are in [`docs/`](docs/) and served by GitHub Pages.
