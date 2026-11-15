ytkit 1.2 - free YouTube toolkit for the Grinder channel (replaces vidIQ)
=========================================================================
Python 3.9+ standard library only. Nothing to pip install. Free: it uses
Google's own YouTube APIs with your own login, inside the free daily quota
(10,000 units a day; resets at midnight Pacific time = 08:00 UK).

FILES
  ytkit.py             the tool
  ytkit.bat            Windows launcher:  ytkit channel
  connect-youtube.bat  one-time guided setup: opens each Google page, finds the
                       downloaded key in Downloads, signs in, copies the line for Claude
  tests\test_ytkit.py  offline test against a fake Google server (no real calls)
  tests\test_social.py offline test of post/social against fake Meta + TikTok servers
  tests\test_editkit.py offline test of editkit on synthetic media
  editkit.py / .bat    editing helpers (see EXTRA TOOLS)

CREDENTIALS (first match wins)
  1. env var YTKIT_CREDS (one line, printed and copied by connect-youtube.bat),
     or YT_CLIENT_ID + YT_CLIENT_SECRET + YT_REFRESH_TOKEN   (Claude cloud sessions)
  2. %USERPROFILE%\.ytkit\token.json  (written by connect-youtube.bat on the PC)

COMMANDS (add -h to any command for all options)            quota cost
  setup                       guided first-time setup (what connect-youtube.bat runs)
  check                       test login, show connected channel        1
  channel [mine|@handle|UC..] subs, views, video count                  1
  videos [channel] --limit 50 [--shorts|--long]   recent uploads        ~3
  video ID [ID...]            full details: title, description, tags    1
  outliers [channel]          videos that beat the channel's median    ~3
  search "query" [--since 30d --order viewCount --duration short]
                              results + views/day + outlier score    ~102
  search "query" --type channel   find competitor channels           ~101
  keywords "seed" [--deep] [--competition 5]
                              autocomplete keyword ideas, free; competition
                              check is 100 per keyword
  report PRESET [--start 28d --end 0d --video ID --content-type SHORTS]
      overview, daily, content-type (Shorts vs long), traffic, traffic-by-type,
      top-videos, search-terms, suggested-from, geo, devices, demographics,
      subscribed, playback, retention (needs --video)            Analytics API
  analytics --metrics ... [--dimensions --filters --sort --limit]   raw query
  reporting types|jobs|create --type X|fetch [--type X]
                              bulk daily CSVs (e.g. thumbnail impressions
                              and CTR). Create a job once; files start ~2 days later.
  comments [--video ID] [--unanswered] [--status heldForReview]         1/page
  reply COMMENT_ID "text" --yes                     PUBLIC              50
  update ID [--title --description @file.txt --tags a,b --privacy
             --publish-at 2026-11-10T17:00:00Z --synthetic yes]
                              dry run unless --yes                      50
  thumbnail ID file.jpg --yes (max 2 MB)            PUBLIC              50
  upload FILE --title T [--description @desc.txt --tags --thumbnail img.jpg
         --publish-at ISO --synthetic yes] (private unless --yes)   ~1600
  captions ID [--download --format srt]   your own videos only      50-200
  seo words [channel|--search "q"|--from-json f] [--ngram 2 --with-tags]
                              which title words go with views: count, total
                              views, avg views, lift vs the set (advertools idea)
  seo check --title "Draft" [--search "q"] [--shorts]
                              draft title vs winning terms, length, caps, keyword spot
  post facebook|instagram|tiktok|all FILE --caption @cap.txt [--yes]
                              Shorts cross-post through the OFFICIAL APIs
                              (FB Page Reels, IG Reels, TikTok). Dry run without --yes.
                              TikTok stays SELF_ONLY until TikTok audits the app.
  social check | meta-token --app-id --app-secret --user-token T | tiktok-auth
         --client-key --client-secret     connect the accounts used by `post`
                              (saved in %USERPROFILE%\.ytkit\social.json)
  quota                       today's estimated use on this machine

EXTRA TOOLS (need: pip install -r requirements-editkit.txt, and ffmpeg)
  editkit.bat beats song.mp3          BPM, beat grid, big hits + Resolve marker EDL
  editkit.bat scenes rec.mp4          cuts + action score per shot + marker EDL
  editkit.bat plan --music song.mp3 --video a.mp4 b.mp4 [--beats-per-cut 2 --preview]
                                      best shots snapped to the beats -> EDL timeline
                                      (Resolve: File > Import > Timeline) + preview mp4
  editkit.bat trim rec.mp4 [--resolve] [--silent-speed 8]
                                      cut dead time (auto-editor); --resolve = timeline only
  editkit.bat loudness a.mp4 b.wav    LUFS / true peak vs the -14 LUFS upload target
  All classical signal processing, no AI: fine on War Thunder footage.

  blender\check_bpy.py script.py      catches Blender API typos before a render
  blender\nature.py                   ground, grass tufts, boulders, scatter (Infinigen port)
  blender\nature_demo.py              test scene:  blender -b -P nature_demo.py -- out.png 50 32
  sfx\sfxgen.py "prompt" --seconds 3  sound effects for our own renders (Stable Audio
                                      Open Small; needs a Hugging Face token, see the file)
  Credits and licences: THIRD_PARTY.md

SAFETY
  Anything public needs --yes. Uploads stay private by default.
  There is no delete command on purpose.

WHAT IT DOES NOT DO (vidIQ extras)
  AI titles/scripts/thumbnail ideas: Claude does these itself.
  Exact "search volume" numbers: not public anywhere for free; ytkit's keyword
  score (autocomplete rank) plus the competition check is the stand-in.
  Other channels' transcripts: use Claude's youtube-transcriber skill.
