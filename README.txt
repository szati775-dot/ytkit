ytkit 1.1 - free YouTube toolkit for the Grinder channel (replaces vidIQ)
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
  quota                       today's estimated use on this machine

SAFETY
  Anything public needs --yes. Uploads stay private by default.
  There is no delete command on purpose.

WHAT IT DOES NOT DO (vidIQ extras)
  AI titles/scripts/thumbnail ideas: Claude does these itself.
  Exact "search volume" numbers: not public anywhere for free; ytkit's keyword
  score (autocomplete rank) plus the competition check is the stand-in.
  Other channels' transcripts: use Claude's youtube-transcriber skill.
