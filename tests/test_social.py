"""Offline tests for `ytkit post` / `ytkit social` against fake Meta + TikTok servers.
Run:  python tests/test_social.py   (from the ytkit folder)
"""
import io
import json
import os
import sys
import tempfile
import threading
import urllib.parse
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
TMP = tempfile.mkdtemp()
LOG, GOT = [], {"fb_bytes": 0, "ig_bytes": 0, "tt_chunks": [], "tt_init": None, "fb_finish": None, "ig_box": None}
PORT = {}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _route(self, method):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        body = self._body()
        LOG.append((method, u.path, q))
        base = "http://127.0.0.1:%d" % PORT["p"]
        p = u.path
        # --- Meta Graph
        if p == "/v24.0/oauth/access_token":
            return self._send({"access_token": "LONG-USER", "token_type": "bearer"})
        if p == "/v24.0/me/accounts":
            return self._send({"data": [{"id": "PAGE1", "name": "Grinder", "access_token": "PAGE-TOK",
                                         "instagram_business_account": {"id": "IG1"}}]})
        if q.get("access_token") not in (None, "PAGE-TOK") and p.startswith("/v24.0/") and "oauth" not in p:
            return self._send({"error": {"message": "Invalid OAuth access token", "code": 190}}, 400)
        if p == "/v24.0/PAGE1/video_reels" and q.get("upload_phase") == "start":
            return self._send({"video_id": "FBV1", "upload_url": base + "/video-upload/v24.0/FBV1"})
        if p == "/video-upload/v24.0/FBV1":
            assert self.headers["Authorization"] == "OAuth PAGE-TOK" and self.headers["offset"] == "0"
            GOT["fb_bytes"] = len(body) if int(self.headers["file_size"]) == len(body) else -1
            return self._send({"success": True})
        if p == "/v24.0/PAGE1/video_reels" and q.get("upload_phase") == "finish":
            GOT["fb_finish"] = q
            return self._send({"success": True})
        if p == "/v24.0/FBV1":
            return self._send({"status": {"video_status": "ready"}})
        if p == "/v24.0/IG1/media":
            GOT["ig_box"] = q
            return self._send({"id": "BOX1", "uri": base + "/ig-api-upload/v24.0/BOX1"})
        if p == "/ig-api-upload/v24.0/BOX1":
            GOT["ig_bytes"] = len(body) if self.headers["Authorization"] == "OAuth PAGE-TOK" else -1
            return self._send({"success": True})
        if p == "/v24.0/BOX1":
            return self._send({"status_code": "FINISHED", "id": "BOX1"})
        if p == "/v24.0/IG1/media_publish":
            return self._send({"id": "IGM1"} if q.get("creation_id") == "BOX1" else {"error": {"message": "bad"}})
        if p == "/v24.0/IGM1":
            return self._send({"permalink": "https://www.instagram.com/reel/XYZ/"})
        if p == "/v24.0/IG1":
            return self._send({"username": "grinder"})
        if p == "/v24.0/PAGE1":
            return self._send({"id": "PAGE1", "name": "Grinder"})
        # --- TikTok
        if p == "/v2/oauth/token/":
            f = dict(urllib.parse.parse_qsl(body.decode()))
            if f.get("grant_type") == "refresh_token" and f.get("refresh_token") == "TT-RT":
                return self._send({"access_token": "TT-AT", "refresh_token": "TT-RT2", "expires_in": 86400})
            if f.get("grant_type") == "refresh_token" and f.get("refresh_token") == "TT-RT2":
                return self._send({"access_token": "TT-AT", "refresh_token": "TT-RT2", "expires_in": 86400})
            return self._send({"error": "invalid_grant", "error_description": "bad"}, 400)
        if p.startswith("/v2/post/") and self.headers.get("Authorization") != "Bearer TT-AT":
            return self._send({"error": {"code": "access_token_invalid", "message": "bad token"}}, 401)
        if p == "/v2/post/publish/creator_info/query/":
            return self._send({"data": {"creator_username": "grinder", "privacy_level_options": ["SELF_ONLY"]},
                               "error": {"code": "ok"}})
        if p == "/v2/post/publish/video/init/":
            GOT["tt_init"] = json.loads(body)
            return self._send({"data": {"publish_id": "PUB1", "upload_url": base + "/tt-upload/PUB1"},
                               "error": {"code": "ok"}})
        if p == "/tt-upload/PUB1":
            GOT["tt_chunks"].append((self.headers["Content-Range"], len(body)))
            return self._send({})
        if p == "/v2/post/publish/status/fetch/":
            return self._send({"data": {"status": "PUBLISH_COMPLETE"}, "error": {"code": "ok"}})
        self._send({"error": {"message": "unknown " + p}}, 404)

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
PORT["p"] = srv.server_port
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d" % PORT["p"]
os.environ.update({"YTKIT_GRAPH_BASE": base, "YTKIT_RUPLOAD_BASE": base, "YTKIT_TIKTOK_BASE": base,
                   "YTKIT_GRAPH_VERSION": "v24.0", "YTKIT_HOME": TMP,
                   "YTKIT_SOCIAL": os.path.join(TMP, "social.json")})
for k in ("META_PAGE_ID", "META_PAGE_TOKEN", "IG_USER_ID", "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET",
          "TIKTOK_REFRESH_TOKEN"):
    os.environ.pop(k, None)
import ytkit  # noqa: E402

ytkit.time.sleep = lambda s: None
PASS, FAIL = [], []


def run(*argv):
    o, e = io.StringIO(), io.StringIO()
    with redirect_stdout(o), redirect_stderr(e):
        code = ytkit.main(list(argv))
    try:
        d = json.loads(o.getvalue()) if o.getvalue().strip() else None
    except ValueError:
        d = o.getvalue()
    return code, d, e.getvalue()


def check(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else "  -> %s" % (info,)))


video = os.path.join(TMP, "short.mp4")
with open(video, "wb") as f:
    f.write(os.urandom(12 * 1024 * 1024 + 4321))       # 12 MB -> TikTok sends one 10 MB chunk + remainder
size = os.path.getsize(video)

c, d, e = run("post", "facebook", video, "--caption", "hi", "--yes")
check("post without login -> clear error", c == 1 and "META_PAGE_ID" in d[0]["error"], (c, d, e))

c, d, e = run("social", "check")
check("social check when nothing connected", c == 0 and "not connected" in d["facebook"] and "not connected" in d["tiktok"], d)

c, d, e = run("social", "meta-token", "--app-id", "A", "--app-secret", "S", "--user-token", "SHORT")
saved = json.load(open(os.environ["YTKIT_SOCIAL"]))
check("meta-token saves page token + IG id", c == 0 and saved == {"META_PAGE_ID": "PAGE1", "META_PAGE_TOKEN": "PAGE-TOK",
      "IG_USER_ID": "IG1"} and d["instagram_linked"], (d, saved))
check("meta-token exchanges for a long-lived token",
      ("GET", "/v24.0/oauth/access_token", {"grant_type": "fb_exchange_token", "client_id": "A",
       "client_secret": "S", "fb_exchange_token": "SHORT"}) in LOG)

n = len(LOG)
c, d, e = run("post", "all", video, "--caption", "POV: test #warthunder")
check("post is a dry run without --yes", c == 0 and d["dry_run"] and len(LOG) == n and d["platforms"] == [
      "facebook", "instagram", "tiktok"], d)

c, d, e = run("post", "facebook", video, "--caption", "POV: test #warthunder", "--yes")
check("facebook reel: start, upload, finish", c == 0 and d[0]["video_id"] == "FBV1" and GOT["fb_bytes"] == size
      and GOT["fb_finish"]["video_state"] == "PUBLISHED" and GOT["fb_finish"]["description"] == "POV: test #warthunder", (d, GOT))

capfile = os.path.join(TMP, "cap.txt")
open(capfile, "w", encoding="utf-8").write("From file #shorts")
c, d, e = run("post", "instagram", video, "--caption", "@" + capfile, "--yes")
check("instagram reel: resumable upload + publish + permalink", c == 0 and d[0]["url"].endswith("/reel/XYZ/")
      and GOT["ig_bytes"] == size and GOT["ig_box"]["media_type"] == "REELS" and GOT["ig_box"]["caption"] == "From file #shorts"
      and GOT["ig_box"]["share_to_feed"] == "true", (d, GOT["ig_box"]))

os.environ.update({"TIKTOK_CLIENT_KEY": "CK", "TIKTOK_CLIENT_SECRET": "CS"})
ytkit.save_social({"TIKTOK_REFRESH_TOKEN": "TT-RT"})
c, d, e = run("post", "tiktok", video, "--title", "POV tiktok", "--yes")
init = GOT["tt_init"]
check("tiktok init: file upload + chunk maths", c == 0 and init["source_info"] == {
      "source": "FILE_UPLOAD", "video_size": size, "chunk_size": 10485760, "total_chunk_count": 1}
      and init["post_info"]["privacy_level"] == "SELF_ONLY" and init["post_info"]["title"] == "POV tiktok", (c, d, e, init))
check("tiktok chunks: last chunk takes the remainder", GOT["tt_chunks"] == [("bytes 0-%d/%d" % (size - 1, size), size)],
      GOT["tt_chunks"])
check("tiktok status polled", d and d[0]["status"] == "PUBLISH_COMPLETE", d)
check("rotated tiktok refresh token saved", json.load(open(os.environ["YTKIT_SOCIAL"]))["TIKTOK_REFRESH_TOKEN"] == "TT-RT2")

c, d, e = run("post", "tiktok", video, "--title", "tt", "--yes", "--privacy", "PUBLIC_TO_EVERYONE")
check("tiktok refuses a privacy the app can't use", c == 1 and "SELF_ONLY" in d[0]["error"], (c, d))

big = os.path.join(TMP, "big.mp4")
with open(big, "wb") as f:
    f.write(b"\0" * (25 * 1024 * 1024 + 7))
GOT["tt_chunks"] = []
c, d, e = run("post", "tiktok", big, "--title", "big", "--yes")
check("tiktok 25 MB -> 2 chunks, last one bigger", [n for _, n in GOT["tt_chunks"]] == [10485760, 15728647]
      and GOT["tt_init"]["source_info"]["total_chunk_count"] == 2, GOT["tt_chunks"])

c, d, e = run("social", "check")
check("social check reports all three", c == 0 and d["facebook"] == "Grinder" and d["instagram"] == "@grinder"
      and d["tiktok"].startswith("@grinder"), d)

os.environ["META_PAGE_TOKEN"] = "WRONG"
c, d, e = run("post", "facebook", video, "--caption", "x", "--yes")
check("bad Meta token -> readable error", c == 1 and "Invalid OAuth" in d[0]["error"], d)
os.environ.pop("META_PAGE_TOKEN")

print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
srv.shutdown()
sys.exit(1 if FAIL else 0)
