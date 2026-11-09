#!/usr/bin/env python3
"""ytkit - a free, self-hosted replacement for the vidIQ features the Grinder
channel uses. Python 3.9+ standard library only (no pip installs).

It talks to Google's own free APIs with your own OAuth credentials:
  * YouTube Data API v3      (channel, videos, comments, search, uploads, edits)
  * YouTube Analytics API v2 (views, watch time, retention, traffic, search terms)
  * YouTube Reporting API v1 (bulk daily reports, e.g. thumbnail impressions/CTR)
  * YouTube/Google autocomplete (keyword ideas, no key needed)

Credentials, first match wins:
  1. env var YTKIT_CREDS (one line printed by `ytkit setup`), or the three env vars
     YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
  2. token file at $YTKIT_TOKEN, else ~/.ytkit/token.json (written by `ytkit auth`)

Safety: every command that changes something public needs --yes.
Uploads are always private unless --privacy/--publish-at is given with --yes.
There is deliberately no delete command.

Run `python ytkit.py -h` or `python ytkit.py <command> -h` for help.
"""
import argparse
import base64
import datetime as dt
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import mimetypes
import os
import re
import secrets
import statistics
import string
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

VERSION = "1.1.2"

API = os.environ.get("YTKIT_API_BASE", "https://www.googleapis.com")
ANALYTICS = os.environ.get("YTKIT_ANALYTICS_BASE", "https://youtubeanalytics.googleapis.com")
REPORTING = os.environ.get("YTKIT_REPORTING_BASE", "https://youtubereporting.googleapis.com")
TOKEN_URL = os.environ.get("YTKIT_TOKEN_URL", "https://oauth2.googleapis.com/token")
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SUGGEST = os.environ.get("YTKIT_SUGGEST_BASE", "https://suggestqueries.google.com")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

HOME = os.environ.get("YTKIT_HOME") or os.path.join(os.path.expanduser("~"), ".ytkit")
TOKEN_FILE = os.environ.get("YTKIT_TOKEN") or os.path.join(HOME, "token.json")

# Approximate Data API quota costs (default daily quota is 10,000 units).
COST = {"list": 1, "search": 100, "update": 50, "insert": 50, "upload": 1600,
        "thumbnail": 50, "captions_download": 200}

CHUNK = 8 * 1024 * 1024  # upload chunk, a multiple of 256 KiB


class YtError(Exception):
    pass


# ----------------------------------------------------------------- utilities

def out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def pacific_today():
    # Quota resets at midnight Pacific time. Approximate PT as UTC-8 (-7 in DST
    # is close enough for a local counter).
    return (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(hours=8)).strftime("%Y-%m-%d")


def add_quota(units, what):
    try:
        os.makedirs(HOME, exist_ok=True)
        path = os.path.join(HOME, "quota.json")
        data = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        day = pacific_today()
        if data.get("day") != day:
            data = {"day": day, "units": 0, "calls": {}}
        data["units"] += units
        data["calls"][what] = data["calls"].get(what, 0) + 1
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def iso_duration_seconds(d):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return None
    days, h, mi, s = (int(x or 0) for x in m.groups())
    return days * 86400 + h * 3600 + mi * 60 + s


def date_arg(s, default_days_ago=None):
    if s is None:
        return (dt.date.today() - dt.timedelta(days=default_days_ago)).isoformat()
    if re.fullmatch(r"\d+d", s):
        return (dt.date.today() - dt.timedelta(days=int(s[:-1]))).isoformat()
    dt.date.fromisoformat(s)
    return s


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ---------------------------------------------------------------- credentials

def encode_creds(cid, csec, rt):
    raw = json.dumps({"client_id": cid, "client_secret": csec, "refresh_token": rt}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def load_creds():
    packed = os.environ.get("YTKIT_CREDS", "").strip()
    if packed:
        try:
            data = json.loads(base64.urlsafe_b64decode(packed + "=" * (-len(packed) % 4)))
            data["_source"] = "env YTKIT_CREDS"
            return data
        except (ValueError, TypeError):
            raise YtError("YTKIT_CREDS is set but is not valid. Copy it again from connect-youtube.bat.")
    cid, csec, rt = (os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
    if cid and csec and rt:
        return {"client_id": cid, "client_secret": csec, "refresh_token": rt, "_source": "env"}
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, encoding="utf-8") as f:
            data = json.load(f)
        data["_source"] = TOKEN_FILE
        return data
    raise YtError("No credentials. Set YTKIT_CREDS (or YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN), "
                  "or double-click connect-youtube.bat once on the PC.")


_ACCESS = {"token": None, "exp": 0}


def access_token():
    if _ACCESS["token"] and time.time() < _ACCESS["exp"] - 60:
        return _ACCESS["token"]
    c = load_creds()
    body = urllib.parse.urlencode({
        "client_id": c["client_id"], "client_secret": c["client_secret"],
        "refresh_token": c["refresh_token"], "grant_type": "refresh_token"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body), timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")
        hint = ""
        if "invalid_grant" in msg:
            hint = (" The refresh token was revoked or expired. If the OAuth consent screen is still "
                    "in 'Testing', tokens die after 7 days: publish it to 'In production', then run "
                    "`ytkit auth` again.")
        raise YtError("Token refresh failed (%s): %s%s" % (e.code, msg.strip(), hint))
    _ACCESS["token"] = data["access_token"]
    _ACCESS["exp"] = time.time() + int(data.get("expires_in", 3600))
    # Google only sends this for logins that expire (e.g. an app still in Testing).
    _ACCESS["rt_expires_in"] = data.get("refresh_token_expires_in")
    return _ACCESS["token"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def http(method, url, params=None, body=None, headers=None, raw=False, auth=True,
         return_response=False, timeout=60):
    if params:
        params = {k: v for k, v in params.items() if v is not None}
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    hdrs = dict(headers or {})
    if auth:
        hdrs["Authorization"] = "Bearer " + access_token()
    data = None
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
        else:
            data = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    for attempt in range(4):
        try:
            resp = _OPENER.open(req, timeout=timeout)
            if return_response:
                return resp
            with resp:
                payload = resp.read()
            if raw:
                return payload
            return json.loads(payload) if payload.strip() else {}
        except urllib.error.HTTPError as e:
            if return_response and e.code == 308:
                return e
            if e.code in (500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            text = e.read().decode(errors="replace")
            try:
                err = json.loads(text)["error"]
                reason = err.get("errors", [{}])[0].get("reason", "")
                text = "%s %s" % (err.get("message", ""), "(%s)" % reason if reason else "")
                if reason in ("quotaExceeded", "dailyLimitExceeded"):
                    text += " Daily API quota used up; it resets at midnight Pacific time."
            except (ValueError, KeyError, TypeError, IndexError):
                pass
            raise YtError("HTTP %s on %s %s: %s" % (e.code, method, url.split("?")[0], text.strip()))
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise YtError("Network error on %s: %s" % (url.split("?")[0], e.reason))


def yt(method, resource, params=None, body=None, cost="list"):
    add_quota(COST.get(cost, 1), resource + ":" + cost)
    return http(method, API + "/youtube/v3/" + resource, params, body)


# ---------------------------------------------------------------- auth (PC)

def cmd_auth(a):
    with open(a.client_secret, encoding="utf-8") as f:
        cs = json.load(f)
    cs = cs.get("installed") or cs.get("web") or cs
    cid, csec = cs["client_id"], cs["client_secret"]
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    got = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q or "error" in q:
                got.update({k: v[0] for k, v in q.items()})
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                ok = "code" in q and q.get("state", [""])[0] == state
                self.wfile.write(("<h2>%s</h2><p>You can close this tab.</p>" % (
                    "ytkit is connected to your channel." if ok else "Sign-in failed: %s" % q.get("error", ["state mismatch"])[0])).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *x):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    redirect = "http://127.0.0.1:%d" % srv.server_port
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent",
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
    print("Opening your browser to sign in. If it does not open, paste this link into it:\n\n" + url + "\n")
    print("Pick the Google account AND the Grinder channel when asked.")
    webbrowser.open(url)
    t = threading.Thread(target=lambda: [srv.handle_request() for _ in range(20) if not got])
    t.start()
    t.join(timeout=600)
    srv.server_close()
    if got.get("state") != state or "code" not in got:
        raise YtError("Sign-in did not complete: %s" % (got.get("error") or "timed out or state mismatch"))
    body = urllib.parse.urlencode({
        "code": got["code"], "client_id": cid, "client_secret": csec, "redirect_uri": redirect,
        "grant_type": "authorization_code", "code_verifier": verifier}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body), timeout=30) as r:
            tok = json.load(r)
    except urllib.error.HTTPError as e:
        raise YtError("Google refused the sign-in code (%s): %s" % (e.code, e.read().decode(errors="replace").strip()))
    if "refresh_token" not in tok:
        raise YtError("Google returned no refresh token. Remove ytkit's access at "
                      "https://myaccount.google.com/permissions and run auth again.")
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump({"client_id": cid, "client_secret": csec, "refresh_token": tok["refresh_token"],
                   "scopes": tok.get("scope", "")}, f, indent=2)
    print("\nSaved credentials to " + TOKEN_FILE)
    _ACCESS.update(token=tok["access_token"], exp=time.time() + int(tok.get("expires_in", 3600)))
    ch = yt("GET", "channels", {"part": "snippet", "mine": "true"}).get("items", [])
    print("Connected channel: %s" % (ch[0]["snippet"]["title"] if ch else "NONE (pick the channel, not just the account)"))
    if a.show_env:
        line = "YTKIT_CREDS=" + encode_creds(cid, csec, tok["refresh_token"])
        copied = copy_to_clipboard(line)
        print("\nLast step, for Claude's cloud threads: add this ONE line as an environment variable")
        print("in Claude > Project settings > Cloud environment > gear next to Default.")
        print("Do NOT paste it into the chat. It is your login.\n")
        print(line)
        if copied:
            print("\n(It is already copied to your clipboard. Just paste it with Ctrl+V.)")


def copy_to_clipboard(text):
    try:
        import subprocess
        if os.name == "nt":
            subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True)
            return True
        for cmd in (["pbcopy"], ["xclip", "-selection", "clipboard"]):
            try:
                subprocess.run(cmd, input=text.encode(), check=True)
                return True
            except (OSError, subprocess.CalledProcessError):
                continue
    except Exception:
        pass
    return False


def find_client_secret(folders):
    found = []
    for d in folders:
        try:
            for n in os.listdir(d):
                if n.lower().startswith("client_secret") and n.lower().endswith(".json"):
                    p = os.path.join(d, n)
                    found.append((os.path.getmtime(p), p))
        except OSError:
            continue
    return max(found)[1] if found else None


CONSOLE = "https://console.cloud.google.com"
SETUP_STEPS = [
    ("Create a Google Cloud project and turn on the 3 YouTube APIs",
     CONSOLE + "/flows/enableapi?apiid=youtube.googleapis.com,youtubeanalytics.googleapis.com,youtubereporting.googleapis.com",
     ["Sign in with the Google account that owns the Grinder channel.",
      "If it asks for a project, choose CREATE PROJECT and call it ytkit (no card needed).",
      "Click Next, then Enable."]),
    ("Set up the sign-in screen", CONSOLE + "/auth/overview",
     ["Click Get started. App name: ytkit. Support email: yours.",
      "Audience: External. Contact email: yours. Tick the agreement. Create."]),
    ("Publish the app so the login does not expire every 7 days", CONSOLE + "/auth/audience",
     ["Click Publish app, then Confirm. It should now say In production."]),
    ("Create the login key", CONSOLE + "/auth/clients/create",
     ["Application type: Desktop app. Name: ytkit. Create.",
      "In the box that appears, click Download JSON. Leave it in Downloads; I will find it."]),
]


def cmd_setup(a):
    """Guided first-time setup: opens each Google page, then signs in."""
    here = os.path.dirname(os.path.abspath(__file__))
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    print("ytkit setup. About 10 minutes. I open each page for you; you click in the browser.\n")
    cs = find_client_secret([here, downloads])
    if cs and not a.redo:
        print("Found your login key already: %s. Skipping straight to sign-in.\n" % cs)
    else:
        for i, (title, url, todo) in enumerate(SETUP_STEPS, 1):
            print("STEP %d of %d: %s" % (i, len(SETUP_STEPS) + 1, title))
            for t in todo:
                print("   - " + t)
            print("   (page: %s)" % url)
            webbrowser.open(url)
            if i < len(SETUP_STEPS):
                input("   Press Enter here when that page is done... ")
            print()
        print("Waiting for the client_secret...json download (up to 10 minutes)...")
        start = time.time()
        while time.time() - start < 600:
            cs = find_client_secret([here, downloads])
            if cs:
                break
            time.sleep(2)
        if not cs:
            raise YtError("No client_secret*.json appeared in Downloads. Download it from the Clients page and run this again.")
    if os.path.dirname(os.path.abspath(cs)) != here:
        import shutil
        dest = os.path.join(here, os.path.basename(cs))
        shutil.copy2(cs, dest)
        cs = dest
        print("Copied the key into " + here)
    print("\nSTEP %d of %d: sign in and pick the Grinder channel" % (len(SETUP_STEPS) + 1, len(SETUP_STEPS) + 1))
    print("   - Google says 'Google hasn't verified this app'. That is normal for your own app:")
    print("     click Advanced, then Go to ytkit. Tick every box and Continue.\n")
    cmd_auth(argparse.Namespace(client_secret=cs, show_env=True))


# ------------------------------------------------------------- channel/videos

def get_channel(cid=None, handle=None):
    p = {"part": "snippet,statistics,contentDetails"}
    if handle:
        p["forHandle"] = handle if handle.startswith("@") else "@" + handle
    elif cid:
        p["id"] = cid
    else:
        p["mine"] = "true"
    items = yt("GET", "channels", p).get("items", [])
    if not items:
        raise YtError("Channel not found: %s" % (handle or cid or "mine"))
    return items[0]


def resolve_channel(ref):
    if not ref or ref == "mine":
        return get_channel()
    if ref.startswith("UC") and len(ref) == 24:
        return get_channel(cid=ref)
    return get_channel(handle=ref)


def slim_channel(c):
    s, st = c["snippet"], c.get("statistics", {})
    return {"id": c["id"], "title": s.get("title"), "handle": s.get("customUrl"),
            "subscribers": int(st.get("subscriberCount", 0)) if not st.get("hiddenSubscriberCount") else None,
            "views": int(st.get("viewCount", 0)), "videos": int(st.get("videoCount", 0)),
            "created": s.get("publishedAt", "")[:10],
            "uploads_playlist": c.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")}


def cmd_channel(a):
    out(slim_channel(resolve_channel(a.channel)))


def video_details(ids, parts="snippet,statistics,contentDetails,status"):
    res = []
    for group in chunks(list(ids), 50):
        res += yt("GET", "videos", {"part": parts, "id": ",".join(group), "maxResults": 50}).get("items", [])
    return res


def slim_video(v, full=False):
    s, st, cd = v.get("snippet", {}), v.get("statistics", {}), v.get("contentDetails", {})
    secs = iso_duration_seconds(cd.get("duration"))
    d = {"id": v["id"], "title": s.get("title"), "published": s.get("publishedAt", "")[:16].replace("T", " "),
         "duration_s": secs, "short": secs is not None and secs <= 180,
         "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)) if "likeCount" in st else None,
         "comments": int(st.get("commentCount", 0)) if "commentCount" in st else None}
    if "status" in v:
        d["privacy"] = v["status"].get("privacyStatus")
        if v["status"].get("publishAt"):
            d["publish_at"] = v["status"]["publishAt"]
    if full:
        d.update({"channel": s.get("channelTitle"), "channel_id": s.get("channelId"),
                  "description": s.get("description"), "tags": s.get("tags", []),
                  "category_id": s.get("categoryId"), "default_language": s.get("defaultLanguage"),
                  "thumbnail": (s.get("thumbnails", {}).get("maxres") or s.get("thumbnails", {}).get("high") or {}).get("url")})
    return d


def channel_uploads(ch, limit):
    pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while len(ids) < limit:
        r = yt("GET", "playlistItems", {"part": "contentDetails", "playlistId": pl, "maxResults": 50, "pageToken": token})
        ids += [i["contentDetails"]["videoId"] for i in r.get("items", [])]
        token = r.get("nextPageToken")
        if not token:
            break
    return video_details(ids[:limit])


def cmd_videos(a):
    ch = resolve_channel(a.channel)
    vids = [slim_video(v) for v in channel_uploads(ch, a.limit)]
    if a.shorts:
        vids = [v for v in vids if v["short"]]
    if a.long:
        vids = [v for v in vids if not v["short"]]
    out(vids)


def cmd_video(a):
    out([slim_video(v, full=True) for v in video_details(a.ids)])


def cmd_outliers(a):
    """Which of a channel's recent videos beat that channel's own median."""
    ch = resolve_channel(a.channel)
    vids = [slim_video(v) for v in channel_uploads(ch, a.limit)]
    out_list = []
    for kind in ("short", "long"):
        group = [v for v in vids if v["short"] == (kind == "short")]
        if not group:
            continue
        med = statistics.median([v["views"] for v in group]) or 1
        for v in group:
            v["vs_median"] = round(v["views"] / med, 2)
        out_list.append({"type": kind, "count": len(group), "median_views": med,
                         "top": sorted(group, key=lambda v: -v["vs_median"])[:a.top]})
    out({"channel": slim_channel(ch)["title"], "groups": out_list})


# ------------------------------------------------------------------- search

def cmd_search(a):
    p = {"part": "snippet", "q": a.query, "type": a.type, "order": a.order,
         "maxResults": min(a.limit, 50), "regionCode": a.region, "relevanceLanguage": a.lang,
         "publishedAfter": (date_arg(a.since) + "T00:00:00Z") if a.since else None,
         "videoDuration": a.duration if a.type == "video" else None}
    r = yt("GET", "search", p, cost="search")
    total = r.get("pageInfo", {}).get("totalResults")
    if a.type == "channel":
        ids = [i["id"]["channelId"] for i in r.get("items", [])]
        chans = yt("GET", "channels", {"part": "snippet,statistics,contentDetails", "id": ",".join(ids)}).get("items", [])
        out({"query": a.query, "total_results_estimate": total, "channels": [slim_channel(c) for c in chans]})
        return
    ids = [i["id"]["videoId"] for i in r.get("items", []) if i["id"].get("videoId")]
    vids = video_details(ids, "snippet,statistics,contentDetails")
    ch_ids = sorted({v["snippet"]["channelId"] for v in vids})
    subs = {}
    for group in chunks(ch_ids, 50):
        for c in yt("GET", "channels", {"part": "statistics", "id": ",".join(group)}).get("items", []):
            subs[c["id"]] = int(c["statistics"].get("subscriberCount", 0) or 0)
    rows = []
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    for v in vids:
        d = slim_video(v)
        d["channel"] = v["snippet"]["channelTitle"]
        d["channel_subs"] = subs.get(v["snippet"]["channelId"])
        pub = dt.datetime.strptime(v["snippet"]["publishedAt"][:19], "%Y-%m-%dT%H:%M:%S")
        days = max((now - pub).total_seconds() / 86400, 0.5)
        d["views_per_day"] = round(d["views"] / days)
        d["outlier_score"] = round(d["views"] / max(d["channel_subs"] or 1, 100), 2)
        rows.append(d)
    if a.sort == "outlier":
        rows.sort(key=lambda d: -d["outlier_score"])
    elif a.sort == "velocity":
        rows.sort(key=lambda d: -d["views_per_day"])
    out({"query": a.query, "total_results_estimate": total,
         "note": "outlier_score = views / channel subscribers (min 100). >1 means it reached beyond the channel's audience.",
         "videos": rows})


# ----------------------------------------------------------------- keywords

def suggest(q, lang="en", region="GB"):
    url = SUGGEST + "/complete/search"
    raw = http("GET", url, {"client": "firefox", "ds": "yt", "q": q, "hl": lang, "gl": region},
               raw=True, auth=False, headers={"User-Agent": "Mozilla/5.0 ytkit"}, timeout=15)
    data = json.loads(raw.decode("utf-8", errors="replace"))
    return data[1] if isinstance(data, list) and len(data) > 1 else []


def cmd_keywords(a):
    """Autocomplete expansion: what people actually type into YouTube search."""
    seen, rows = {}, []
    probes = [a.seed] + (["%s %s" % (a.seed, c) for c in string.ascii_lowercase] if a.deep else [])
    probes += ["%s %s" % (w, a.seed) for w in ("how", "why", "best", "is")] if a.deep else []
    for rank_probe, q in enumerate(probes):
        try:
            sugg = suggest(q, a.lang, a.region)
        except YtError as e:
            if rank_probe == 0:
                raise YtError(str(e) + " (autocomplete host blocked? It needs suggestqueries.google.com)")
            continue
        for pos, s in enumerate(sugg):
            if s not in seen:
                seen[s] = {"keyword": s, "score": 0, "hits": 0, "best_position": pos + 1}
                rows.append(seen[s])
            seen[s]["hits"] += 1
            seen[s]["best_position"] = min(seen[s]["best_position"], pos + 1)
            # Autocomplete orders by popularity. Showing up high, for the bare seed,
            # and from several probes all mean more people search it.
            seen[s]["score"] += max(15 - pos, 1) * (3 if rank_probe == 0 else 1)
        time.sleep(0.15)
    rows.sort(key=lambda r: (-r["score"], r["best_position"]))
    result = {"seed": a.seed, "count": len(rows), "keywords": rows[:a.limit],
              "note": "score is a relative demand signal from autocomplete rank, not a search-volume number"}
    if a.competition:
        comp = []
        for r in rows[:a.competition]:
            s = yt("GET", "search", {"part": "id", "q": r["keyword"], "type": "video", "maxResults": 10,
                                     "publishedAfter": (dt.date.today() - dt.timedelta(days=90)).isoformat() + "T00:00:00Z"},
                   cost="search")
            ids = [i["id"]["videoId"] for i in s.get("items", [])]
            views = [int(v.get("statistics", {}).get("viewCount", 0)) for v in video_details(ids, "statistics")]
            comp.append({"keyword": r["keyword"],
                         "results_last_90d_estimate": s.get("pageInfo", {}).get("totalResults"),
                         "top10_median_views": statistics.median(views) if views else 0})
        result["competition"] = comp
        result["note"] = "competition costs 100 quota units per keyword"
    out(result)


# ---------------------------------------------------------------- analytics

def analytics(start, end, metrics, dimensions=None, filters=None, sort=None, limit=None, channel="MINE"):
    params = {"ids": "channel==" + channel, "startDate": start, "endDate": end, "metrics": metrics,
              "dimensions": dimensions, "filters": filters, "sort": sort, "maxResults": limit}
    r = http("GET", ANALYTICS + "/v2/reports", params)
    cols = [h["name"] for h in r.get("columnHeaders", [])]
    return [dict(zip(cols, row)) for row in r.get("rows", []) or []]


PRESETS = {
    "overview": dict(metrics="views,engagedViews,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                             "subscribersGained,subscribersLost,likes,comments,shares"),
    "daily": dict(metrics="views,estimatedMinutesWatched,subscribersGained,subscribersLost", dimensions="day", sort="day"),
    "content-type": dict(metrics="views,engagedViews,estimatedMinutesWatched,averageViewDuration,subscribersGained",
                         dimensions="creatorContentType"),
    "traffic": dict(metrics="views,estimatedMinutesWatched", dimensions="insightTrafficSourceType", sort="-views"),
    "traffic-by-type": dict(metrics="views", dimensions="creatorContentType,insightTrafficSourceType", sort="-views"),
    "top-videos": dict(metrics="views,engagedViews,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                               "subscribersGained,likes,comments,shares", dimensions="video", sort="-views", limit=25),
    "search-terms": dict(metrics="views", dimensions="insightTrafficSourceDetail",
                         filters="insightTrafficSourceType==YT_SEARCH", sort="-views", limit=25),
    "suggested-from": dict(metrics="views", dimensions="insightTrafficSourceDetail",
                           filters="insightTrafficSourceType==RELATED_VIDEO", sort="-views", limit=25),
    "geo": dict(metrics="views,estimatedMinutesWatched", dimensions="country", sort="-views", limit=25),
    "devices": dict(metrics="views,estimatedMinutesWatched", dimensions="deviceType", sort="-views"),
    "demographics": dict(metrics="viewerPercentage", dimensions="ageGroup,gender"),
    "subscribed": dict(metrics="views,estimatedMinutesWatched,averageViewDuration", dimensions="subscribedStatus"),
    "playback": dict(metrics="views", dimensions="insightPlaybackLocationType", sort="-views"),
}


# The API wants camelCase values; accept the friendlier upper-case names too.
CONTENT_TYPES = {"SHORTS": "shorts", "VIDEO_ON_DEMAND": "videoOnDemand", "LIVE_STREAM": "liveStream",
                 "shorts": "shorts", "videoOnDemand": "videoOnDemand", "liveStream": "liveStream"}


def cmd_report(a):
    start, end = date_arg(a.start, 28), date_arg(a.end, 0)
    if a.preset == "retention":
        if not a.video:
            raise YtError("retention needs --video ID")
        rows = analytics(start, end, "audienceWatchRatio,relativeRetentionPerformance",
                         "elapsedVideoTimeRatio", "video==" + a.video)
        out({"video": a.video, "start": start, "end": end,
             "note": "elapsedVideoTimeRatio 0.01 = 1% into the video; audienceWatchRatio 1.0 = everyone still watching "
                     "(can be >1 with rewatches); relativeRetentionPerformance 0.5 = average for similar-length videos.",
             "rows": rows})
        return
    p = dict(PRESETS[a.preset])
    filters = [f for f in (p.get("filters"), ("video==" + a.video) if a.video else None,
                           ("creatorContentType==" + CONTENT_TYPES[a.content_type]) if a.content_type else None) if f]
    p["filters"] = ";".join(filters) or None
    if a.limit:
        p["limit"] = a.limit
    rows = analytics(start, end, p["metrics"], p.get("dimensions"), p["filters"], p.get("sort"), p.get("limit"))
    if a.preset == "top-videos" and rows:
        titles = {v["id"]: slim_video(v) for v in video_details([r["video"] for r in rows], "snippet,contentDetails")}
        for r in rows:
            t = titles.get(r["video"], {})
            r["title"], r["short"] = t.get("title"), t.get("short")
    out({"preset": a.preset, "start": start, "end": end, "rows": rows})


def cmd_analytics(a):
    """Raw Analytics API query for anything the presets do not cover."""
    out(analytics(date_arg(a.start, 28), date_arg(a.end, 0), a.metrics, a.dimensions, a.filters, a.sort, a.limit))


# --------------------------------------------------------- reporting (bulk)

def cmd_reporting(a):
    base = REPORTING + "/v1"
    if a.action == "types":
        out(http("GET", base + "/reportTypes").get("reportTypes", []))
    elif a.action == "jobs":
        out(http("GET", base + "/jobs").get("jobs", []))
    elif a.action == "create":
        if not a.type:
            raise YtError("create needs --type (see `reporting types`)")
        out(http("POST", base + "/jobs", body={"reportTypeId": a.type, "name": "ytkit " + a.type}))
    elif a.action == "fetch":
        jobs = [j for j in http("GET", base + "/jobs").get("jobs", []) if not a.type or j["reportTypeId"] == a.type]
        if not jobs:
            raise YtError("No reporting job%s. Create one first; the first files appear about 2 days later." % (
                " for " + a.type if a.type else ""))
        os.makedirs(a.dir, exist_ok=True)
        fetched = []
        for j in jobs:
            reps = http("GET", "%s/jobs/%s/reports" % (base, j["id"])).get("reports", [])
            reps.sort(key=lambda r: r.get("startTime", ""), reverse=True)
            for r in reps[:a.latest]:
                name = "%s_%s.csv" % (j["reportTypeId"], r.get("startTime", "")[:10])
                path = os.path.join(a.dir, name)
                if not os.path.exists(path):
                    with open(path, "wb") as f:
                        f.write(http("GET", r["downloadUrl"], raw=True))
                fetched.append(path)
        out({"files": fetched})


# ------------------------------------------------------------------ comments

def slim_thread(t):
    top = t["snippet"]["topLevelComment"]
    s = top["snippet"]
    d = {"comment_id": top["id"], "video_id": t["snippet"].get("videoId"), "author": s.get("authorDisplayName"),
         "author_channel_id": (s.get("authorChannelId") or {}).get("value"),
         "text": s.get("textOriginal"), "likes": s.get("likeCount"), "published": s.get("publishedAt", "")[:16],
         "reply_count": t["snippet"].get("totalReplyCount", 0), "can_reply": t["snippet"].get("canReply")}
    reps = t.get("replies", {}).get("comments", [])
    if reps:
        d["replies"] = [{"author": r["snippet"].get("authorDisplayName"),
                         "author_channel_id": (r["snippet"].get("authorChannelId") or {}).get("value"),
                         "text": r["snippet"].get("textOriginal")} for r in reps]
    return d


def cmd_comments(a):
    p = {"part": "snippet,replies", "maxResults": min(a.limit, 100), "order": a.order, "textFormat": "plainText",
         "moderationStatus": a.status if a.status != "published" else None}
    if a.video:
        p["videoId"] = a.video
    else:
        p["allThreadsRelatedToChannelId"] = get_channel()["id"]
    rows, token = [], None
    while len(rows) < a.limit:
        p["pageToken"] = token
        r = yt("GET", "commentThreads", p)
        rows += [slim_thread(t) for t in r.get("items", [])]
        token = r.get("nextPageToken")
        if not token:
            break
    rows = rows[:a.limit]
    if a.unanswered:
        me = get_channel()["id"]
        rows = [r for r in rows if r["author_channel_id"] != me
                and not any(x["author_channel_id"] == me for x in r.get("replies", []))]
    out(rows)


def need_yes(a, what):
    if not a.yes:
        raise YtError("%s is public-facing. Re-run with --yes once Jozsef has approved it." % what)


def cmd_reply(a):
    need_yes(a, "Replying to a comment")
    r = yt("POST", "comments", {"part": "snippet"},
           {"snippet": {"parentId": a.comment_id, "textOriginal": a.text}}, cost="insert")
    out({"posted": True, "reply_id": r.get("id")})


# ------------------------------------------------------------ edits/uploads

def read_text_arg(v):
    if v and v.startswith("@") and os.path.exists(v[1:]):
        with open(v[1:], encoding="utf-8") as f:
            return f.read()
    return v


def cmd_update(a):
    v = video_details([a.id], "snippet,status")
    if not v:
        raise YtError("Video not found: " + a.id)
    v = v[0]
    sn, st = v["snippet"], v["status"]
    new_sn = {k: sn[k] for k in ("title", "description", "categoryId", "tags", "defaultLanguage",
                                 "defaultAudioLanguage") if k in sn}
    if a.title is not None:
        new_sn["title"] = a.title
    if a.description is not None:
        new_sn["description"] = read_text_arg(a.description)
    if a.tags is not None:
        new_sn["tags"] = [t.strip() for t in a.tags.split(",") if t.strip()]
    if a.category:
        new_sn["categoryId"] = a.category
    new_st = {k: st[k] for k in ("privacyStatus", "publishAt", "embeddable", "license",
                                 "publicStatsViewable", "selfDeclaredMadeForKids", "containsSyntheticMedia") if k in st}
    if a.privacy:
        new_st["privacyStatus"] = a.privacy
    if a.publish_at:
        new_st["publishAt"], new_st["privacyStatus"] = a.publish_at, "private"
    if a.synthetic is not None:
        new_st["containsSyntheticMedia"] = a.synthetic == "yes"
    changes = {k: (sn.get(k), new_sn[k]) for k in new_sn if sn.get(k) != new_sn[k]}
    changes.update({k: (st.get(k), new_st[k]) for k in new_st if st.get(k) != new_st[k]})
    if not changes:
        out({"changed": False})
        return
    if not a.yes:
        out({"dry_run": True, "would_change": changes, "hint": "re-run with --yes to apply"})
        return
    yt("PUT", "videos", {"part": "snippet,status"}, {"id": a.id, "snippet": new_sn, "status": new_st}, cost="update")
    out({"changed": True, "fields": sorted(changes)})


def cmd_thumbnail(a):
    need_yes(a, "Changing a thumbnail")
    out({"set": True, "items": set_thumbnail(a.id, a.file)})


def set_thumbnail(video_id, path):
    size = os.path.getsize(path)
    if size > 2 * 1024 * 1024:
        raise YtError("Thumbnail must be 2 MB or less (this is %.1f MB)." % (size / 1048576))
    ctype = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        data = f.read()
    add_quota(COST["thumbnail"], "thumbnails:set")
    r = http("POST", API + "/upload/youtube/v3/thumbnails/set", {"videoId": video_id, "uploadType": "media"},
             data, {"Content-Type": ctype})
    return r.get("items")


def cmd_upload(a):
    if (a.privacy != "private" and not a.publish_at) and not a.yes:
        raise YtError("Uploading as %s is public-facing. Use --yes, or upload private (default)." % a.privacy)
    if a.publish_at and not a.yes:
        raise YtError("Scheduling a publish time is public-facing. Re-run with --yes.")
    size = os.path.getsize(a.file)
    ctype = mimetypes.guess_type(a.file)[0] or "video/*"
    status = {"privacyStatus": "private" if a.publish_at else a.privacy,
              "selfDeclaredMadeForKids": a.made_for_kids == "yes",
              "containsSyntheticMedia": a.synthetic == "yes"}
    if a.publish_at:
        status["publishAt"] = a.publish_at
    meta = {"snippet": {"title": a.title, "description": read_text_arg(a.description) or "",
                        "tags": [t.strip() for t in (a.tags or "").split(",") if t.strip()],
                        "categoryId": a.category},
            "status": status}
    if a.language:
        meta["snippet"]["defaultLanguage"] = meta["snippet"]["defaultAudioLanguage"] = a.language
    add_quota(COST["upload"], "videos:upload")
    resp = http("POST", API + "/upload/youtube/v3/videos",
                {"uploadType": "resumable", "part": "snippet,status", "notifySubscribers": str(not a.quiet).lower()},
                meta, {"X-Upload-Content-Length": str(size), "X-Upload-Content-Type": ctype},
                return_response=True)
    session = resp.headers.get("Location")
    resp.close()
    if not session:
        raise YtError("Upload session was not created (no Location header).")
    offset, result = 0, None
    with open(a.file, "rb") as f:
        while offset < size:
            f.seek(offset)
            chunk = f.read(CHUNK)
            end = offset + len(chunk) - 1
            r = http("PUT", session, body=chunk, return_response=True, timeout=300,
                     headers={"Content-Length": str(len(chunk)), "Content-Range": "bytes %d-%d/%d" % (offset, end, size)})
            if getattr(r, "code", None) == 308 or getattr(r, "status", None) == 308:
                rng = r.headers.get("Range")
                offset = int(rng.split("-")[1]) + 1 if rng else 0
                r.close()
            else:
                with r:
                    result = json.loads(r.read())
                offset = size
            sys.stderr.write("\ruploaded %d%%" % (100 * min(offset, size) // max(size, 1)))
    sys.stderr.write("\n")
    if not result or "id" not in result:
        raise YtError("Upload finished without a video id.")
    info = {"uploaded": True, "id": result["id"], "url": "https://youtu.be/" + result["id"],
            "privacy": result.get("status", {}).get("privacyStatus"),
            "publish_at": result.get("status", {}).get("publishAt")}
    if a.thumbnail:
        try:
            set_thumbnail(result["id"], a.thumbnail)
            info["thumbnail"] = "set"
        except YtError as e:
            info["thumbnail"] = "failed: %s" % e
    out(info)


# ------------------------------------------------------------------ captions

def cmd_captions(a):
    tracks = yt("GET", "captions", {"part": "snippet", "videoId": a.id}).get("items", [])
    if not a.download:
        out([{"id": t["id"], "language": t["snippet"].get("language"), "kind": t["snippet"].get("trackKind"),
              "name": t["snippet"].get("name")} for t in tracks])
        return
    pick = next((t for t in tracks if t["snippet"].get("language", "").startswith(a.lang)), tracks[0] if tracks else None)
    if not pick:
        raise YtError("No caption tracks on " + a.id)
    add_quota(COST["captions_download"], "captions:download")
    data = http("GET", API + "/youtube/v3/captions/" + pick["id"], {"tfmt": a.format}, raw=True)
    sys.stdout.write(data.decode("utf-8", errors="replace"))


def cmd_quota(a):
    path = os.path.join(HOME, "quota.json")
    data = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    if data.get("day") != pacific_today():
        data = {"day": pacific_today(), "units": 0, "calls": {}}
    data["daily_limit"] = 10000
    data["note"] = "Local estimate for this machine only. Real numbers: Google Cloud console > APIs > YouTube Data API v3 > Quotas."
    out(data)


def cmd_check(a):
    c = load_creds()
    ch = slim_channel(get_channel())
    rt = _ACCESS.get("rt_expires_in")
    login = "permanent" if not rt else "expires in %.1f days (app still in Testing? publish it, then reconnect)" % (int(rt) / 86400)
    out({"ok": True, "credentials_from": c["_source"], "login": login, "channel": ch["title"], "channel_id": ch["id"],
         "subscribers": ch["subscribers"], "version": VERSION})


# -------------------------------------------------------------------- CLI

def build_parser():
    P = argparse.ArgumentParser(prog="ytkit", description="Free YouTube toolkit (vidIQ replacement).")
    P.add_argument("--version", action="version", version=VERSION)
    sub = P.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("auth", help="one-time Google sign-in on the PC")
    s.add_argument("client_secret", help="path to the client_secret_*.json downloaded from Google Cloud")
    s.add_argument("--show-env", action="store_true", help="print the 3 values for cloud environment variables")
    s.set_defaults(fn=cmd_auth)

    s = sub.add_parser("setup", help="guided first-time setup (opens each Google page, then signs in)")
    s.add_argument("--redo", action="store_true", help="walk through the Google pages even if a key exists")
    s.set_defaults(fn=cmd_setup)

    sub.add_parser("check", help="test credentials and show the connected channel").set_defaults(fn=cmd_check)
    sub.add_parser("quota", help="today's estimated API quota use").set_defaults(fn=cmd_quota)

    s = sub.add_parser("channel", help="channel stats (mine, @handle or UC id)")
    s.add_argument("channel", nargs="?", default="mine")
    s.set_defaults(fn=cmd_channel)

    s = sub.add_parser("videos", help="recent uploads with stats")
    s.add_argument("channel", nargs="?", default="mine")
    s.add_argument("--limit", type=int, default=50)
    g = s.add_mutually_exclusive_group()
    g.add_argument("--shorts", action="store_true")
    g.add_argument("--long", action="store_true")
    s.set_defaults(fn=cmd_videos)

    s = sub.add_parser("video", help="full details for one or more video ids")
    s.add_argument("ids", nargs="+")
    s.set_defaults(fn=cmd_video)

    s = sub.add_parser("outliers", help="a channel's videos that beat its own median (Shorts and long split)")
    s.add_argument("channel", nargs="?", default="mine")
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--top", type=int, default=10)
    s.set_defaults(fn=cmd_outliers)

    s = sub.add_parser("search", help="YouTube search with views/day and outlier score (100 units)")
    s.add_argument("query")
    s.add_argument("--type", choices=["video", "channel"], default="video")
    s.add_argument("--order", choices=["relevance", "viewCount", "date", "rating"], default="relevance")
    s.add_argument("--since", help="YYYY-MM-DD or e.g. 30d")
    s.add_argument("--duration", choices=["any", "short", "medium", "long"], help="short = under 4 min")
    s.add_argument("--limit", type=int, default=25)
    s.add_argument("--region", default="GB")
    s.add_argument("--lang", default="en")
    s.add_argument("--sort", choices=["none", "outlier", "velocity"], default="outlier")
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("keywords", help="keyword ideas from YouTube autocomplete (free)")
    s.add_argument("seed")
    s.add_argument("--deep", action="store_true", help="also try seed+a..z and how/why/best/is prefixes")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--competition", type=int, default=0, help="check competition for the top N (100 units each)")
    s.add_argument("--region", default="GB")
    s.add_argument("--lang", default="en")
    s.set_defaults(fn=cmd_keywords)

    s = sub.add_parser("report", help="analytics presets (your channel)")
    s.add_argument("preset", choices=sorted(list(PRESETS) + ["retention"]))
    s.add_argument("--start", help="YYYY-MM-DD or e.g. 28d (default 28d)")
    s.add_argument("--end", help="YYYY-MM-DD or e.g. 0d (default today)")
    s.add_argument("--video", help="limit to one video id")
    s.add_argument("--content-type", choices=sorted(CONTENT_TYPES))
    s.add_argument("--limit", type=int)
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("analytics", help="raw YouTube Analytics query")
    s.add_argument("--metrics", required=True)
    s.add_argument("--dimensions")
    s.add_argument("--filters")
    s.add_argument("--sort")
    s.add_argument("--limit", type=int)
    s.add_argument("--start")
    s.add_argument("--end")
    s.set_defaults(fn=cmd_analytics)

    s = sub.add_parser("reporting", help="bulk Reporting API (impressions/CTR etc.)")
    s.add_argument("action", choices=["types", "jobs", "create", "fetch"])
    s.add_argument("--type", help="reportTypeId")
    s.add_argument("--dir", default=os.path.join(HOME, "reports"))
    s.add_argument("--latest", type=int, default=7, help="how many most recent daily files to fetch per job")
    s.set_defaults(fn=cmd_reporting)

    s = sub.add_parser("comments", help="recent comments on the channel or one video")
    s.add_argument("--video")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--order", choices=["time", "relevance"], default="time")
    s.add_argument("--status", choices=["published", "heldForReview", "likelySpam"], default="published")
    s.add_argument("--unanswered", action="store_true", help="only threads the channel has not replied to")
    s.set_defaults(fn=cmd_comments)

    s = sub.add_parser("reply", help="reply to a comment (public, needs --yes)")
    s.add_argument("comment_id")
    s.add_argument("text")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_reply)

    s = sub.add_parser("update", help="edit title/description/tags/privacy (dry run without --yes)")
    s.add_argument("id")
    s.add_argument("--title")
    s.add_argument("--description", help="text, or @file.txt")
    s.add_argument("--tags", help="comma separated; replaces existing tags")
    s.add_argument("--category")
    s.add_argument("--privacy", choices=["private", "unlisted", "public"])
    s.add_argument("--publish-at", help="ISO 8601 UTC, e.g. 2026-11-10T17:00:00Z")
    s.add_argument("--synthetic", choices=["yes", "no"], help="altered/synthetic content disclosure")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_update)

    s = sub.add_parser("thumbnail", help="set a custom thumbnail (public, needs --yes)")
    s.add_argument("id")
    s.add_argument("file")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_thumbnail)

    s = sub.add_parser("upload", help="upload a video (private by default, ~1600 units)")
    s.add_argument("file")
    s.add_argument("--title", required=True)
    s.add_argument("--description", default="", help="text, or @file.txt")
    s.add_argument("--tags")
    s.add_argument("--category", default="20", help="20 = Gaming")
    s.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    s.add_argument("--publish-at", help="schedule: ISO 8601 UTC (uploads private, goes public then)")
    s.add_argument("--made-for-kids", choices=["yes", "no"], default="no")
    s.add_argument("--synthetic", choices=["yes", "no"], default="no", help="altered/synthetic content disclosure")
    s.add_argument("--language", default="en")
    s.add_argument("--thumbnail", help="image to set right after upload")
    s.add_argument("--quiet", action="store_true", help="do not notify subscribers")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_upload)

    s = sub.add_parser("captions", help="list or download captions of YOUR videos")
    s.add_argument("id")
    s.add_argument("--download", action="store_true")
    s.add_argument("--lang", default="en")
    s.add_argument("--format", choices=["srt", "vtt", "sbv"], default="srt")
    s.set_defaults(fn=cmd_captions)
    return P


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    # Let "--sort -views" work (argparse would read "-views" as an option).
    for i in range(len(argv) - 1, 0, -1):
        if argv[i - 1] == "--sort" and argv[i].startswith("-"):
            argv[i - 1:i + 1] = ["--sort=" + argv[i]]
    a = build_parser().parse_args(argv)
    try:
        a.fn(a)
    except YtError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print("ERROR: file not found: %s" % e.filename, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
