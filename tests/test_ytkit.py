"""Offline tests for ytkit: a fake Google API server, no real calls, no quota.
Run:  python tests/test_ytkit.py   (from the ytkit folder)
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from contextlib import redirect_stdout, redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

LOG = []
STATE = {"upload_received": 0, "upload_size": None, "video_update": None, "reply": None, "thumb": None}

CH = {"id": "UCIcJ6KYbtQtoL4XZq8ypvlw", "snippet": {"title": "Grinder", "customUrl": "@grinder5",
      "publishedAt": "2025-01-23T00:00:00Z"},
      "statistics": {"subscriberCount": "1810", "viewCount": "2330000", "videoCount": "632"},
      "contentDetails": {"relatedPlaylists": {"uploads": "UUIcJ6KYbtQtoL4XZq8ypvlw"}}}


def vid(i, views, dur):
    return {"id": "v%d" % i, "snippet": {"title": "Video %d" % i, "publishedAt": "2026-11-0%dT10:00:00Z" % (1 + i % 8),
            "channelId": CH["id"], "channelTitle": "Grinder", "tags": ["war thunder"], "categoryId": "20",
            "description": "desc %d" % i},
            "statistics": {"viewCount": str(views), "likeCount": "5", "commentCount": "1"},
            "contentDetails": {"duration": dur}, "status": {"privacyStatus": "public"}}


VIDEOS = [vid(i, v, d) for i, (v, d) in enumerate(
    [(47000, "PT45S"), (1200, "PT5M10S"), (800, "PT58S"), (300, "PT6M"), (11000, "PT30S"), (900, "PT4M2S")])]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200, headers=None):
        body = json.dumps(obj).encode() if not isinstance(obj, bytes) else obj
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _auth_ok(self):
        if self.headers.get("Authorization") != "Bearer AT-1":
            self._send({"error": {"code": 401, "message": "bad auth"}}, 401)
            return False
        return True

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        LOG.append(("POST", u.path, q))
        body = self._body()
        if u.path == "/token":
            f = dict(urllib.parse.parse_qsl(body.decode()))
            if f.get("grant_type") == "authorization_code":
                ok = f.get("code") == "CODE-1" and f.get("code_verifier") and f.get("redirect_uri", "").startswith("http://127.0.0.1:")
                return self._send({"access_token": "AT-1", "refresh_token": "RT-1", "expires_in": 3600, "scope": "x"}
                                  if ok else {"error": "invalid_grant"}, 200 if ok else 400)
            if f.get("refresh_token") != "RT-1":
                return self._send({"error": "invalid_grant"}, 400)
            return self._send({"access_token": "AT-1", "expires_in": 3600})
        if not self._auth_ok():
            return
        if u.path == "/upload/youtube/v3/videos":
            STATE["upload_size"] = int(self.headers["X-Upload-Content-Length"])
            STATE["upload_meta"] = json.loads(body)
            port = self.server.server_address[1]
            return self._send(b"", 200, {"Location": "http://127.0.0.1:%d/session/abc" % port})
        if u.path == "/upload/youtube/v3/thumbnails/set":
            STATE["thumb"] = (q.get("videoId"), len(body), self.headers.get("Content-Type"))
            return self._send({"items": [{"default": {"url": "x"}}]})
        if u.path == "/youtube/v3/comments":
            STATE["reply"] = json.loads(body)
            return self._send({"id": "reply-1"})
        if u.path == "/v1/jobs":
            return self._send({"id": "job-1", "reportTypeId": json.loads(body)["reportTypeId"]})
        self._send({"error": {"code": 404, "message": "nope " + u.path}}, 404)

    def do_PUT(self):
        u = urllib.parse.urlparse(self.path)
        LOG.append(("PUT", u.path, {}))
        body = self._body()
        if not self._auth_ok():
            return
        if u.path == "/session/abc":
            rng = self.headers["Content-Range"]
            start = int(rng.split(" ")[1].split("-")[0])
            assert start == STATE["upload_received"], (start, STATE["upload_received"])
            STATE["upload_received"] += len(body)
            if STATE["upload_received"] < STATE["upload_size"]:
                return self._send(b"", 308, {"Range": "bytes=0-%d" % (STATE["upload_received"] - 1)})
            return self._send({"id": "NEWVID", "status": {"privacyStatus": STATE["upload_meta"]["status"]["privacyStatus"],
                                                          "publishAt": STATE["upload_meta"]["status"].get("publishAt")}})
        if u.path == "/youtube/v3/videos":
            STATE["video_update"] = json.loads(body)
            return self._send(STATE["video_update"])
        self._send({"error": {"code": 404, "message": "nope"}}, 404)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        LOG.append(("GET", u.path, q))
        if u.path == "/complete/search":
            s = q["q"]
            return self._send([s, [s, s + " best plane", s + " tips", "war thunder yak 3"]])
        if not self._auth_ok():
            return
        p = u.path
        if p == "/youtube/v3/channels":
            if q.get("forHandle") == "@nobody":
                return self._send({"items": []})
            return self._send({"items": [CH]})
        if p == "/youtube/v3/playlistItems":
            if not q.get("pageToken"):
                return self._send({"items": [{"contentDetails": {"videoId": v["id"]}} for v in VIDEOS[:3]],
                                   "nextPageToken": "P2"})
            return self._send({"items": [{"contentDetails": {"videoId": v["id"]}} for v in VIDEOS[3:]]})
        if p == "/youtube/v3/videos":
            ids = q["id"].split(",")
            return self._send({"items": [v for v in VIDEOS if v["id"] in ids]})
        if p == "/youtube/v3/search":
            if q.get("type") == "channel":
                return self._send({"pageInfo": {"totalResults": 5}, "items": [{"id": {"channelId": CH["id"]}}]})
            return self._send({"pageInfo": {"totalResults": 12345},
                               "items": [{"id": {"videoId": "v0"}}, {"id": {"videoId": "v3"}}]})
        if p == "/youtube/v3/commentThreads":
            mk = lambda cid, author, replies: {"snippet": {"videoId": "v0", "totalReplyCount": len(replies), "canReply": True,
                    "topLevelComment": {"id": cid, "snippet": {"authorDisplayName": author, "authorChannelId": {"value": "UC-" + author}, "textOriginal": "hi " + cid,
                                                               "likeCount": 1, "publishedAt": "2026-11-08T10:00:00Z"}}},
                    "replies": {"comments": [{"snippet": {"authorDisplayName": r, "textOriginal": "thx",
                    "authorChannelId": {"value": CH["id"] if r == "@grinder5" else "UC-" + r}}} for r in replies]}}
            return self._send({"items": [mk("c1", "@viewer1", []), mk("c2", "@viewer2", ["@grinder5"]), mk("c3", "@viewer3", ["@other"])]})
        if p == "/youtube/v3/captions":
            return self._send({"items": [{"id": "cap1", "snippet": {"language": "en", "trackKind": "asr", "name": ""}}]})
        if p == "/youtube/v3/captions/cap1":
            return self._send(b"1\n00:00:00,000 --> 00:00:01,000\nHello\n")
        if p == "/v2/reports":
            dims = (q.get("dimensions") or "").split(",") if q.get("dimensions") else []
            mets = q["metrics"].split(",")
            headers = [{"name": d} for d in dims] + [{"name": m} for m in mets]
            if dims == ["video"]:
                rows = [["v0"] + [10] * len(mets), ["v1"] + [5] * len(mets)]
            elif dims:
                rows = [["X"] * len(dims) + [1] * len(mets)]
            else:
                rows = [[100] * len(mets)]
            return self._send({"columnHeaders": headers, "rows": rows})
        if p == "/v1/reportTypes":
            return self._send({"reportTypes": [{"id": "channel_reach_basic_a1", "name": "Reach"}]})
        if p == "/v1/jobs":
            return self._send({"jobs": [{"id": "job-1", "reportTypeId": "channel_reach_basic_a1"}]})
        if p == "/v1/jobs/job-1/reports":
            port = self.server.server_address[1]
            return self._send({"reports": [{"startTime": "2026-11-07T08:00:00Z", "downloadUrl": "http://127.0.0.1:%d/dl/1" % port},
                                           {"startTime": "2026-11-06T08:00:00Z", "downloadUrl": "http://127.0.0.1:%d/dl/2" % port}]})
        if p.startswith("/dl/"):
            return self._send(b"date,video_id,video_thumbnail_impressions\n20261107,v0,500\n")
        self._send({"error": {"code": 404, "message": "nope " + p}}, 404)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]
TMP = tempfile.mkdtemp()
os.environ.update({"YTKIT_API_BASE": BASE, "YTKIT_ANALYTICS_BASE": BASE, "YTKIT_REPORTING_BASE": BASE,
                   "YTKIT_TOKEN_URL": BASE + "/token", "YTKIT_SUGGEST_BASE": BASE, "YTKIT_HOME": TMP,
                   "YT_CLIENT_ID": "cid", "YT_CLIENT_SECRET": "csec", "YT_REFRESH_TOKEN": "RT-1",
                   "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})

import ytkit  # noqa: E402  (after env so bases pick up the fake server)

ytkit.CHUNK = 256 * 1024  # force several upload chunks in the test

PASS, FAIL = [], []


def run(*argv):
    o, e = io.StringIO(), io.StringIO()
    with redirect_stdout(o), redirect_stderr(e):
        code = ytkit.main(list(argv))
    text = o.getvalue()
    try:
        data = json.loads(text) if text.strip() else None
    except ValueError:
        data = text
    return code, data, e.getvalue()


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else "  -> %s" % (info,)))


# --- read commands
c, d, _ = run("check")
check("check connects", c == 0 and d["channel"] == "Grinder" and d["credentials_from"] == "env", d)

c, d, _ = run("channel", "@grinder5")
check("channel by handle", c == 0 and d["subscribers"] == 1810 and d["handle"] == "@grinder5", d)
check("handle sent with @", ("GET", "/youtube/v3/channels", {"part": "snippet,statistics,contentDetails", "forHandle": "@grinder5"}) in LOG)

c, d, e = run("channel", "@nobody")
check("unknown channel -> clean error", c == 2 and "not found" in e, e)

c, d, _ = run("videos", "--limit", "10")
check("videos paginates uploads", c == 0 and len(d) == 6, d)
check("short detection", d[0]["short"] is True and d[1]["short"] is False and d[5]["duration_s"] == 242, d[:2])

c, d, _ = run("videos", "--shorts")
check("--shorts filter", c == 0 and all(v["short"] for v in d) and len(d) == 3, d)

c, d, _ = run("video", "v1")
check("video full details", c == 0 and d[0]["tags"] == ["war thunder"] and d[0]["description"] == "desc 1", d)

c, d, _ = run("outliers")
check("outliers split + ratio", c == 0 and {g["type"] for g in d["groups"]} == {"short", "long"}
      and d["groups"][0]["top"][0]["id"] == "v0" and d["groups"][0]["median_views"] == 11000, d)

c, d, _ = run("search", "war thunder yak", "--since", "30d")
check("search enriches + outlier score", c == 0 and d["total_results_estimate"] == 12345
      and d["videos"][0]["outlier_score"] == round(47000 / 1810, 2) and "views_per_day" in d["videos"][0], d)
sq = [x for x in LOG if x[1] == "/youtube/v3/search"][-1][2]
check("search publishedAfter format", sq["publishedAfter"].endswith("T00:00:00Z") and sq["regionCode"] == "GB", sq)

c, d, _ = run("search", "war thunder", "--type", "channel")
check("channel search", c == 0 and d["channels"][0]["title"] == "Grinder", d)

c, d, _ = run("keywords", "war thunder")
check("keywords basic", c == 0 and d["keywords"][0]["keyword"] == "war thunder" and d["count"] == 4, d)
c, d, _ = run("keywords", "war thunder", "--deep", "--competition", "2")
check("keywords deep ranks by hits", c == 0 and d["keywords"][0]["hits"] > 1 and len(d["competition"]) == 2
      and d["competition"][0]["top10_median_views"] == (47000 + 300) / 2, d if not isinstance(d, dict) else d.get("competition"))

# --- analytics
c, d, _ = run("report", "overview")
check("report overview", c == 0 and d["rows"][0]["views"] == 100, d)
c, d, _ = run("report", "top-videos", "--start", "2026-10-01", "--content-type", "SHORTS")
rq = [x for x in LOG if x[1] == "/v2/reports"][-1][2]
check("top-videos joins titles", c == 0 and d["rows"][0]["title"] == "Video 0" and d["rows"][0]["short"] is True, d)
check("content-type filter + dates", rq["filters"] == "creatorContentType==SHORTS" and rq["startDate"] == "2026-10-01"
      and rq["ids"] == "channel==MINE", rq)
c, d, _ = run("report", "search-terms", "--video", "v0")
rq = [x for x in LOG if x[1] == "/v2/reports"][-1][2]
check("search-terms combines filters", rq["filters"] == "insightTrafficSourceType==YT_SEARCH;video==v0", rq)
c, d, e = run("report", "retention")
check("retention needs --video", c == 2 and "--video" in e, e)
c, d, _ = run("report", "retention", "--video", "v0")
rq = [x for x in LOG if x[1] == "/v2/reports"][-1][2]
check("retention query", c == 0 and rq["dimensions"] == "elapsedVideoTimeRatio" and rq["filters"] == "video==v0", rq)
c, d, _ = run("analytics", "--metrics", "views", "--dimensions", "day", "--start", "7d")
check("raw analytics", c == 0 and d[0]["day"] == "X", d)

# --- reporting
c, d, _ = run("reporting", "types")
check("reporting types", c == 0 and d[0]["id"] == "channel_reach_basic_a1", d)
c, d, _ = run("reporting", "fetch", "--latest", "1")
check("reporting fetch downloads latest", c == 0 and len(d["files"]) == 1 and d["files"][0].endswith("2026-11-07.csv")
      and open(d["files"][0]).read().startswith("date,"), d)

# --- comments
c, d, _ = run("comments", "--limit", "10")
check("comments list", c == 0 and len(d) == 3 and d[0]["comment_id"] == "c1", d)
c, d, _ = run("comments", "--unanswered")
check("unanswered filter", c == 0 and [r["comment_id"] for r in d] == ["c1", "c3"], d)

# --- write commands are gated
c, d, e = run("reply", "c1", "thanks!")
check("reply blocked without --yes", c == 2 and "--yes" in e and STATE["reply"] is None, e)
c, d, _ = run("reply", "c1", "thanks!", "--yes")
check("reply with --yes", c == 0 and STATE["reply"]["snippet"]["parentId"] == "c1", STATE["reply"])

c, d, _ = run("update", "v1", "--title", "New title", "--tags", "a, b")
check("update dry-run by default", c == 0 and d["dry_run"] and STATE["video_update"] is None
      and d["would_change"]["title"] == ["Video 1", "New title"], d)
c, d, _ = run("update", "v1", "--title", "New title", "--synthetic", "yes", "--yes")
vu = STATE["video_update"]
check("update keeps other fields", c == 0 and vu["snippet"]["title"] == "New title" and vu["snippet"]["description"] == "desc 1"
      and vu["snippet"]["tags"] == ["war thunder"] and vu["status"]["containsSyntheticMedia"] is True
      and vu["status"]["privacyStatus"] == "public", vu)
c, d, _ = run("update", "v1")
check("update no-op", c == 0 and d == {"changed": False}, d)

thumb = os.path.join(TMP, "t.jpg")
open(thumb, "wb").write(b"\xff\xd8" + b"0" * 1000)
c, d, e = run("thumbnail", "v1", thumb)
check("thumbnail blocked without --yes", c == 2 and STATE["thumb"] is None, e)
c, d, _ = run("thumbnail", "v1", thumb, "--yes")
check("thumbnail set", c == 0 and STATE["thumb"] == ("v1", 1002, "image/jpeg"), STATE["thumb"])
big = os.path.join(TMP, "big.jpg")
open(big, "wb").write(b"0" * (2 * 1024 * 1024 + 1))
c, d, e = run("thumbnail", "v1", big, "--yes")
check("thumbnail size limit", c == 2 and "2 MB" in e, e)

video = os.path.join(TMP, "clip.mp4")
open(video, "wb").write(os.urandom(256 * 1024 * 3 + 1234))
c, d, e = run("upload", video, "--title", "T", "--privacy", "public")
check("public upload blocked without --yes", c == 2 and STATE["upload_size"] is None, e)
c, d, e = run("upload", video, "--title", "T", "--publish-at", "2026-11-10T17:00:00Z")
check("scheduled upload blocked without --yes", c == 2, e)
c, d, e = run("upload", video, "--title", "T", "--tags", "war thunder,yak", "--thumbnail", thumb)
check("private upload, chunked + resumed", c == 0 and d["id"] == "NEWVID" and STATE["upload_received"] == os.path.getsize(video)
      and d["privacy"] == "private" and d["thumbnail"] == "set", (d, e, STATE["upload_received"]))
m = STATE["upload_meta"]
check("upload metadata", m["snippet"]["categoryId"] == "20" and m["snippet"]["tags"] == ["war thunder", "yak"]
      and m["status"]["selfDeclaredMadeForKids"] is False, m)
STATE["upload_received"] = 0
c, d, e = run("upload", video, "--title", "T", "--publish-at", "2026-11-10T17:00:00Z", "--yes")
check("scheduled upload stays private until publishAt", c == 0 and STATE["upload_meta"]["status"] == {
    "privacyStatus": "private", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False,
    "publishAt": "2026-11-10T17:00:00Z"}, STATE["upload_meta"])

# --- captions / quota
c, d, _ = run("captions", "v0")
check("captions list", c == 0 and d[0]["id"] == "cap1", d)
o = io.StringIO()
with redirect_stdout(o):
    ytkit.main(["captions", "v0", "--download"])
check("captions download", "Hello" in o.getvalue(), o.getvalue())
c, d, _ = run("quota")
check("quota counter", c == 0 and d["units"] > 1600 and d["daily_limit"] == 10000, d)

# --- bad token gives a helpful hint
ytkit._ACCESS.update(token=None, exp=0)
os.environ["YT_REFRESH_TOKEN"] = "WRONG"
c, d, e = run("check")
check("invalid_grant hint", c == 2 and "In production" in e, e)
os.environ["YT_REFRESH_TOKEN"] = "RT-1"

# --- first-time sign-in flow (browser simulated)
import webbrowser  # noqa: E402
opened = []


def fake_browser(url):
    opened.append(url)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    if "redirect_uri" not in q:
        return True
    def hit():
        import time as _t
        _t.sleep(0.3)
        urllib.request.urlopen(q["redirect_uri"] + "/?" + urllib.parse.urlencode({"code": "CODE-1", "state": q["state"]})).read()
    threading.Thread(target=hit, daemon=True).start()
    return True


import urllib.request  # noqa: E402
webbrowser.open = fake_browser
ytkit.copy_to_clipboard = lambda t: True
cs_file = os.path.join(TMP, "client_secret_123.json")
json.dump({"installed": {"client_id": "cid", "client_secret": "csec"}}, open(cs_file, "w"))
ytkit.TOKEN_FILE = os.path.join(TMP, "auth", "token.json")
ytkit._ACCESS.update(token=None, exp=0)
o, e = io.StringIO(), io.StringIO()
with redirect_stdout(o), redirect_stderr(e):
    code = ytkit.main(["auth", cs_file, "--show-env"])
txt = o.getvalue()
check("auth flow saves token + shows channel", code == 0 and "Connected channel: Grinder" in txt
      and json.load(open(ytkit.TOKEN_FILE))["refresh_token"] == "RT-1", (txt, e.getvalue()))
aq = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(opened[0]).query))
check("auth asks offline + all scopes + PKCE", aq["access_type"] == "offline" and aq["code_challenge_method"] == "S256"
      and "yt-analytics.readonly" in aq["scope"] and "youtube.upload" in aq["scope"], aq)
line = [l for l in txt.splitlines() if l.startswith("YTKIT_CREDS=")]
check("auth prints one YTKIT_CREDS line", len(line) == 1 and "clipboard" in txt, txt)
packed = line[0].split("=", 1)[1]
os.environ["YTKIT_CREDS"] = packed
ytkit._ACCESS.update(token=None, exp=0)
c, d, _ = run("check")
check("printed line works as credentials", c == 0 and d["channel"] == "Grinder", d)
del os.environ["YTKIT_CREDS"]

# --- guided setup: opens the 4 Google pages, picks up the download, signs in
import builtins  # noqa: E402
fake_home = tempfile.mkdtemp()
os.makedirs(os.path.join(fake_home, "Downloads"))
old_home, old_up, old_input = os.environ.get("HOME"), os.environ.get("USERPROFILE"), builtins.input
os.environ["HOME"] = os.environ["USERPROFILE"] = fake_home  # USERPROFILE is what Windows uses
prompts = []
builtins.input = lambda msg="": prompts.append(msg) or ""
def later_download():
    import time as _t
    _t.sleep(1.0)
    json.dump({"installed": {"client_id": "cid", "client_secret": "csec"}},
              open(os.path.join(fake_home, "Downloads", "client_secret_999.json"), "w"))
threading.Thread(target=later_download, daemon=True).start()
opened.clear()
ytkit.TOKEN_FILE = os.path.join(TMP, "auth2", "token.json")
here_copy = os.path.join(os.path.dirname(os.path.abspath(ytkit.__file__)), "client_secret_999.json")
o, e = io.StringIO(), io.StringIO()
with redirect_stdout(o), redirect_stderr(e):
    code = ytkit.main(["setup"])
builtins.input = old_input
for k, v in (("HOME", old_home), ("USERPROFILE", old_up)):
    if v is None:
        os.environ.pop(k, None)
    else:
        os.environ[k] = v
txt = o.getvalue()
check("setup opens 4 Google pages then sign-in", code == 0 and len(opened) == 5 and "/auth/clients/create" in opened[3]
      and len(prompts) == 3, (code, opened, prompts, e.getvalue()[-300:]))
check("setup copies key next to ytkit and connects", os.path.exists(here_copy) and "Connected channel: Grinder" in txt
      and "YTKIT_CREDS=" in txt, txt[-400:])
if os.path.exists(here_copy):
    os.remove(here_copy)

# --- packed single-line credentials
ytkit._ACCESS.update(token=None, exp=0)
os.environ["YTKIT_CREDS"] = ytkit.encode_creds("cid", "csec", "RT-1")
c, d, _ = run("check")
check("YTKIT_CREDS works", c == 0 and d["credentials_from"] == "env YTKIT_CREDS", d)
ytkit._ACCESS.update(token=None, exp=0)
os.environ["YTKIT_CREDS"] = "not-base64!!"
c, d, e = run("check")
check("bad YTKIT_CREDS -> clear error", c == 2 and "YTKIT_CREDS" in e, e)
del os.environ["YTKIT_CREDS"]

# --- setup finds the newest downloaded key
dl1, dl2 = tempfile.mkdtemp(), tempfile.mkdtemp()
open(os.path.join(dl1, "client_secret_old.json"), "w").write("{}")
os.utime(os.path.join(dl1, "client_secret_old.json"), (1, 1))
open(os.path.join(dl2, "client_secret_new.json"), "w").write("{}")
open(os.path.join(dl2, "other.json"), "w").write("{}")
check("find_client_secret picks newest", ytkit.find_client_secret([dl1, dl2, "/nope"]).endswith("client_secret_new.json"))
check("find_client_secret none", ytkit.find_client_secret(["/nope"]) is None)
check("setup steps link the 3 APIs", "youtubeanalytics.googleapis.com" in ytkit.SETUP_STEPS[0][1]
      and "youtubereporting.googleapis.com" in ytkit.SETUP_STEPS[0][1])

# --- token file fallback
ytkit._ACCESS.update(token=None, exp=0)
for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
    os.environ.pop(k)
tf = os.path.join(TMP, "token.json")
json.dump({"client_id": "cid", "client_secret": "csec", "refresh_token": "RT-1"}, open(tf, "w"))
ytkit.TOKEN_FILE = tf
c, d, _ = run("check")
check("token.json fallback", c == 0 and d["credentials_from"] == tf, d)

# --- CLI runs as a script (help works, py3 syntax ok)
r = subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), "ytkit.py"), "-h"], capture_output=True, text=True)
check("script -h", r.returncode == 0 and "keywords" in r.stdout, r.stderr)

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
srv.shutdown()
sys.exit(1 if FAIL else 0)
