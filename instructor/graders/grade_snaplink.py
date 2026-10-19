#!/usr/bin/env python3
"""SnapLink (exam version B) auto-grader.

Black-box checks of a running SnapLink service against CONTRACT-B, plus optional
"assist" checks of the student's repository, live Kubernetes objects and the
Docker image. Python 3.9+ standard library only. Never follows redirects.

Instructor-only. See --help for usage.
"""

import argparse
import calendar
import collections
import concurrent.futures
import http.client
import json
import os
import random
import re
import shutil
import socket
import string
import subprocess
import sys
import threading
import time
import urllib.parse

VERSION = "1.0"
TIMEOUT = 5.0  # seconds, every normal request
STORM_TIMEOUT = 15.0  # seconds, requests inside the concurrency storms
RFC3339_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)
CODE_RE = re.compile(r"^[A-Za-z0-9]{6}$")
MUX_DEFAULT_BODIES = (b"404 page not found\n", b"Method Not Allowed\n")
RESERVED = {"api", "healthz", "readyz", "metrics"}
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
SUMMARY_RE = re.compile(r"\d+\s+passed,\s*\d+\s+failed")
# env vars removed before `go test` so the student's tests cannot reach a datastore
NO_DB_ENV = ("STORE", "REDIS_ADDR", "REDIS_PASSWORD", "SNAPLINK_TEST_REDIS_ADDR", "DATABASE_URL")
# goroutine count >= 100: `n = 200`, `const workers = 100`, `i < 100`, `range 100`, `wg.Add(100)`
COUNT_RES = [re.compile(r"\b(?:n|N|num\w*|count|total|workers|goroutines|parallel\w*|concurrency|times|clients|requests|hits|storm\w*)"
                        r"\s*:?=\s*(\d{3,7})\b(?!\s*\*)"),
             re.compile(r"<=?\s*(\d{3,7})\b(?!\s*\*)"),
             re.compile(r"\brange\s+(\d{3,7})\b"),
             re.compile(r"\.Add\(\s*(\d{3,7})\s*\)")]


def goroutine_counts(text):
    return [int(n) for rx in COUNT_RES for n in rx.findall(text)]
# method/route pairs in tests, e.g. httptest.NewRequest(http.MethodPost, "/api/links", ...) or {"GET", "/healthz", ...}
PAIR_RE = re.compile(r'(http\.Method(?:Get|Post|Put|Patch|Delete)|"(?:GET|POST|PUT|PATCH|DELETE)")\s*,\s*"(/[^"]*)"')
ERR_STATUS_RE = re.compile(r"\b(400|404|405|409|422|500|503)\b|http\.Status(BadRequest|NotFound|MethodNotAllowed|Conflict|"
                           r"UnprocessableEntity|InternalServerError|ServiceUnavailable)\b")


def norm_method(m):
    return m.strip('"').upper() if m.startswith('"') else m[len("http.Method"):].upper()


def norm_route(r):
    """/api/links/... -> /api/links/{code}; /api/links, /healthz, /readyz, /metrics stay;
    any other single segment (incl. "/" + code) -> /{code}."""
    r = r.split("?", 1)[0]
    if r.startswith("/api/links/"):
        return "/api/links/{code}"
    if r.rstrip("/") == "/api/links":
        return "/api/links"
    if r in ("/healthz", "/readyz", "/metrics"):
        return r
    if r.count("/") == 1:
        return "/{code}"
    return r
RNG = random.SystemRandom()

# Stage maxima (COMMON.md). S1 is 25 = 11 auto (API + CON) + 14 manual.
STAGE_MAX = collections.OrderedDict(
    [("S0", 5), ("S1", 25), ("S2", 8), ("S3", 7), ("S4", 9), ("S5", 7), ("S6", 6), ("S7", 10), ("S8", 3)]
)
# Items of each stage that no automatic/assist check covers (awarded by hand).
MANUAL_ITEMS = [
    ("S0", 0, "QUALITY of the 'My decisions' answers: REPO-S0a (2) only checks that they are filled in"),
    ("S1", 3, "domain & validation: URL/code rules, reserved words, crypto/rand base62, sentinel errors + errors.Is, ONE error->status function"),
    ("S1", 4, "Store interface with memory (mutex) + redis implementations, selected by STORE"),
    ("S1", 3, "Redis correctness: HINCRBY/INCR (no GET+SET), atomic claim (HSETNX/SET NX/Lua), ZSET newest-first, delete removes hash + index"),
    ("S1", 1, "config from env with defaults, fail fast with a clear log line"),
    ("S1", 1, "/healthz never touches Redis; /readyz pings with timeout <= 2 s -> 503 when down"),
    ("S1", 1, "middleware: slog JSON request log (method, path, status, duration_ms) + panic recovery -> 500 JSON"),
    ("S1", 1, "graceful shutdown: SIGINT/SIGTERM, Server.Shutdown with timeout <= 10 s, close Redis client, log it"),
    ("S4", 1, "`docker build -t snaplink:v1 .` works and `docker run -e STORE=memory -p 8080:8080 snaplink:v1` -> /healthz 200"),
    ("S5", 1, "smoke.sh green against `docker compose up -d --build` from a clean clone"),
    ("S6", 0.5, "latest CI run on main is green (open the Actions tab)"),
    ("S6", 1, ">= 1 stage merged through a GitHub Pull Request that shows the CI check"),
    ("S8", 0, "README quality + AI-usage note: REPO-S8a (1) and REPO-S8b (1) are heuristics"),
    ("DEF", 20, "defense D1-D4 (5 each): request journey, a 'why' question, live debug, live change (NO AI)"),
]


# --------------------------------------------------------------------------- output


class Style:
    def __init__(self, enabled):
        self.enabled = enabled

    def _c(self, code, s):
        return "\033[%sm%s\033[0m" % (code, s) if self.enabled else s

    def green(self, s):
        return self._c("32", s)

    def red(self, s):
        return self._c("31", s)

    def yellow(self, s):
        return self._c("33", s)

    def cyan(self, s):
        return self._c("36", s)

    def gray(self, s):
        return self._c("90", s)

    def bold(self, s):
        return self._c("1", s)


def fmt_pts(x):
    return ("%.2f" % x).rstrip("0").rstrip(".") if x != int(x) else "%d" % x


class Check:
    """One row of the report."""

    def __init__(self, cid, section, title, max_pts, kind, stage=None):
        self.id = cid
        self.section = section
        self.title = title
        self.max = float(max_pts)
        self.kind = kind  # auto | assist | info
        self.stage = stage
        self.earned = 0.0
        self.reasons = []
        self.skipped = False
        self.info_ok = None  # for kind == info

    def score(self, earned, reasons=None):
        self.earned = round(max(0.0, min(self.max, earned)), 4)
        if reasons:
            self.reasons.extend(reasons)
        return self

    def all_or_nothing(self, problems, ok_reason=None):
        if problems:
            return self.score(0, problems)
        return self.score(self.max, [ok_reason] if ok_reason else None)

    def skip(self, reason):
        self.skipped = True
        self.earned = 0.0
        self.reasons.append(reason)
        return self

    @property
    def status(self):
        if self.skipped:
            return "SKIP"
        if self.kind == "info":
            return "INFO" if self.info_ok is None else ("OK" if self.info_ok else "WARN")
        if self.earned >= self.max - 1e-9:
            return "PASS"
        return "PARTIAL" if self.earned > 0 else "FAIL"

    def to_dict(self):
        return {
            "id": self.id,
            "section": self.section,
            "title": self.title,
            "kind": self.kind,
            "stage": self.stage,
            "earned": round(self.earned, 2),
            "max": self.max,
            "status": self.status,
            "reasons": self.reasons,
        }


class Report:
    def __init__(self, style):
        self.checks = []
        self.style = style
        self.notes = []
        self.warnings = []

    def add(self, cid, section, title, max_pts, kind="auto", stage=None):
        c = Check(cid, section, title, max_pts, kind, stage)
        self.checks.append(c)
        return c

    def find(self, cid):
        for c in self.checks:
            if c.id == cid:
                return c
        return None

    def print_row(self, c):
        st = self.style
        status = c.status
        label = status
        if c.kind == "assist" and status != "SKIP":
            label = "ASSIST " + {"PASS": "ok", "PARTIAL": "part", "FAIL": "no"}[status]
        color = {
            "PASS": st.green, "OK": st.green, "PARTIAL": st.yellow, "FAIL": st.red,
            "WARN": st.yellow, "SKIP": st.gray, "INFO": st.cyan,
        }[status]
        pts = "" if c.kind == "info" else "%5s/%-4s" % (fmt_pts(c.earned), fmt_pts(c.max))
        print("  %-10s %-58s %-10s %s" % (c.id, c.title[:58], pts, color(label)))
        show = c.reasons if (c.kind != "auto" or status != "PASS") else [r for r in c.reasons if r.startswith("note")]
        for r in show:
            print("  %-10s %s" % ("", st.gray("- " + r) if status in ("PASS", "OK") else "- " + r))


# --------------------------------------------------------------------------- HTTP


class Resp:
    def __init__(self, status, headers, body, error=None):
        self.status = status
        self.headers = headers
        self.body = body
        self.error = error
        self._json = None
        self._parsed = False

    @property
    def ctype(self):
        return self.headers.get("content-type", "")

    @property
    def json_ct(self):
        return self.ctype.lower().startswith("application/json")

    def json(self):
        if not self._parsed:
            self._parsed = True
            try:
                self._json = json.loads(self.body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._json = None
        return self._json

    def describe(self):
        if self.status == 0:
            return "no response (%s)" % self.error
        return str(self.status)

    def short_body(self, n=120):
        s = self.body.decode("utf-8", "replace").strip().replace("\n", " ")
        return (s[:n] + "...") if len(s) > n else (s or "<empty>")

    def is_error_json(self):
        j = self.json()
        return isinstance(j, dict) and isinstance(j.get("error"), str)


class Client:
    """Tiny HTTP client on http.client: one connection per request, and it can
    never follow a redirect (http.client does not implement redirects)."""

    def __init__(self, base_url):
        u = urllib.parse.urlsplit(base_url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError("--url must look like http://host:port")
        self.https = u.scheme == "https"
        self.host = u.hostname
        self.port = u.port or (443 if self.https else 80)
        self.prefix = u.path.rstrip("/")
        self.recorder = None
        self._lock = threading.Lock()

    def request(self, method, path, body=None, raw=None, timeout=TIMEOUT, barrier=None):
        data = None
        headers = {"User-Agent": "snaplink-grader/" + VERSION, "Accept": "application/json"}
        if raw is not None:
            data = raw.encode("utf-8")
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
        if data is not None:
            headers["Content-Type"] = "application/json"
        cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
        conn = cls(self.host, self.port, timeout=timeout)
        try:
            if barrier is not None:  # connect first, then fire all requests together
                conn.connect()
                barrier.wait(timeout=30)
            conn.request(method, self.prefix + path, body=data, headers=headers)
            r = conn.getresponse()
            payload = r.read()
            resp = Resp(r.status, {k.lower(): v for k, v in r.getheaders()}, payload)
        except (OSError, http.client.HTTPException, threading.BrokenBarrierError) as e:
            resp = Resp(0, {}, b"", "%s: %s" % (type(e).__name__, e))
        finally:
            conn.close()
        if self.recorder is not None:
            with self._lock:
                self.recorder.append((method, path, resp))
        return resp

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body=body, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)


def rand_str(n, alphabet=string.ascii_letters + string.digits):
    return "".join(RNG.choice(alphabet) for _ in range(n))


def ts_ns(s):
    """RFC 3339 timestamp -> integer nanoseconds since the epoch (or None)."""
    if not isinstance(s, str):
        return None
    m = RFC3339_RE.match(s)
    if not m:
        return None
    y, mo, d, h, mi, se = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7) or ""
    ns = int((frac[1:] + "000000000")[:9]) if frac else 0
    tz = m.group(8)
    offset = 0
    if tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        offset = sign * (int(tz[1:3]) * 3600 + int(tz[4:6]) * 60)
    try:
        secs = calendar.timegm((y, mo, d, h, mi, se, 0, 0, 0)) - offset
    except (ValueError, OverflowError):
        return None
    return secs * 10 ** 9 + ns


class Ctx:
    """State shared between the HTTP sections."""

    def __init__(self, run_id):
        self.run_id = run_id
        self.codes = set()  # every code this run created
        self.good_codes = set()  # codes created on purpose (make_link / API-03): BON-B1 raw-code check
        self.listed_codes = []  # codes that must still be in GET /api/links

    def url(self, name):
        return "https://example.com/snaplink-grader/%s/%s?ref=grader" % (self.run_id, name)


def make_link(cl, ctx, name, extra=None):
    """Create a link for a later check. Accepts any 2xx with a code so that a
    wrong status code is only punished once (in API-03)."""
    body = {"url": ctx.url(name)}
    if extra:
        body.update(extra)
    r = cl.post("/api/links", body)
    j = r.json()
    if 200 <= r.status < 300 and isinstance(j, dict) and isinstance(j.get("code"), str) and j["code"]:
        ctx.codes.add(j["code"])
        ctx.good_codes.add(j["code"])
        return j["code"], body["url"], None
    return None, body["url"], "prerequisite POST /api/links failed: status %s, body %s" % (r.describe(), r.short_body())


def cleanup_if_created(cl, ctx, r):
    """A request that should have been rejected created a link: remove it."""
    j = r.json()
    if 200 <= r.status < 300 and isinstance(j, dict) and isinstance(j.get("code"), str):
        ctx.codes.add(j["code"])
        cl.delete("/api/links/" + urllib.parse.quote(j["code"], safe=""))


# --------------------------------------------------------------------------- API suite


def run_api(cl, rep, ctx):
    rec = []
    cl.recorder = rec

    # API-01
    c = rep.add("API-01", "API", "GET /healthz -> 200 JSON status ok", 0.25)
    r = cl.get("/healthz")
    p = []
    if r.status != 200:
        p.append("status: expected 200, got %s" % r.describe())
    if not r.json_ct:
        p.append("Content-Type: expected application/json, got %r" % r.ctype)
    j = r.json()
    if not (isinstance(j, dict) and j.get("status") == "ok"):
        p.append('body: expected {"status":"ok"}, got %s' % r.short_body())
    c.all_or_nothing(p)

    # API-02
    c = rep.add("API-02", "API", "GET /readyz -> 200 JSON status ready", 0.25)
    r = cl.get("/readyz")
    p = []
    if r.status != 200:
        p.append("status: expected 200, got %s (is Redis up?)" % r.describe())
    if not r.json_ct:
        p.append("Content-Type: expected application/json, got %r" % r.ctype)
    j = r.json()
    if not (isinstance(j, dict) and j.get("status") == "ready"):
        p.append('body: expected {"status":"ready"}, got %s' % r.short_body())
    c.all_or_nothing(p)

    # API-03
    c = rep.add("API-03", "API", "POST /api/links valid -> 201 + correct Link", 1)
    u3 = ctx.url("api03")
    r = cl.post("/api/links", {"url": u3})
    j = r.json()
    code3 = None
    p = []
    if r.status != 201:
        p.append("status: expected 201, got %s" % r.describe())
    if not isinstance(j, dict):
        p.append("body is not a JSON object: %s" % r.short_body())
    else:
        code3 = j.get("code") if isinstance(j.get("code"), str) else None
        if code3:
            ctx.codes.add(code3)
            if 200 <= r.status < 300:
                ctx.good_codes.add(code3)
        if not (code3 and CODE_RE.match(code3)):
            p.append("code: expected 6 chars [A-Za-z0-9], got %r" % j.get("code"))
        if j.get("url") != u3:
            p.append("url: expected %r, got %r" % (u3, j.get("url")))
        su = j.get("short_url")
        if not (isinstance(su, str) and su.startswith("http") and code3 and su.endswith("/" + code3)):
            p.append("short_url: expected http...'/%s', got %r" % (code3, su))
        if not (type(j.get("clicks")) is int and j.get("clicks") == 0):
            p.append("clicks: expected integer 0, got %r" % (j.get("clicks"),))
        if ts_ns(j.get("created_at")) is None:
            p.append("created_at: expected RFC 3339, got %r" % (j.get("created_at"),))
    c.all_or_nothing(p)
    if code3 is None:
        code3, u3, _ = make_link(cl, ctx, "api03-fallback")
    if code3:
        ctx.listed_codes.append(code3)

    # API-04
    c = rep.add("API-04", "API", "invalid input -> 400 JSON error (7 cases)", 1)
    long_url = "https://example.com/" + "a" * (2049 - len("https://example.com/"))
    cases = [
        ('url ""', {"url": ""}, None),
        ('url "not a url"', {"url": "not a url"}, None),
        ('url "http://"', {"url": "http://"}, None),
        ('url "ftp://example.com"', {"url": "ftp://example.com"}, None),
        ('url "javascript:alert(1)"', {"url": "javascript:alert(1)"}, None),
        ("2049-char https URL", {"url": long_url}, None),
        ("invalid JSON body", None, '{"url": "https://example.com/x"'),
    ]
    ok = 0
    p = []
    for name, body, raw in cases:
        r = cl.post("/api/links", body, raw=raw)
        if r.status == 400 and r.is_error_json():
            ok += 1
        else:
            p.append("%s: expected 400 + {\"error\"}, got %s %s" % (name, r.describe(), r.short_body(60)))
            cleanup_if_created(cl, ctx, r)
    c.score(c.max * ok / len(cases), p)

    # API-05
    c = rep.add("API-05", "API", "custom code: 201 exact / 409 taken / 400 invalid", 1)
    custom = "g-" + rand_str(6, string.ascii_lowercase + string.digits) + "_x"
    earned = 0.0
    p = []
    r = cl.post("/api/links", {"url": ctx.url("api05"), "code": custom})
    j = r.json()
    if r.status == 201 and isinstance(j, dict) and j.get("code") == custom:
        earned += 0.4
    else:
        p.append("create %r: expected 201 with that code, got %s %s" % (custom, r.describe(), r.short_body(60)))
    if 200 <= r.status < 300:
        ctx.codes.add(custom)
        ctx.listed_codes.append(custom)
    r = cl.post("/api/links", {"url": ctx.url("api05-again"), "code": custom})
    if r.status == 409:
        earned += 0.3
    else:
        p.append("same code again: expected 409, got %s %s" % (r.describe(), r.short_body(60)))
    bad = ["ab", "bad code!", "healthz", "c" * 33]
    for b in bad:
        r = cl.post("/api/links", {"url": ctx.url("api05-bad"), "code": b})
        if r.status == 400:
            earned += 0.3 / len(bad)
        else:
            p.append("code %r: expected 400, got %s" % (b if len(b) < 20 else "c*33", r.describe()))
            cleanup_if_created(cl, ctx, r)
    c.score(earned, p)

    # API-06
    c = rep.add("API-06", "API", "GET /{code} -> 302 Location; unknown -> 404", 1)
    earned = 0.0
    p = []
    if code3:
        r = cl.get("/" + code3)
        loc = r.headers.get("location")
        if r.status == 302 and loc == u3:
            earned += 0.6
        else:
            p.append("GET /%s: expected 302 Location %s, got %s Location %r" % (code3, u3, r.describe(), loc))
    else:
        p.append("no link to redirect (POST /api/links failed)")
    unknown = rand_str(10)
    r = cl.get("/" + unknown)
    if r.status == 404 and r.is_error_json():
        earned += 0.4
    else:
        p.append("GET /%s (unknown): expected 404 JSON error, got %s %s" % (unknown, r.describe(), r.short_body(60)))
    c.score(earned, p)

    # API-07
    c = rep.add("API-07", "API", "2 redirects on a fresh link -> clicks == 2", 1)
    earned = 0.0
    p = []
    code7, _, err = make_link(cl, ctx, "api07")
    if code7:
        ctx.listed_codes.append(code7)
        sts = [cl.get("/" + code7).status for _ in range(2)]
        if sts != [302, 302]:
            p.append("redirect statuses: expected [302, 302], got %s" % sts)
        r = cl.get("/api/links/" + code7)
        j = r.json()
        clicks = j.get("clicks") if isinstance(j, dict) else None
        if r.status == 200 and type(clicks) is int and clicks == 2:
            earned += 0.7
        else:
            p.append("GET /api/links/%s: expected 200 clicks 2, got %s clicks %r" % (code7, r.describe(), clicks))
    else:
        p.append(err)
    unknown = rand_str(10)
    r = cl.get("/api/links/" + unknown)
    if r.status == 404:
        earned += 0.3
    else:
        p.append("GET /api/links/%s (unknown): expected 404, got %s" % (unknown, r.describe()))
    c.score(earned, p)

    # API-08
    c = rep.add("API-08", "API", "GET /api/links -> array, has our codes, newest first", 1)
    r = cl.get("/api/links")
    j = r.json()
    p = []
    if r.status != 200:
        p.append("status: expected 200, got %s" % r.describe())
    if not isinstance(j, list):
        p.append("body: expected a JSON array, got %s" % r.short_body(60))
    else:
        present = {e.get("code") for e in j if isinstance(e, dict)}
        missing = [x for x in ctx.listed_codes if x not in present]
        if missing:
            p.append("codes created by this run missing from the list: %s" % ", ".join(missing))
        prev = None
        for i, e in enumerate(j):
            t = ts_ns(e.get("created_at")) if isinstance(e, dict) else None
            if t is None:
                p.append("item %d: created_at missing or not RFC 3339" % i)
                break
            if prev is not None and t > prev:
                p.append("not newest first: item %d (%s) is newer than item %d" % (i, e.get("created_at"), i - 1))
                break
            prev = t
    c.all_or_nothing(p, "%d links listed" % len(j) if isinstance(j, list) else None)

    # API-09
    c = rep.add("API-09", "API", "DELETE -> 204, then 404 everywhere", 1)
    earned = 0.0
    p = []
    code9, _, err = make_link(cl, ctx, "api09")
    if code9:
        r = cl.delete("/api/links/" + code9)
        if r.status == 204:
            earned += 0.4
            if r.body.strip():
                p.append("note: 204 should have an empty body (got %s)" % r.short_body(40))
        else:
            p.append("DELETE: expected 204, got %s" % r.describe())
        r1, r2 = cl.get("/" + code9), cl.get("/api/links/" + code9)
        if r1.status == 404 and r2.status == 404:
            earned += 0.3
        else:
            p.append("after delete: GET /{code} -> %s, GET /api/links/{code} -> %s (both should be 404)" % (r1.describe(), r2.describe()))
        rl = cl.get("/api/links")
        jl = rl.json()
        absent = isinstance(jl, list) and code9 not in {e.get("code") for e in jl if isinstance(e, dict)}
        r3 = cl.delete("/api/links/" + code9)
        if absent and r3.status == 404:
            earned += 0.3
        else:
            p.append("after delete: absent from list=%s, second DELETE -> %s (want True / 404)" % (absent, r3.describe()))
    else:
        p.append(err)
    c.score(earned, p)

    # API-10
    cl.recorder = None
    c = rep.add("API-10", "API", "errors are JSON {error} + JSON Content-Type; no 5xx", 0.5)
    p = []
    ignored = 0
    for method, path, r in rec:
        shown = path if len(path) < 50 else path[:47] + "..."
        if r.status == 0:
            p.append("%s %s -> no response (crash?): %s" % (method, shown, r.error))
            continue
        if r.status >= 500:
            p.append("%s %s -> %d (5xx)" % (method, shown, r.status))
            continue
        if r.status == 204 or r.status < 200 or 300 <= r.status < 400:
            continue  # redirects and 204 carry no JSON; wrong redirect codes are API-06's business
        if r.body in MUX_DEFAULT_BODIES:
            ignored += 1
            continue
        if not r.json_ct:
            p.append("%s %s -> %d with Content-Type %r" % (method, shown, r.status, r.ctype))
        elif r.status >= 400 and not r.is_error_json():
            p.append('%s %s -> %d body is not {"error": "..."}: %s' % (method, shown, r.status, r.short_body(50)))
    if ignored:
        p.append("note: %d ServeMux default 404/405 responses ignored (route missing?)" % ignored)
    real = [x for x in p if not x.startswith("note:")]
    shown = p[:8] + (["... %d more" % (len(p) - 8)] if len(p) > 8 else [])
    c.score(0 if real else c.max, ["%d responses inspected" % len(rec)] + shown)


# --------------------------------------------------------------------------- concurrency


STATUS_NOTE = "note: status codes are graded in %s, not here"


def run_concurrency(cl, rep, ctx):
    # Storms test atomicity only. Any 3xx to the right URL counts as a redirect
    # and any 2xx / 4xx as create / reject, so a wrong status code (graded in
    # API-03/05/06) is not charged a second time here.
    c = rep.add("CON-1", "CON", "100 parallel redirects -> all redirect, clicks == 100", 1.5)
    code, url, err = make_link(cl, ctx, "con1")
    if not code:
        c.score(0, [err])
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as ex:
            futs = [ex.submit(cl.get, "/" + code, timeout=STORM_TIMEOUT) for _ in range(100)]
            resps = [f.result() for f in futs]
        statuses = collections.Counter(x.status for x in resps)
        good = sum(1 for x in resps if 300 <= x.status < 400 and x.headers.get("location") == url)
        r = cl.get("/api/links/" + code)
        j = r.json()
        clicks = j.get("clicks") if isinstance(j, dict) else None
        p = []
        if good != 100:
            p.append("expected 100 redirects (3xx, Location = original url), got %d; statuses %s" % (good, fmt_counter(statuses)))
        if clicks != 100:
            p.append("clicks after the storm: expected exactly 100, got %r (lost updates => non-atomic increment)" % (clicks,))
        if not p and statuses.get(302, 0) != 100:
            p.append("%s (%s)" % (STATUS_NOTE % "API-06", fmt_counter(statuses)))
        c.score(0 if [x for x in p if not x.startswith("note:")] else c.max, p)

    c = rep.add("CON-2", "CON", "20 parallel POST same code -> 1 created + 19 rejected", 1.5)
    code = "race-" + rand_str(8, string.ascii_lowercase + string.digits)
    barrier = threading.Barrier(20)
    body = {"url": ctx.url("con2"), "code": code}
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as ex:
        futs = [ex.submit(cl.post, "/api/links", body, timeout=STORM_TIMEOUT, barrier=barrier) for _ in range(20)]
        statuses = collections.Counter(f.result().status for f in futs)
    ctx.codes.add(code)
    wins = sum(n for st, n in statuses.items() if 200 <= st < 300)
    rejected = sum(n for st, n in statuses.items() if 400 <= st < 500)
    p = []
    if wins != 1 or rejected != 19:
        p.append("expected 1 x 2xx + 19 x 4xx, got %s%s" % (
            fmt_counter(statuses), " (%d winners => non-atomic code claim)" % wins if wins > 1 else ""))
    if any(st >= 500 for st in statuses):
        p.append("5xx responses during the storm")
    if not p and (statuses.get(201, 0) != 1 or statuses.get(409, 0) != 19):
        p.append("%s (%s)" % (STATUS_NOTE % "API-03/API-05", fmt_counter(statuses)))
    c.score(0 if [x for x in p if not x.startswith("note:")] else c.max, p)


def fmt_counter(cnt):
    return ", ".join("%d x %s" % (n, s if s else "no-response") for s, n in sorted(cnt.items()))


# --------------------------------------------------------------------------- bonus (auto)


def run_bonus_ttl(cl, rep, ctx):
    c = rep.add("BON-B4", "BONUS", "B4 expiring links (ttl_seconds)", 4)
    earned = 0.0
    p = []
    r = cl.post("/api/links", {"url": "https://example.com/ttl?run=" + ctx.run_id, "ttl_seconds": 2})
    j = r.json()
    code = j.get("code") if isinstance(j, dict) and isinstance(j.get("code"), str) else None
    if code:
        ctx.codes.add(code)
    has_exp = bool(code) and 200 <= r.status < 300 and ts_ns(j.get("expires_at")) is not None
    codes_note = []
    if has_exp:
        earned += 1
        if r.status != 201:
            codes_note.append("create %d" % r.status)
    else:
        p.append("ttl_seconds 2: expected 2xx with RFC 3339 expires_at, got %s %s" % (r.describe(), r.short_body(80)))
    # The expiry parts are only tested when a TTL link exists (expires_at present),
    # otherwise a service without B4 would collect the "302 right away" half point.
    if has_exp:
        r = cl.get("/" + code)
        if 300 <= r.status < 400:
            earned += 0.5
            if r.status != 302:
                codes_note.append("redirect %d" % r.status)
        else:
            p.append("immediate GET /{code}: expected a redirect (3xx), got %s" % r.describe())
        print("  ... BON-B4: waiting 3 s for the 2 s TTL to expire ...", flush=True)
        time.sleep(3)
        r1, r2 = cl.get("/" + code), cl.get("/api/links/" + code)
        rl = cl.get("/api/links")
        jl = rl.json()
        absent = isinstance(jl, list) and code not in {e.get("code") for e in jl if isinstance(e, dict)}
        if r1.status == 404 and r2.status == 404 and absent:
            earned += 1.5
        else:
            p.append("after 3 s: GET /{code} -> %s, GET /api/links/{code} -> %s, absent from list=%s (want 404/404/True)"
                     % (r1.describe(), r2.describe(), absent))
    else:
        p.append("expiry part (2 pts) not tested: the TTL link was not created correctly")
    bad = [("0", 0), ("-1", -1), ("1.5", 1.5), ('"10"', "10")]
    if not has_exp:
        # a service without B4 ignores the unknown field; it must not earn the
        # "invalid value -> 400" point by rejecting e.g. "10" for another reason
        p.append("invalid-value part not tested: ttl_seconds not supported")
    for name, v in (bad if has_exp else []):
        r = cl.post("/api/links", {"url": ctx.url("ttl-bad"), "ttl_seconds": v})
        if r.status == 400:
            earned += 1.0 / len(bad)
        else:
            p.append("ttl_seconds %s: expected 400, got %s" % (name, r.describe()))
            cleanup_if_created(cl, ctx, r)
    if codes_note:
        p.append("%s (%s)" % (STATUS_NOTE % "API-03/API-06", ", ".join(codes_note)))
    c.score(earned, p)


def parse_prom_labels(s):
    return dict(re.findall(r'(\w+)="((?:[^"\\]|\\.)*)"', s))


def run_bonus_metrics(cl, rep, ctx):
    c = rep.add("BON-B1", "BONUS", "B1 Prometheus /metrics", 4)
    r = cl.get("/metrics")
    text = r.body.decode("utf-8", "replace")
    earned = 0.0
    p = []
    if r.status == 200 and "# TYPE" in text:
        earned += 1
    else:
        c.score(0, ["GET /metrics: expected 200 Prometheus text with '# TYPE', got %s %s" % (r.describe(), r.short_body(60))])
        return
    # label values may contain "}" (e.g. path="/{code}"), so match quoted strings as a whole
    series = [parse_prom_labels(m) for m in
              re.findall(r'^http_requests_total\{((?:[^"}]|"(?:[^"\\]|\\.)*")*)\}', text, re.M)]
    if not series:
        p.append("no http_requests_total{...} series")
    else:
        has_labels = any({"method", "path", "status"} <= set(s) for s in series)
        paths = sorted({s.get("path", "") for s in series})
        # only codes the grader created on purpose, never reserved words: a wrongly
        # accepted custom code "healthz" must not look like a cardinality bomb
        ours = {x for x in ctx.good_codes if x and x.lower() not in RESERVED}
        raw = sorted({pa for pa in paths for code in ours if code in pa})
        patterned = any("{" in pa for pa in paths)
        if has_labels and patterned and not raw:
            earned += 1
            p.append("path labels: %s" % ", ".join(paths[:6]))
        else:
            if not has_labels:
                p.append("http_requests_total needs labels method, path, status (got %s)" % sorted(set().union(*series)))
            if raw:
                p.append("path label contains raw codes (cardinality bomb): %s" % ", ".join(raw[:3]))
            if not patterned:
                p.append("no path label looks like a route pattern such as /{code}: %s" % ", ".join(paths[:6]))
    if re.search(r"^http_request_duration_seconds_bucket\{", text, re.M):
        earned += 1
    else:
        p.append("http_request_duration_seconds_bucket missing")
    have = [m for m in ("snaplink_redirects_total", "snaplink_links_created_total") if re.search(r"^%s(\{| )" % m, text, re.M)]
    if len(have) == 2:
        earned += 1
    else:
        p.append("domain metrics missing: %s" % ", ".join(sorted({"snaplink_redirects_total", "snaplink_links_created_total"} - set(have))))
    c.score(earned, p)


# --------------------------------------------------------------------------- repo helpers


def run(cmd, cwd=None, timeout=60, env=None):
    """Run a command; returns (exit_code or None on timeout/missing, combined output)."""
    try:
        # stdin=DEVNULL: tools like kubectl must never sit waiting for a password prompt
        cp = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout, env=env)
        return cp.returncode, cp.stdout.decode("utf-8", "replace")
    except FileNotFoundError:
        return None, "%s: command not found" % cmd[0]
    except subprocess.TimeoutExpired as e:
        out = (e.output or b"").decode("utf-8", "replace")
        return None, "timed out after %ds\n%s" % (timeout, out)


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def first_line(s, n=160):
    for line in (s or "").splitlines():
        if line.strip():
            return line.strip()[:n]
    return ""


def last_lines(s, k=3):
    lines = [x for x in (s or "").splitlines() if x.strip()]
    return " | ".join(x.strip()[:120] for x in lines[-k:])


def walk_files(root, exts=None, skip_dirs=(".git", "vendor", "node_modules")):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in skip_dirs]
        for fn in fns:
            if exts is None or fn.endswith(exts):
                yield os.path.join(dp, fn)


def find_first(root, names):
    for n in names:
        p = os.path.join(root, n)
        if os.path.isfile(p):
            return p
    return None


def has_strict_mode(text):
    """True if ONE `set` line enables e, u and -o pipefail: `set -euo pipefail`,
    `set -Eeuo pipefail`, `set -eu -o pipefail`, `set -o errexit -o nounset -o pipefail`..."""
    for line in (text or "").splitlines():
        line = line.strip()
        if not re.match(r"^set\s", line):
            continue
        flags, pipefail = set(), False
        toks = line.split()[1:]
        i = 0
        while i < len(toks):
            t = toks[i]
            if t.startswith("#"):
                break
            if t.startswith("-") and not t.startswith("--"):
                letters = t[1:]
                if "o" in letters and i + 1 < len(toks):
                    opt = toks[i + 1]
                    pipefail |= opt == "pipefail"
                    flags |= {"e"} if opt == "errexit" else ({"u"} if opt == "nounset" else set())
                    i += 1
                flags |= set(letters.replace("o", ""))
            i += 1
        if {"e", "u"} <= flags and pipefail:
            return True
    return False


def yaml_children(text, parent):
    """Very small indentation-based YAML helper (no PyYAML): returns an
    ordered dict child-key -> block text for the mapping under top-level
    `parent:`."""
    lines = (text or "").splitlines()
    out = collections.OrderedDict()
    i = 0
    while i < len(lines) and not re.match(r"^%s:\s*(#.*)?$" % re.escape(parent), lines[i]):
        i += 1
    if i >= len(lines):
        return out
    i += 1
    child_indent = None
    current = None
    while i < len(lines):
        line = lines[i]
        if line.strip() and not line.startswith((" ", "\t")) and not line.lstrip().startswith("#"):
            break  # next top-level key
        if line.strip() and not line.lstrip().startswith("#"):
            ind = len(line) - len(line.lstrip())
            if child_indent is None:
                child_indent = ind
            m = re.match(r"^\s*([\w.\-\"']+)\s*:", line)
            if ind == child_indent and m:
                current = m.group(1).strip("\"'")
                out[current] = []
        if current is not None:
            out[current].append(line)
        i += 1
    return collections.OrderedDict((k, "\n".join(v)) for k, v in out.items())


def k8s_docs(paths):
    """Split YAML files into documents; returns list of (file, kind, name, text)."""
    docs = []
    for f in sorted(paths):
        text = read(f) or ""
        for part in re.split(r"^---\s*$", text, flags=re.M):
            m = re.search(r"^kind:\s*['\"]?(\w+)", part, re.M)
            if not m:
                continue
            meta = yaml_children(part, "metadata")
            name = ""
            if "name" in meta:
                name = meta["name"].split(":", 1)[1].split(" #")[0].strip().strip("'\"")
            docs.append((f, m.group(1), name, part))
    return docs


def probe_path(text, probe):
    """path of an httpGet probe, looking only inside the probe's own block."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)%s:\s*(#.*)?$" % probe, line)
        if not m:
            continue
        ind = len(m.group(1))
        for nxt in lines[i + 1:]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= ind:
                break
            pm = re.match(r"^\s*path:\s*['\"]?([^\s'\"#]+)", nxt)
            if pm:
                return pm.group(1)
        return "(non-http probe)"
    return None


# --------------------------------------------------------------------------- repo assist


class Repo:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.git_ok = os.path.isdir(os.path.join(self.path, ".git")) or run(
            ["git", "-C", self.path, "rev-parse", "--git-dir"], timeout=10)[0] == 0
        self.branch = None
        if self.git_ok:
            for b in ("main", "master"):
                if run(["git", "-C", self.path, "rev-parse", "--verify", "-q", b], timeout=10)[0] == 0:
                    self.branch = b
                    break
            self.branch = self.branch or "HEAD"

    def git(self, *args, timeout=30):
        return run(["git", "-c", "core.quotepath=off", "-C", self.path] + list(args), timeout=timeout)

    def p(self, *parts):
        return os.path.join(self.path, *parts)

    def mode(self, rel):
        code, out = self.git("ls-files", "-s", "--", rel)
        if code != 0 or not out.strip():
            return None
        return out.split()[0]

    def tracked(self, rel):
        code, out = self.git("ls-files", "--", rel)
        return code == 0 and bool(out.strip())


def assist(rep, cid, stage, title, max_pts):
    return rep.add(cid, "REPO", title, max_pts, kind="assist", stage=stage)


def run_repo(repo, rep, url, ctx):
    if not os.path.isdir(repo.path):
        c = assist(rep, "REPO", None, "repository path", 0)
        c.skip("not a directory: %s" % repo.path)
        return
    go_ok = shutil.which("go") is not None
    s0(repo, rep)
    s2(repo, rep, go_ok)
    s3(repo, rep, url)
    s4(repo, rep)
    s5(repo, rep)
    s6(repo, rep)
    s7_repo(repo, rep)
    s8(repo, rep)


PLACEHOLDER = "اینجا بنویس"
DECISION_KEYS = ["WHAT", "STRUCTURE", "DATA", "CONCURRENCY", "SECURITY", "OUT OF SCOPE", "RISKS", "AI PLAN"]
DECISIONS_HEADING = re.compile(r"(my\s+decisions|تصمیم[\u200c\s]*(ها|های)\s*(ی\s*)?من)", re.I)


def heading_level(line):
    m = re.match(r"^(#{1,6})\s+", line)
    return len(m.group(1)) if m else 0


def s0(repo, rep):
    # S0a decisions
    c = assist(rep, "REPO-S0a", "S0", "PLAN/DECISIONS 'My decisions': 8 answers filled", 2)
    cands = []
    for name in ("PLAN.md", "DECISIONS.md", "plan.md", "decisions.md", "docs/PLAN.md", "docs/DECISIONS.md"):
        t = read(repo.p(name))
        if t is not None:
            cands.append((name, t))
    found = None
    for name, t in cands:
        lines = t.splitlines()
        for i, line in enumerate(lines):
            if heading_level(line) and DECISIONS_HEADING.search(line):
                found = (name, lines, i)
                break
        if found:
            break
    if not found:
        c.score(0, ["no PLAN.md / DECISIONS.md with a 'My decisions' / 'تصمیم‌های من' heading (looked at: %s)"
                    % (", ".join(n for n, _ in cands) or "none found")])
    else:
        name, lines, start = found
        lvl = heading_level(lines[start])
        end = len(lines)
        for j in range(start + 1, len(lines)):
            hl = heading_level(lines[j])
            if hl and hl <= lvl:
                end = j
                break
        section = lines[start + 1:end]
        answers = collections.OrderedDict()
        cur = None
        for line in section:
            if heading_level(line):
                cur = None
                up = line.upper()
                for k in DECISION_KEYS:
                    if k not in answers and re.search(r"\b%s\b" % k.replace(" ", r"\s+"), up):
                        cur = k
                        answers[k] = []
                        break
            elif cur:
                answers[cur].append(line)
        # FILLED = after dropping the placeholder line(s), headings and "> " hint
        # lines, at least ~40 characters of real text remain.
        missing, empty, leftover = [], [], []
        for k in DECISION_KEYS:
            if k not in answers:
                missing.append(k)
                continue
            kept = [l for l in answers[k] if PLACEHOLDER not in l and not heading_level(l) and not l.lstrip().startswith(">")]
            real = re.sub(r"[\s_*`~\u270d\ufe0f]+", "", "\n".join(kept))
            if len(real) < 40:
                empty.append(k)
            elif any(PLACEHOLDER in l for l in answers[k]):
                leftover.append(k)
        good = len(DECISION_KEYS) - len(missing) - len(empty)
        why = ["%s: %d/8 filled (>= 40 chars of real text)" % (name, good)]
        if missing:
            why.append("sub-heading missing: " + ", ".join(missing))
        if empty:
            why.append("not filled (placeholder only or < 40 chars): " + ", ".join(empty))
        if leftover:
            why.append("note: placeholder line not deleted (answer counted): " + ", ".join(leftover))
        if repo.git_ok:
            code, out = repo.git("log", repo.branch, "--format=%at", "--reverse")
            code2, out2 = repo.git("log", repo.branch, "--diff-filter=A", "--format=%at", "--reverse", "--", name)
            if code == 0 and code2 == 0 and out.split() and out2.split():
                mins = (int(out2.split()[0]) - int(out.split()[0])) / 60.0
                why.append("first committed %.0f min after the first commit%s" % (mins, " (late? should be < 15)" if mins > 15 else ""))
        c.score(2.0 if good == 8 else (int(good / 8.0 * 2 * 4) / 4.0), why)

    # S0b go.mod + .gitignore
    c = assist(rep, "REPO-S0b", "S0", "go.mod + .gitignore (binaries, .env, coverage)", 1)
    gomod = read(repo.p("go.mod")) or ""
    gi = read(repo.p(".gitignore"))
    why = []
    mod = re.search(r"^module\s+(\S+)", gomod, re.M)
    gov = re.search(r"^go\s+(\S+)", gomod, re.M)
    why.append("go.mod: module %s, go %s" % (mod.group(1) if mod else "?", gov.group(1) if gov else "?") if gomod else "go.mod missing")
    pts = 0.0
    if mod:
        pts += 0.25
    if gi is None:
        why.append(".gitignore missing")
    else:
        lines = [x.strip() for x in gi.splitlines() if x.strip() and not x.strip().startswith("#")]
        env = any(re.match(r"^/?(\*\*/)?\.env(\*|\.\*)?$", x) for x in lines)
        cov = any(re.search(r"(\.out$|coverage|\.cov|\.prof)", x) for x in lines)
        binr = any(re.search(r"(^/?bin/?$|\.exe$|^/?snaplink$|^/?dist/?$|^/?build/?$|^\*\.test$|^/?tmp/?$)", x) for x in lines)
        pts += 0.25 * sum([env, cov, binr])
        why.append(".gitignore: .env %s, coverage %s, binaries %s" % tuple("yes" if v else "NO" for v in (env, cov, binr)))
    if repo.git_ok:
        code, out = repo.git("remote", "-v")
        why.append("remote: %s" % ("github.com" if "github.com" in out else (first_line(out) or "none (not pushed?)")))
    c.score(pts, why)

    # S0c merges
    c = assist(rep, "REPO-S0c", "S0", "stage branches merged into main: 0.5 per merge commit (max 4)", 2)
    if not repo.git_ok:
        c.score(0, ["not a git repository"])
        return
    code, out = repo.git("log", repo.branch, "--merges", "--first-parent", "--format=%s")
    subs = [x for x in out.splitlines() if x.strip()] if code == 0 else []
    n = len(subs)
    prs = len([x for x in subs if x.startswith("Merge pull request #")])
    why = ["%d merge commits on %s (first-parent): %d git merge --no-ff, %d GitHub 'Merge pull request #N'"
           % (n, repo.branch, n - prs, prs)]
    if subs:
        why.append("e.g. " + "; ".join(subs[:4]))
    if n == 0:
        why.append("squash/rebase merges leave no merge commit: check the GitHub PR list by eye")
    c.score(min(2.0, 0.5 * n), why)


def s2(repo, rep, go_ok):
    tests = list(walk_files(repo.path, (".go",)))
    tests = [f for f in tests if f.endswith("_test.go")]
    texts = {f: read(f) or "" for f in tests}
    rel = lambda f: os.path.relpath(f, repo.path)

    c = assist(rep, "REPO-S2a", "S2", "table-driven tests ([]struct + t.Run) with errors.Is", 3)
    td = [f for f, t in texts.items() if "[]struct" in t and "t.Run(" in t]
    eis = [f for f, t in texts.items() if "errors.Is(" in t]
    why = ["%d test files; table-driven: %s" % (len(tests), ", ".join(rel(f) for f in td[:4]) or "none")]
    why.append("errors.Is in tests: %s" % (", ".join(rel(f) for f in eis[:3]) or "none"))
    c.score(3 if td and eis else (2 if td else 0), why)

    c = assist(rep, "REPO-S2b", "S2", "concurrency test: >= 100 goroutines + sync.WaitGroup", 2)
    cc = [f for f, t in texts.items() if "sync.WaitGroup" in t and re.search(r"\bgo\s+func\b", t)]
    big = [f for f in cc if any(n >= 100 for n in goroutine_counts(texts[f]))]
    why = ["WaitGroup + go func in: %s" % (", ".join(rel(f) for f in cc[:3]) or "none")]
    if big:
        why.append("goroutine count >= 100 in: %s" % ", ".join(rel(f) for f in big[:3]))
    elif cc:
        why.append("no goroutine count >= 100 found (literal like n = 200 / loop bound i < 100): confirm by eye")
    c.score(2 if big else (1 if cc else 0), why)

    c = assist(rep, "REPO-S2c", "S2", "httptest tests: >= 3 method/route pairs + an error status", 2)
    ht = [f for f, t in texts.items() if "httptest." in t]
    blob = "\n".join(texts.values())  # pairs may live in helper/table files
    pairs = sorted({(norm_method(m), norm_route(r)) for m, r in PAIR_RE.findall(blob)})
    err = bool(ERR_STATUS_RE.search("\n".join(texts[f] for f in ht)))
    why = ["httptest in: %s" % (", ".join(rel(f) for f in ht[:3]) or "none"),
           "%d method/route pairs: %s" % (len(pairs), ", ".join("%s %s" % pr for pr in pairs[:8]) or "none"),
           "error status literal: %s" % ("yes" if err else "no")]
    c.score(2 if ht and len(pairs) >= 3 and err else (1 if ht else 0), why)

    c = assist(rep, "REPO-S2d", "S2", "`go test -race -count=1 ./...` passes (no DB)", 1)
    if not go_ok:
        c.skip("go not found on PATH")
    elif not os.path.isfile(repo.p("go.mod")):
        c.score(0, ["no go.mod at the repository root: nothing to test"])
    else:
        print("  ... running go test -race in the student repo (up to 240 s) ...", flush=True)
        env = {k: v for k, v in os.environ.items() if k not in NO_DB_ENV}
        code, out = run(["go", "test", "-race", "-count=1", "./..."], cwd=repo.path, timeout=240, env=env)
        race = True
        if code not in (0, None) and ("requires cgo" in out or "-race is not supported" in out):
            race = False
            code, out = run(["go", "test", "-count=1", "./..."], cwd=repo.path, timeout=240, env=env)
        why = [("passed" if code == 0 else "FAILED") + ("" if race else " (without -race: cgo/race unavailable on this machine)"),
               last_lines(out, 3)]
        why.append("env without %s; still make sure no Redis answers on localhost:6379" % ", ".join(NO_DB_ENV))
        c.score(1 if code == 0 else 0, why)

    c = rep.add("REPO-S2e", "REPO", "go vet ./... and gofmt -l . (also needed for CI)", 0, kind="info", stage="S2")
    if not go_ok:
        c.skip("go not found on PATH")
    else:
        vcode, vout = run(["go", "vet", "./..."], cwd=repo.path, timeout=240)
        fcode, fout = run(["gofmt", "-l", "."], cwd=repo.path, timeout=60)
        unformatted = [x for x in fout.splitlines() if x.strip() and not x.startswith("vendor/")] if fcode == 0 else []
        c.info_ok = vcode == 0 and fcode == 0 and not unformatted
        c.reasons.append("go vet: %s" % ("clean" if vcode == 0 else "FAILED: " + last_lines(vout, 2)))
        c.reasons.append("gofmt -l: %s" % ("clean" if not unformatted and fcode == 0 else ", ".join(unformatted[:5]) or first_line(fout)))


def script_basics(repo, rel):
    """(fraction 0..1 for shebang / strict mode / git mode 100755 / bash -n, reason)."""
    t = read(repo.p(rel))
    if t is None:
        return 0.0, "%s missing" % rel
    lines = t.splitlines()
    shebang = bool(lines) and lines[0].strip() == "#!/usr/bin/env bash"
    strict = has_strict_mode(t)
    mode = repo.mode(rel) if repo.git_ok else None
    code, out = run(["bash", "-n", repo.p(rel)], timeout=20)
    syntax = code == 0
    frac = 0.25 * sum([shebang, strict, mode == "100755", syntax])
    why = "%s: shebang %s, set -euo pipefail %s, git mode %s, bash -n %s" % (
        rel, "ok" if shebang else "NO (%r)" % (lines[0][:30] if lines else ""), "ok" if strict else "NO",
        mode or "untracked", "ok" if syntax else "FAILED " + first_line(out))
    return frac, why


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def smoke_lines(out):
    """(PASS/FAIL lines, FAIL lines, summary lines) of a smoke.sh run, ANSI colours removed."""
    lines = [ANSI_RE.sub("", x).strip() for x in (out or "").splitlines()]
    pf = [x for x in lines if re.match(r"^(PASS|FAIL)\b", x)]
    fails = [x for x in pf if x.startswith("FAIL")]
    summary = [x for x in lines if SUMMARY_RE.search(x)]
    return pf, fails, summary


def s3(repo, rep, url):
    ce = read(repo.p("scripts", "check-env.sh"))
    sm = read(repo.p("scripts", "smoke.sh"))

    c = assist(rep, "REPO-S3a", "S3", "both scripts: env bash shebang, strict mode, 100755, bash -n", 1)
    f1, w1 = script_basics(repo, "scripts/check-env.sh")
    f2, w2 = script_basics(repo, "scripts/smoke.sh")
    c.score(0.5 * f1 + 0.5 * f2, [w1, w2])

    c = assist(rep, "REPO-S3b", "S3", "check-env.sh: go git docker kubectl kind|minikube, ALL GOOD/MISSING", 1)
    if ce is None:
        c.score(0, ["scripts/check-env.sh missing"])
    else:
        tools = [t for t in ("go", "git", "docker", "kubectl") if re.search(r"\b%s\b" % t, ce)]
        kind = bool(re.search(r"\b(kind|minikube)\b", ce))
        marks = [m for m in ("ALL GOOD", "MISSING", "✓", "✗") if m in ce]
        pts = 0.5 * (len(tools) == 4 and kind) + 0.5 * ("ALL GOOD" in ce and "MISSING" in ce)
        c.score(pts, ["tools mentioned: %s; kind/minikube: %s" % (", ".join(tools) or "none", "yes" if kind else "NO"),
                      "markers: %s" % (", ".join(marks) or "none")])

    c = assist(rep, "REPO-S3c", "S3", "check-env.sh checks the Docker daemon (docker info)", 1)
    c.score(1 if ce and "docker info" in ce else 0, ["'docker info' %s" % ("found" if ce and "docker info" in ce else "not found")])

    # Positive run against --url (reused by S3d/e/g) and a negative run against a closed port.
    smoke_out, smoke_code = None, None
    neg_out, neg_code, neg_port = None, None, None
    if sm is not None:
        if url:
            print("  ... running scripts/smoke.sh %s (up to 120 s) ..." % url, flush=True)
            smoke_code, smoke_out = run(["bash", repo.p("scripts", "smoke.sh"), url], cwd=repo.path, timeout=120)
        neg_port = free_port()
        print("  ... running scripts/smoke.sh against closed port %d (must fail, up to 120 s) ..." % neg_port, flush=True)
        neg_code, neg_out = run(["bash", repo.p("scripts", "smoke.sh"), "http://127.0.0.1:%d" % neg_port],
                                cwd=repo.path, timeout=120)
    pf, fails, summary = smoke_lines(smoke_out)

    c = assist(rep, "REPO-S3d", "S3", "smoke.sh prints >= 6 PASS/FAIL checks against --url", 1)
    if sm is None:
        c.score(0, ["scripts/smoke.sh missing"])
    elif smoke_out is None:
        c.skip("no --url / server unreachable: smoke.sh not run")
    else:
        c.score(1 if len(pf) >= 6 else 0, ["%d PASS/FAIL lines when run against %s" % (len(pf), url)])

    c = assist(rep, "REPO-S3e", "S3", "smoke.sh format + exit code (incl. a closed-port run that must fail)", 1)
    if sm is None:
        c.score(0, ["scripts/smoke.sh missing"])
    else:
        why = []
        pos = 0.0
        if smoke_out is not None:
            pos = 0.25 * bool(pf) + 0.25 * bool(summary)
            consistent = (smoke_code == 0) == (not fails)
            why.append("run vs --url: %d PASS/FAIL lines, summary %s, exit %s%s" % (
                len(pf), repr(summary[-1]) if summary else "MISSING", smoke_code,
                "" if consistent else " (note: exit code does not match the FAIL lines)"))
        else:
            why.append("run vs --url: not possible (no --url / server unreachable)")
        npf, nfails, nsum = smoke_lines(neg_out)
        neg_ok = neg_code not in (0, None) and bool(nfails) and bool(nsum)
        why.append("closed port %d: exit %s, %d FAIL lines, summary %s => %s" % (
            neg_port, neg_code, len(nfails), repr(nsum[-1]) if nsum else "MISSING",
            "ok" if neg_ok else "NOT OK (must exit non-zero, print FAIL lines and 'N passed, M failed')"))
        c.score(pos + 0.5 * neg_ok, why)

    c = assist(rep, "REPO-S3f", "S3", "smoke.sh captures the code from the response (jq/sed/grep)", 1)
    if sm is None:
        c.score(0, ["scripts/smoke.sh missing"])
    else:
        tool = re.search(r"\b(jq|sed|grep|awk|python3?|cut)\b", sm)
        capture = re.search(r"\w+=\$\(.*(jq|sed|grep|awk|python|cut|field|json)", sm) or re.search(r"\bcode\b.*=\s*\$\(", sm)
        c.score(1 if tool and capture else (0.5 if tool else 0),
                ["parser: %s, captured into a variable: %s" % (tool.group(1) if tool else "none", "yes" if capture else "not obvious")])

    c = assist(rep, "REPO-S3g", "S3", "smoke.sh green against --url (confirm compose + k8s by eye)", 1)
    if sm is None:
        c.score(0, ["scripts/smoke.sh missing"])
    elif smoke_out is None:
        c.skip("no --url given / server unreachable")
    else:
        c.score(1 if smoke_code == 0 else 0, ["exit %s: %s" % (smoke_code, last_lines(smoke_out, 2))])


def dockerfile_lines(text):
    out, buf = [], ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        out.append(buf + line)
        buf = ""
    if buf:
        out.append(buf)
    return out


def s4(repo, rep):
    df = read(repo.p("Dockerfile"))
    lines = dockerfile_lines(df)
    froms = [i for i, l in enumerate(lines) if re.match(r"^FROM\s", l, re.I)]
    final = lines[froms[-1]:] if froms else []

    c = assist(rep, "REPO-S4a", "S4", "multi-stage build (golang builder -> small runtime)", 2)
    if df is None:
        c.score(0, ["Dockerfile missing"])
    else:
        bases = []
        for i in froms:  # skip flags such as --platform=$BUILDPLATFORM
            toks = [t for t in lines[i].split()[1:] if not t.startswith("--")]
            bases.append(toks[0] if toks else "?")
        builder = any(re.match(r"^([\w.\-]+(:\d+)?/)*golang(:|@|$)", b.lower()) for b in bases[:-1])
        last = bases[-1].lower() if bases else ""
        small = last == "scratch" or "distroless" in last or re.match(r"^([\w.\-]+/)*alpine(:|@|$)", last) is not None
        c.score(2 if len(froms) >= 2 and builder and small else 0,
                ["FROM: %s; golang builder stage: %s; final stage scratch/distroless/alpine: %s" % (
                    " -> ".join(bases), "yes" if builder else "NO", "yes" if small else "NO")])

    c = assist(rep, "REPO-S4c", "S4", "runs as non-root (USER in the final stage)", 1)
    users = [l.split(None, 1)[1].strip() for l in final if re.match(r"^USER\s", l, re.I)]
    nonroot = bool(users) and users[-1].split(":")[0] not in ("root", "0")
    c.score(1 if nonroot else 0, ["final-stage USER: %s" % (users[-1] if users else "none (root!)")])

    c = assist(rep, "REPO-S4d", "S4", ".dockerignore excludes .git and .env", 1)
    di = read(repo.p(".dockerignore"))
    if di is None:
        c.score(0, [".dockerignore missing"])
    else:
        ent = [x.strip().lstrip("/") for x in di.splitlines() if x.strip() and not x.strip().startswith("#")]
        g, e = any(x.rstrip("/") == ".git" for x in ent), any(x in (".env", ".env*", "*.env", "**/.env") for x in ent)
        c.score(0.5 * g + 0.5 * e, [".git %s, .env %s; %d entries" % ("yes" if g else "NO", "yes" if e else "NO", len(ent))])

    c = assist(rep, "REPO-S4e", "S4", "cache order: COPY go.mod go.sum -> go mod download -> COPY . .", 1)
    modcopy = next((i for i, l in enumerate(lines) if re.match(r"^COPY\s", l, re.I) and "go.mod" in l), None)
    allcopy = next((i for i, l in enumerate(lines) if re.match(r"^COPY\s+(--\S+\s+)*\.\s+\S+\s*$", l, re.I)), None)
    dl = next((i for i, l in enumerate(lines) if "go mod download" in l), None)
    ok = modcopy is not None and allcopy is not None and modcopy < allcopy
    c.score((0.75 if ok else 0) + (0.25 if ok and dl is not None and modcopy < dl < allcopy else 0),
            ["COPY go.mod at line %s, go mod download at %s, COPY . . at %s (instruction index)" % (modcopy, dl, allcopy)])

    c = assist(rep, "REPO-S4f", "S4", "static binary: CGO_ENABLED=0, -s -w, exec-form ENTRYPOINT, EXPOSE 8080", 1)
    blob = "\n".join(lines)
    cgo = "CGO_ENABLED=0" in blob.replace(" ", "")
    sw = bool(re.search(r"-s\s+-w|-w\s+-s", blob))
    ep = any(re.match(r"^(ENTRYPOINT|CMD)\s+\[", l, re.I) for l in final)
    ex = any(re.match(r"^EXPOSE\s+8080\b", l, re.I) for l in lines)
    c.score(0.25 * sum([cgo, sw, ep, ex]), ["CGO_ENABLED=0 %s, -s -w %s, exec-form ENTRYPOINT/CMD %s, EXPOSE 8080 %s"
                                            % tuple("yes" if v else "NO" for v in (cgo, sw, ep, ex))])


def compose_file(repo):
    return find_first(repo.path, ["compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml"])


def s5(repo, rep):
    f = compose_file(repo)
    text = read(f) if f else None
    services = yaml_children(text, "services") if text else {}
    redis_name = next((k for k, v in services.items() if re.search(r"image:\s*['\"]?redis", v)), None)
    if redis_name is None:
        redis_name = next((k for k in services if "redis" in k.lower()), None)
    app_name = next((k for k, v in services.items() if re.search(r"^\s+build\s*:", v, re.M)), None)
    rblk = services.get(redis_name, "")
    ablk = services.get(app_name, "")

    c = assist(rep, "REPO-S5a", "S5", "compose: app (build) + redis:7-alpine services", 1)
    if text is None:
        c.score(0, ["no compose.yaml / docker-compose.yml"])
    else:
        img = re.search(r"image:\s*['\"]?(redis[^\s'\"]*)", rblk)
        c.score(0.5 * bool(app_name) + 0.5 * bool(redis_name),
                ["%s: services %s; app=%s, redis=%s (%s)" % (os.path.basename(f), ", ".join(services), app_name, redis_name,
                                                             img.group(1) if img else "no image")])

    c = assist(rep, "REPO-S5b", "S5", "redis healthcheck (redis-cli ping) + condition: service_healthy", 2)
    hc = "healthcheck:" in rblk and "redis-cli" in rblk and "ping" in rblk
    dep = bool(re.search(r"condition:\s*service_healthy", ablk or text or ""))
    c.score(1 * hc + 1 * dep, ["redis healthcheck with redis-cli ping: %s; app depends_on condition: service_healthy: %s"
                               % ("yes" if hc else "NO", "yes" if dep else "NO")])

    c = assist(rep, "REPO-S5c", "S5", "named volume for Redis data", 1)
    vols = list(yaml_children(text, "volumes").keys()) if text else []
    used = [v for v in vols if re.search(r"-\s*['\"]?%s:" % re.escape(v), rblk) or re.search(r"source:\s*%s\b" % re.escape(v), rblk)]
    c.score(1 if used else (0.5 if vols else 0), ["top-level volumes: %s; mounted in redis: %s" % (", ".join(vols) or "none", ", ".join(used) or "no")])

    c = assist(rep, "REPO-S5d", "S5", ".env.example committed, .env NOT tracked", 1)
    ex = os.path.isfile(repo.p(".env.example"))
    ex_tracked = repo.tracked(".env.example") if repo.git_ok else ex
    env_tracked = repo.tracked(".env") if repo.git_ok else False
    c.score(0.5 * (ex and ex_tracked) + 0.5 * (not env_tracked and (ex or text is not None)),
            [".env.example %s; .env tracked in git: %s" % ("committed" if ex and ex_tracked else ("present, not committed" if ex else "missing"),
                                                         "YES (secret leak!)" if env_tracked else "no")])

    c = assist(rep, "REPO-S5e", "S5", "restart: unless-stopped on app; redis port NOT published", 1)
    rs = bool(re.search(r"restart:\s*['\"]?unless-stopped", ablk))
    pub = bool(re.search(r"^\s+ports\s*:", rblk, re.M))
    c.score(0.5 * rs + 0.5 * (bool(rblk) and not pub), ["app restart unless-stopped: %s; redis ports published: %s"
                                                       % ("yes" if rs else "NO", "YES" if pub else "no")])


def s6(repo, rep):
    wdir = repo.p(".github", "workflows")
    files = sorted(walk_files(wdir, (".yml", ".yaml"))) if os.path.isdir(wdir) else []
    blob = "\n".join(read(f) or "" for f in files)
    names = ", ".join(os.path.relpath(f, repo.path) for f in files) or "none"

    c = assist(rep, "REPO-S6a", "S6", "workflow triggers: push to main + pull_request", 1)
    push = bool(re.search(r"\bpush\b", blob))
    main = bool(re.search(r"\bmain\b", blob))
    pr = "pull_request" in blob
    c.score(0.5 * (push and main) + 0.5 * pr, ["%s: push %s (main %s), pull_request %s" % (names, push, main, pr)])

    c = assist(rep, "REPO-S6b", "S6", "test job: checkout, setup-go, gofmt, go vet, go test -race", 2)
    items = [("actions/checkout", "actions/checkout" in blob), ("actions/setup-go", "actions/setup-go" in blob),
             ("gofmt check that fails the build", gofmt_fails_build(blob)), ("go vet", "go vet" in blob),
             ("-race", "-race" in blob)]
    vf = "go-version-file" in blob
    c.score(0.4 * sum(v for _, v in items), ["%s; go-version-file: %s" % (", ".join("%s %s" % (k, "yes" if v else "NO") for k, v in items),
                                                                     "yes" if vf else "no")])

    c = assist(rep, "REPO-S6c", "S6", "build job: docker build with needs: test", 1)
    db = bool(re.search(r"docker\s+(buildx\s+)?build|docker/build-push-action", blob))
    nd = bool(re.search(r"^\s+needs:", blob, re.M))
    c.score(0.5 * db + 0.5 * nd, ["docker build %s, needs: %s" % ("yes" if db else "NO", "yes" if nd else "NO")])

    c = assist(rep, "REPO-S6d", "S6", "CI badge in README (green run on main: see MANUAL)", 0.5)
    readme = read(repo.p("README.md")) or ""
    badge = bool(re.search(r"(actions/workflows/[^)\s]+/badge\.svg|badge\.svg)", readme))
    c.score(0.5 if badge else 0, ["badge %s" % ("found" if badge else "not found")])


STEP_RE = re.compile(r"^\s*-\s+(name|uses|run|id|if|with|env)\s*:")
GOFMT_FAIL_RE = re.compile(r"exit\s+1|\btest\s+-z\b|\[\[?\s+-z\b|\|\|\s*exit|--exit-code|\bdiff\s|gofmt-action")


def gofmt_fails_build(text):
    """A workflow step that runs gofmt AND turns unformatted files into a red build
    (exit 1, test -z "$(gofmt -l .)", [ -z ... ], diff, --exit-code ...), not just the word."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "gofmt" not in line:
            continue
        start = i
        while start > 0 and not STEP_RE.match(lines[start]):
            start -= 1
        end = i + 1
        while end < len(lines) and not STEP_RE.match(lines[end]):
            end += 1
        if GOFMT_FAIL_RE.search("\n".join(lines[start:end])):
            return True
    return False


def find_k8s_files(repo):
    d = repo.p("k8s")
    if os.path.isdir(d):
        return sorted(walk_files(d, (".yaml", ".yml")))
    return []


def s7_repo(repo, rep):
    files = find_k8s_files(repo)
    docs = k8s_docs(files)
    relf = lambda f: os.path.relpath(f, repo.path)
    workloads = [d for d in docs if d[1] in ("Deployment", "StatefulSet")]
    redis = [d for d in workloads if re.search(r"image:\s*['\"]?[\w./-]*redis", d[3])]
    apps = [d for d in workloads if d not in redis]
    app = apps[0] if apps else None
    svcs = [d for d in docs if d[1] == "Service"]

    c = assist(rep, "REPO-S7a", "S7", "Namespace snaplink, applied first (file order)", 1)
    ns = [d for d in docs if d[1] == "Namespace"]
    if not files:
        c.score(0, ["no k8s/ folder with YAML files"])
    else:
        first_ok = bool(ns) and docs.index(ns[0]) == 0
        c.score(0.5 * bool(ns and ns[0][2] == "snaplink") + 0.5 * first_ok,
                ["files: %s" % ", ".join(relf(f) for f in files),
                 "Namespace: %s; first document applied: %s" % (ns[0][2] if ns else "none", "yes" if first_ok else "NO")])

    c = assist(rep, "REPO-S7b", "S7", "ConfigMap + Secret, consumed by the app (envFrom/secretKeyRef)", 2)
    cm = [d for d in docs if d[1] == "ConfigMap"]
    sec = [d for d in docs if d[1] == "Secret"]
    at = app[3] if app else ""
    cm_used = bool(re.search(r"configMap(Ref|KeyRef)", at))
    sec_used = bool(re.search(r"secret(KeyRef|Ref)", at))
    c.score(0.5 * bool(cm) + 0.5 * bool(sec) + 0.5 * cm_used + 0.5 * sec_used,
            ["ConfigMap: %s; Secret: %s; app uses configMapRef/KeyRef: %s, secretKeyRef/Ref: %s" % (
                ", ".join(d[2] for d in cm) or "none", ", ".join(d[2] for d in sec) or "none", cm_used, sec_used)])

    c = assist(rep, "REPO-S7c", "S7", "redis workload + ClusterIP Service + --requirepass from Secret", 2)
    rt = redis[0][3] if redis else ""
    rsvc = [d for d in svcs if "redis" in d[2].lower() or re.search(r"redis", yaml_children(d[3], "spec").get("selector", ""))]
    reqpass = "requirepass" in rt and bool(re.search(r"secret(KeyRef|Ref)", rt))
    c.score(0.75 * bool(redis) + 0.5 * bool(rsvc) + 0.75 * reqpass,
            ["redis %s: %s; Service: %s; requirepass from Secret: %s" % (
                redis[0][1] if redis else "workload", redis[0][2] if redis else "none",
                ", ".join(d[2] for d in rsvc) or "none", reqpass)])

    c = assist(rep, "REPO-S7d", "S7", "app Deployment: replicas 2, requests+limits, pinned tag, IfNotPresent", 2)
    if not app:
        c.score(0, ["no app Deployment (non-redis image) found"])
    else:
        rep_m = re.search(r"^\s+replicas:\s*(\d+)", at, re.M)
        img = re.search(r"image:\s*['\"]?([^\s'\"]+)", at)
        image = img.group(1) if img else ""
        tag = image.rsplit(":", 1)[1] if ":" in image.split("/")[-1] else ""
        res = "requests:" in at and "limits:" in at
        pol = bool(re.search(r"imagePullPolicy:\s*['\"]?IfNotPresent", at))
        pinned = bool(tag) and tag != "latest"
        reps = int(rep_m.group(1)) if rep_m else None
        c.score(0.5 * (reps == 2) + 0.5 * res + 0.5 * pinned + 0.5 * pol,
                ["%s: replicas %s, image %s, requests+limits %s, imagePullPolicy IfNotPresent %s" % (
                    app[2], reps, image or "?", res, pol)])

    c = assist(rep, "REPO-S7e", "S7", "livenessProbe /healthz + readinessProbe /readyz", 2)
    lp, rp = (probe_path(at, "livenessProbe"), probe_path(at, "readinessProbe")) if app else (None, None)
    c.score(1 * (lp == "/healthz") + 1 * (rp == "/readyz"), ["liveness path %s, readiness path %s" % (lp, rp)])

    c = assist(rep, "REPO-S7f", "S7", "app Service port 80 (port-forward smoke: confirm by eye)", 1)
    asvc = [d for d in svcs if d not in rsvc]
    p80 = [d for d in asvc if re.search(r"^\s+(-\s+)?port:\s*['\"]?80['\"]?\s*(#.*)?$", d[3], re.M)]
    c.score(1 if p80 else (0.5 if asvc else 0), ["app Service: %s; port 80: %s" % (", ".join(d[2] for d in asvc) or "none", "yes" if p80 else "no")])

    # Bonus info from the repo (points only when verified live, see MANUAL)
    ing = [d for d in docs if d[1] == "Ingress"]
    host = any("snaplink.local" in d[3] for d in ing)
    chart = None
    cd = repo.p("charts")
    if os.path.isdir(cd):
        for n in sorted(os.listdir(cd)):
            if os.path.isfile(os.path.join(cd, n, "Chart.yaml")):
                chart = n
                break
    rep.repo_bonus = {"ingress": host, "chart": chart}
    c = rep.add("REPO-B2", "REPO", "(info) Ingress for snaplink.local in k8s/", 0, kind="info", stage="B2")
    c.info_ok = host
    c.reasons.append("Ingress objects: %s; host snaplink.local: %s" % (", ".join(d[2] for d in ing) or "none", host))
    c = rep.add("REPO-B3", "REPO", "(info) Helm chart in charts/", 0, kind="info", stage="B3")
    if chart:
        vals = read(os.path.join(cd, chart, "values.yaml")) or ""
        tdir = os.path.join(cd, chart, "templates")
        tdocs = k8s_docs(list(walk_files(tdir, (".yaml", ".yml", ".tpl")))) if os.path.isdir(tdir) else []
        kinds = sorted({d[1] for d in tdocs})
        need = [k for k in ("Deployment", "Service", "ConfigMap", "Secret") if k not in kinds]
        vk = [k for k in ("tag:", "replicaCount:", "resources:") if k in vals]
        c.info_ok = not need and len(vk) == 3
        c.reasons.append("charts/%s: values has %s; templates kinds %s%s" % (
            chart, ", ".join(v.rstrip(":") for v in vk), ", ".join(kinds), ("; missing " + ", ".join(need)) if need else ""))
    else:
        c.info_ok = False
        c.reasons.append("no charts/<name>/Chart.yaml")


SECRET_RE = re.compile(r"""(?i)\b\w*(password|passwd|secret|token|apikey|api_key)\w*\b\s*(:=|=|:)\s*"([^"\s]{4,})\"""")


def s8(repo, rep):
    readme = read(repo.p("README.md"))
    c = assist(rep, "REPO-S8a", "S8", "README: run local/compose/k8s, env table, diagram", 1)
    if readme is None:
        c.score(0, ["README.md missing"])
    else:
        local = bool(re.search(r"go run|STORE=memory", readme))
        comp = bool(re.search(r"docker[ -]compose", readme))
        k8s = bool(re.search(r"kubectl|kind |minikube", readme))
        table = bool(re.search(r"^\|.*(PORT|STORE|REDIS_ADDR).*\|", readme, re.M))
        blocks = re.findall(r"```([^\n]*)\n(.*?)```", readme, re.S)
        diag = any(lang.strip() == "mermaid" or re.search(r"[─│┌└▶►]|-->|->|\+--|<-", body)
                   for lang, body in blocks if lang.strip() not in ("bash", "sh", "json", "go", "yaml", "console"))
        c.score((0.5 if (local and comp and k8s) else 0.5 * sum([local, comp, k8s]) / 3.0) + 0.25 * table + 0.25 * diag,
                ["run: local %s, compose %s, k8s %s; env table %s; diagram %s" % tuple("yes" if v else "NO" for v in (local, comp, k8s, table, diag))])

    c = assist(rep, "REPO-S8b", "S8", "'AI usage' section incl. something the AI got wrong", 1)
    if readme is None:
        c.score(0, ["README.md missing"])
    else:
        lines = readme.splitlines()
        start = next((i for i, l in enumerate(lines) if heading_level(l) and (re.search(r"\bAI\b", l, re.I) or "هوش مصنوعی" in l)), None)
        if start is None:
            c.score(0, ["no heading containing 'AI' or 'هوش مصنوعی'"])
        else:
            lvl = heading_level(lines[start])
            end = next((j for j in range(start + 1, len(lines)) if heading_level(lines[j]) and heading_level(lines[j]) <= lvl), len(lines))
            body = "\n".join(lines[start + 1:end])
            words = len(re.findall(r"\w+", body))
            wrong = bool(re.search(r"(wrong|mistake|bug|incorrect|fixed|broke|caught|اشتباه|غلط|خطا|باگ|اصلاح|درست\s*کرد)", body, re.I))
            c.score((0.5 if words >= 20 else 0.25) + (0.5 if wrong else 0),
                    ["section %r: %d words; mentions a mistake that was fixed: %s" % (lines[start].strip()[:50], words, "yes" if wrong else "NO")])

    c = assist(rep, "REPO-S8c", "S8", "history: >= 10 commits, conventional, spread; no secrets/binaries", 1)
    if not repo.git_ok:
        c.score(0, ["not a git repository"])
        return
    code, out = repo.git("log", repo.branch, "--no-merges", "--format=%at%x09%s")
    rows = [x.split("\t", 1) for x in out.splitlines() if "\t" in x] if code == 0 else []
    n = len(rows)
    conv = [s for _, s in rows if re.match(r"^(feat|fix|test|tests|build|ci|docs|chore|refactor|perf|style|revert|deploy)(\([^)]*\))?!?:\s", s)]
    ratio = len(conv) / float(n) if n else 0.0
    times = [int(t) for t, _ in rows]
    span = (max(times) - min(times)) / 60.0 if times else 0.0
    pts = (1 / 3.0) * (n >= 10) + (1 / 3.0) * (ratio >= 0.7) + (1 / 3.0) * (span >= 90)
    why = ["%d non-merge commits, %.0f%% conventional, first->last %.0f min" % (n, ratio * 100, span)]
    # secrets in Go code (tests excluded: fixtures are not secrets)
    hits = []
    for f in walk_files(repo.path, (".go",)):
        if f.endswith("_test.go"):
            continue
        for i, line in enumerate((read(f) or "").splitlines(), 1):
            m = SECRET_RE.search(line)
            if m or re.search(r"redis://[^:\"\s]*:[^@\"\s]+@", line):
                hits.append("%s:%d" % (os.path.relpath(f, repo.path), i))
    # binaries / big files tracked
    bins = []
    code, out = repo.git("ls-files", "-z")
    for rel in (out.split("\0") if code == 0 else []):
        if not rel:
            continue
        fp = repo.p(rel)
        try:
            size = os.path.getsize(fp)
            with open(fp, "rb") as fh:
                magic = fh.read(4)
        except OSError:
            continue
        if size > 5 * 1024 * 1024 or magic in (b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe") or magic[:2] == b"MZ":
            bins.append(rel)
    if hits:
        why.append("possible hard-coded secret in Go code: %s" % ", ".join(hits[:4]))
    if bins:
        why.append("binary / large files committed: %s" % ", ".join(bins[:4]))
    if hits or bins:
        pts = min(pts, 0.5)
    else:
        why.append("no obvious secrets in *.go, no binaries tracked")
    c.score(pts, why)


# --------------------------------------------------------------------------- live k8s / image


def run_k8s(ns, rep, skip_bonus=False):
    rows = [("K8S-NS", "namespace exists, objects inside", 1),
            ("K8S-CFG", "ConfigMap + Secret exist and are consumed by the app", 2),
            ("K8S-REDIS", "redis ready + Service + --requirepass", 2),
            ("K8S-APP", "app: readyReplicas >= 2, requests+limits, pinned tag, IfNotPresent", 2),
            ("K8S-PROBES", "app livenessProbe /healthz + readinessProbe /readyz", 2),
            ("K8S-SVC", "app Service exposes port 80", 1)]
    checks = {cid: rep.add(cid, "K8S", t, m, kind="assist", stage="S7") for cid, t, m in rows}
    store = rep.add("K8S-STORE", "K8S", "app STORE setting (memory => storms prove nothing)", 0, kind="info")
    b2 = rep.add("BON-B2", "K8S", "B2 Ingress host snaplink.local -> app Service (live)", 3, kind="assist", stage="B2")
    b3 = rep.add("BON-B3", "K8S", "B3 Helm release snaplink* deployed (helm list -A)", 4, kind="assist", stage="B3")
    if not skip_bonus:
        helm_check(b3)

    def skip_all(why):
        for c in list(checks.values()) + [store, b2]:
            c.skip(why)

    if shutil.which("kubectl") is None:
        skip_all("kubectl not found on PATH")
        return
    code, out = run(["kubectl", "--request-timeout=15s", "get", "namespace", ns, "-o", "json"], timeout=30)
    if code != 0:
        skip_all("kubectl get namespace %s failed: %s" % (ns, first_line(out)))
        return
    code, out = run(["kubectl", "--request-timeout=15s", "-n", ns, "get", "deploy,statefulset,svc,cm,secret,ingress", "-o", "json"], timeout=40)
    try:
        items = json.loads(out).get("items", []) if code == 0 else None
    except ValueError:
        items = None
    if items is None:
        skip_all("kubectl get failed: %s" % first_line(out))
        return

    def containers(o):
        return (((o.get("spec") or {}).get("template") or {}).get("spec") or {}).get("containers") or []

    def name(o):
        return (o.get("metadata") or {}).get("name", "?")

    wl = [o for o in items if o.get("kind") in ("Deployment", "StatefulSet")]
    redis = [o for o in wl if any("redis" in (c.get("image") or "") for c in containers(o))]
    apps = [o for o in wl if o not in redis]
    app = apps[0] if apps else None
    svcs = [o for o in items if o.get("kind") == "Service"]
    cms = [o for o in items if o.get("kind") == "ConfigMap" and name(o) != "kube-root-ca.crt"]
    secs = [o for o in items if o.get("kind") == "Secret" and o.get("type") in ("Opaque", None)]

    checks["K8S-NS"].score(1 if items else 0.5, ["%d objects in namespace %s" % (len(items), ns)])

    ac = containers(app)[0] if app and containers(app) else {}
    blob = json.dumps(ac)
    cm_used = "configMapRef" in blob or "configMapKeyRef" in blob
    sec_used = "secretKeyRef" in blob or "secretRef" in blob
    checks["K8S-CFG"].score(0.5 * bool(cms) + 0.5 * bool(secs) + 0.5 * cm_used + 0.5 * sec_used,
                            ["ConfigMaps %s; Secrets %s; app consumes cm %s, secret %s" % (
                                [name(o) for o in cms], [name(o) for o in secs], cm_used, sec_used)])

    r = redis[0] if redis else None
    rready = bool(r) and ((r.get("status") or {}).get("readyReplicas") or 0) >= 1
    rsvc = [o for o in svcs if "redis" in name(o) or "redis" in json.dumps((o.get("spec") or {}).get("selector") or {})]
    rblob = json.dumps(containers(r)) if r else ""
    reqpass = "requirepass" in rblob
    checks["K8S-REDIS"].score(1 * rready + 0.5 * bool(rsvc) + 0.5 * reqpass,
                              ["redis %s ready %s; Service %s; requirepass %s" % (name(r) if r else "none", rready,
                                                                                  [name(o) for o in rsvc], reqpass)])

    if not app:
        checks["K8S-APP"].score(0, ["no app Deployment (non-redis image)"])
        checks["K8S-PROBES"].score(0, ["no app Deployment"])
    else:
        ready = (app.get("status") or {}).get("readyReplicas") or 0
        res = ac.get("resources") or {}
        image = ac.get("image", "")
        tag = image.rsplit(":", 1)[1] if ":" in image.split("/")[-1] else ""
        pol = ac.get("imagePullPolicy")
        checks["K8S-APP"].score(0.5 * (ready >= 2) + 0.5 * bool(res.get("requests") and res.get("limits"))
                                + 0.5 * (bool(tag) and tag != "latest") + 0.5 * (pol == "IfNotPresent"),
                                ["%s: readyReplicas %s/%s, resources %s, image %s, pullPolicy %s" % (
                                    name(app), ready, (app.get("spec") or {}).get("replicas"), res or "none", image, pol)])
        lp = ((ac.get("livenessProbe") or {}).get("httpGet") or {}).get("path")
        rp = ((ac.get("readinessProbe") or {}).get("httpGet") or {}).get("path")
        checks["K8S-PROBES"].score(1 * (lp == "/healthz") + 1 * (rp == "/readyz"), ["liveness %s, readiness %s" % (lp, rp)])

    asvc = [o for o in svcs if o not in rsvc]
    p80 = [o for o in asvc if any(p.get("port") == 80 for p in (o.get("spec") or {}).get("ports") or [])]
    checks["K8S-SVC"].score(1 if p80 else (0.5 if asvc else 0), ["app Services %s; port 80: %s" % ([name(o) for o in asvc], bool(p80))])

    # B2: the object alone is worth 1/3; the remaining 2 need a curl through the controller (MANUAL)
    ings = [o for o in items if o.get("kind") == "Ingress"]
    app_svcs = {name(o) for o in asvc}
    hit, hosts = [], []
    for o in ings:
        for rl in (o.get("spec") or {}).get("rules") or []:
            hosts.append(rl.get("host"))
            backends = [((pa.get("backend") or {}).get("service") or {}).get("name")
                        for pa in ((rl.get("http") or {}).get("paths") or [])]
            if rl.get("host") == "snaplink.local" and any(b in app_svcs for b in backends):
                hit.append(name(o))
    if hit:
        b2.score(1, ["Ingress %s: host snaplink.local -> app Service %s" % (hit, sorted(app_svcs)),
                     "the other 2 pts need the curl through the controller (see MANUAL)"])
    else:
        b2.score(0, ["no Ingress with host snaplink.local pointing to an app Service (hosts: %s, app Services: %s)"
                     % (hosts, sorted(app_svcs))])

    # STORE actually used by the app: env (wins) or envFrom ConfigMaps
    if not app:
        store.skip("no app Deployment")
    else:
        cm_data = {name(o): (o.get("data") or {}) for o in cms}
        value, source = None, None
        for ef in ac.get("envFrom") or []:
            ref = (ef.get("configMapRef") or {}).get("name")
            if ref and "STORE" in cm_data.get(ref, {}):
                value, source = cm_data[ref]["STORE"], "envFrom ConfigMap %s" % ref
        for ev in ac.get("env") or []:
            if ev.get("name") != "STORE":
                continue
            if "value" in ev:
                value, source = ev["value"], "env value"
            else:
                ref = ((ev.get("valueFrom") or {}).get("configMapKeyRef") or {})
                value = cm_data.get(ref.get("name"), {}).get(ref.get("key"))
                source = "configMapKeyRef %s/%s" % (ref.get("name"), ref.get("key"))
        shown = value if value else "not set (default redis)"
        if (value or "").strip().lower() == "memory":
            store.info_ok = False
            rep.warnings.append("K8S-STORE: app runs with STORE=memory - CON-1/CON-2/BON-B4 must be set to 0: app is not using Redis")
            store.reasons.append("STORE=%s (%s): CON-1/CON-2/BON-B4 must be set to 0: app is not using Redis" % (shown, source))
        else:
            store.info_ok = True
            store.reasons.append("STORE=%s%s" % (shown, " (%s)" % source if source else ""))


def helm_check(b3):
    """B3 live: any namespace (students install the chart into e.g. snaplink-helm)."""
    if shutil.which("helm") is None:
        b3.skip("helm not found on PATH")
        return
    code, out = run(["helm", "list", "-A", "-o", "json"], timeout=30)
    try:
        rels = json.loads(out) if code == 0 else None
    except ValueError:
        rels = None
    if rels is None:
        b3.skip("helm list -A failed: %s" % first_line(out))
        return
    ok = [x for x in rels if str(x.get("chart", "")).startswith("snaplink") and x.get("status") == "deployed"]
    listed = ", ".join("%s (chart %s, ns %s, %s)" % (x.get("name"), x.get("chart"), x.get("namespace"), x.get("status"))
                       for x in rels) or "none"
    b3.score(4 if ok else 0, ["deployed snaplink* release in namespace %s" % ", ".join(sorted({str(x.get("namespace")) for x in ok}))
                              if ok else "no deployed release whose chart starts with 'snaplink'", "releases: %s" % listed])


def run_image(image, rep):
    c = rep.add("IMG-1", "IMG", "docker image %s size <= 30 MB" % image, 2, kind="assist", stage="S4")
    if shutil.which("docker") is None:
        c.skip("docker not found on PATH")
        return
    code, out = run(["docker", "image", "inspect", image, "--format", "{{.Size}}"], timeout=30)
    if code != 0:
        if re.search(r"(?i)no such (image|object)", out):
            c.score(0, ["image not found locally: %s (build it first)" % first_line(out)])
        elif re.search(r"(?i)cannot connect|failed to connect|is the docker daemon running|connection refused|permission denied", out):
            c.skip("docker daemon not reachable: %s" % first_line(out))
        else:
            c.skip("docker image inspect failed: %s" % first_line(out))
        return
    try:
        size = int(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        c.skip("unexpected docker output: %s" % first_line(out))
        return
    mb = size / 1e6
    c.score(2 if size <= 30 * 1000 * 1000 else 0, ["%.1f MB (limit 30 MB)" % mb])


# --------------------------------------------------------------------------- summary


def summarize(rep, args, reachable, started):
    st = rep.style
    sect = lambda s: [c for c in rep.checks if c.section == s]
    api = sum(c.earned for c in sect("API"))
    con = sum(c.earned for c in sect("CON"))
    bon = [c for c in sect("BONUS")]
    bon_e = sum(c.earned for c in bon)
    bon_m = sum(c.max for c in bon)

    # Suggested (assist) per stage. S7 = max(repo-based, live-based).
    per = collections.OrderedDict()
    for c in rep.checks:
        if c.kind != "assist" or c.stage not in STAGE_MAX:
            continue
        key = (c.stage, "live" if c.section == "K8S" else "repo")
        e, m = per.get(key, (0.0, 0.0))
        per[key] = (e + c.earned, m + (0 if c.skipped else c.max))
    stages = collections.OrderedDict()
    for (stage, src), (e, m) in per.items():
        if stage in stages and stages[stage][0] >= e:
            continue
        stages[stage] = (e, m, src)

    print()
    print(st.bold("SUMMARY"))
    core = api + con
    print("  AUTO (certain):     API %s/8  CON %s/3  => core %s/11%s" % (
        fmt_pts(round(api, 2)), fmt_pts(round(con, 2)), fmt_pts(round(core, 2)),
        "" if not bon else "  |  bonus %s => %s/%s" % ("  ".join("%s %s/%s" % (c.id.replace("BON-", ""), fmt_pts(round(c.earned, 2)), fmt_pts(c.max)) for c in bon),
                                                     fmt_pts(round(bon_e, 2)), fmt_pts(bon_m))))
    sug_e = sum(v[0] for v in stages.values())
    sug_m = sum(v[1] for v in stages.values())
    if stages:
        print("  SUGGESTED (assist): %s  => %s/%s" % ("  ".join("%s %s/%s" % (s, fmt_pts(round(v[0], 2)), fmt_pts(v[1])) for s, v in stages.items()),
                                                    fmt_pts(round(sug_e, 2)), fmt_pts(sug_m)))
    else:
        print("  SUGGESTED (assist): none (use --repo / --namespace / --image)")
    b23 = [c for c in rep.checks if c.id in ("BON-B2", "BON-B3") and not c.skipped]
    if b23:
        print("  SUGGESTED bonus:    %s" % "  ".join("%s %s/%s" % (c.id.replace("BON-", ""), fmt_pts(c.earned), fmt_pts(c.max)) for c in b23))
    total_known = core + sug_e
    print("  AUTO core + SUGGESTED = %s of 80 build points before the manual items below" % fmt_pts(round(total_known, 2)))

    # pts == 0 marks "confirm an assist suggestion" (shown as 'confirm', not added again)
    manual = []
    for stage, pts, text in MANUAL_ITEMS:
        if pts == 0 and not any(c.stage == stage and c.section == "REPO" for c in rep.checks):
            continue  # nothing to confirm without --repo
        manual.append((stage, pts, text))
    # assist stages that could not be checked at all
    for s, mx in STAGE_MAX.items():
        if s in ("S1",):
            continue
        covered = stages.get(s, (0, 0, ""))[1]
        man = sum(p for st_, p, _ in MANUAL_ITEMS if st_ == s)
        rest = mx - covered - man
        if rest > 1e-9:
            manual.append((s, rest, "not checked automatically in this run (no --repo/--namespace/--image or skipped)"))
    if not args.skip_bonus:
        verified = {c.id for c in b23 if c.earned > 0}
        rb = getattr(rep, "repo_bonus", {}) or {}
        curl = ("curl through the ingress controller: kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller 8081:80 & "
                "curl -H 'Host: snaplink.local' localhost:8081/healthz -> 200")
        if "BON-B2" in verified:
            manual.append(("B2", 2, "B2 " + curl))
        else:
            manual.append(("B2", 3, "B2 Ingress object (1)%s + %s (2)" % (" - repo has one" if rb.get("ingress") else "", curl)))
        if "BON-B3" not in verified:
            manual.append(("B3", 4, "`helm install` works%s" % (" (repo has charts/%s)" % rb["chart"] if rb.get("chart") else "")))
    print("  MANUAL (award by hand, max points):")
    for s, p, t in manual:
        print("    %-4s %5s  %s" % (s, fmt_pts(p) if p else "confirm", t))
    man_total = sum(p for _, p, _ in manual if p)
    print("  -> manual items worth up to %s more points ('confirm' rows are already inside SUGGESTED)" % fmt_pts(round(man_total, 2)))
    for w in rep.warnings:
        print(st.red("  WARNING: " + w))
    if not reachable:
        print(st.red("  SERVER UNREACHABLE at %s: API/CON/bonus checks not run (exit code 2)" % args.url))
    print()
    print(st.gray("How to read this report: AUTO rows are black-box facts against the running service - award them as is."))
    print(st.gray("ASSIST rows are heuristics on files, git, kubectl or docker - they SUGGEST points; confirm by eye, they can be fooled."))
    print(st.gray("MANUAL items need a human (code reading, GitHub UI, defense). Every non-PASS row lists why: tell the student."))
    print(st.gray("Run took %.1f s; run id %s (all test links contain it in their URL)." % (time.time() - started, args.run_id)))
    return {
        "auto": {"api": round(api, 2), "con": round(con, 2), "core": round(core, 2), "core_max": 11,
                 "bonus": round(bon_e, 2), "bonus_max": bon_m},
        "suggested": {s: {"earned": round(v[0], 2), "max": v[1], "source": v[2]} for s, v in stages.items()},
        "suggested_total": round(sug_e, 2),
        "suggested_max": sug_m,
        "suggested_bonus": {c.id: c.earned for c in b23},
        "manual": [{"stage": s, "max": p, "item": t} for s, p, t in manual],
        "warnings": rep.warnings,
    }


# --------------------------------------------------------------------------- main


HELP_EPILOG = """
examples:
  grade_snaplink.py --url http://localhost:8080
  grade_snaplink.py --url http://localhost:8080 --repo ~/submissions/ali/snaplink --json ali.json
  grade_snaplink.py --url http://localhost:8080 --namespace snaplink --image snaplink:v1

sections:
  API-01..API-10  API contract, 8 pts (AUTO). API-04/API-05 give proportional credit per case;
                  API-10 also checks Content-Type of every JSON response of the suite and fails on any 5xx.
  CON-1, CON-2    concurrency storms against the real datastore, 3 pts (AUTO, all-or-nothing). They test
                  atomicity only: any 3xx (to the right URL) is a redirect, any 2xx/4xx a create/reject;
                  wrong status codes are graded once, in API-03/05/06, and only noted here (same for B4).
  BON-B1, BON-B4  metrics and expiring links, +4 each (AUTO; skip with --skip-bonus). B4 waits 3 s.
  REPO-*          --repo assist checks per stage (SUGGESTED points; confirm by eye).
                  WARNING: --repo RUNS student code: go test, go vet and scripts/smoke.sh <url>.
  K8S-*, BON-B2/3 --namespace live checks with kubectl; B2 object = 1 of 3 (curl via the controller is MANUAL);
                  B3 = `helm list -A` has a deployed release whose chart starts with "snaplink" (any namespace).
  IMG-1           --image: docker image inspect size <= 30 MB.

Run the grader from OUTSIDE the student repo, against the service using its REAL datastore:
  python3 /path/to/graders/grade_snaplink.py --url http://localhost:8080 --repo /path/to/student-repo
CON-1/CON-2/BON-B4 only mean something when the app runs with STORE=redis (compose or kind);
with --namespace, K8S-STORE warns when the cluster app runs STORE=memory.

The grader never follows redirects, uses fresh random codes/URLs on every run (it works against a
Redis that already holds data) and leaves its test links in the store (URLs contain the run id).
Exit code: 0, or 2 when the service at --url is unreachable.
"""


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="grade_snaplink.py",
        description="Auto-grader for the SnapLink exam (version B): black-box API + concurrency checks "
                    "of a running service, plus optional repo / kubectl / docker assist checks.",
        epilog=HELP_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8080", help="base URL of the running service (default %(default)s)")
    ap.add_argument("--repo", metavar="PATH", help="student repository for assist checks (runs go test and smoke.sh!)")
    ap.add_argument("--namespace", metavar="NS", help="Kubernetes namespace for live kubectl checks (e.g. snaplink)")
    ap.add_argument("--image", metavar="NAME:TAG", help="local Docker image to measure (e.g. snaplink:v1)")
    ap.add_argument("--json", metavar="FILE", help="also write a machine-readable report")
    ap.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    ap.add_argument("--skip-bonus", action="store_true", help="skip bonus checks (B1, B4 and live B2/B3)")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass

    started = time.time()
    args.run_id = rand_str(8, string.ascii_lowercase + string.digits)
    style = Style(not args.no_color and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None)
    rep = Report(style)
    try:
        cl = Client(args.url.rstrip("/"))
    except ValueError as e:
        ap.error(str(e))
    ctx = Ctx(args.run_id)

    print(style.bold("SnapLink grader %s" % VERSION) + "  url=%s  run=%s" % (args.url, args.run_id))
    socket.setdefaulttimeout(TIMEOUT)
    probe = cl.get("/healthz")
    for _ in range(3):  # a just-started server may need a moment
        if probe.status != 0:
            break
        time.sleep(1)
        probe = cl.get("/healthz")
    reachable = probe.status != 0
    if reachable:
        print(style.bold("\n[1] API contract (8)"))
        run_api(cl, rep, ctx)
        for c in rep.checks:
            if c.section == "API":
                rep.print_row(c)
        print(style.bold("\n[2] Concurrency (3)"))
        run_concurrency(cl, rep, ctx)
        for c in rep.checks:
            if c.section == "CON":
                rep.print_row(c)
        if not args.skip_bonus:
            print(style.bold("\n[3] Bonus, automatic (B4 +4, B1 +4)"))
            run_bonus_ttl(cl, rep, ctx)
            run_bonus_metrics(cl, rep, ctx)  # last: sees the traffic of every section
            for c in rep.checks:
                if c.section == "BONUS":
                    rep.print_row(c)
    else:
        print(style.red("\nService unreachable at %s: %s" % (args.url, probe.error)))
        for cid, sec, title, mx in [("API", "API", "API contract", 8), ("CON", "CON", "concurrency", 3)]:
            rep.add(cid, sec, title, mx).score(0, ["server unreachable"])

    if args.repo:
        print(style.bold("\n[4] Repository assist checks (SUGGESTED - confirm by eye): %s" % os.path.abspath(args.repo)))
        repo = Repo(args.repo)
        n0 = len(rep.checks)
        run_repo(repo, rep, args.url if reachable else None, ctx)
        for c in rep.checks[n0:]:
            rep.print_row(c)
    if args.namespace:
        print(style.bold("\n[5] Live Kubernetes checks, namespace %s (SUGGESTED)" % args.namespace))
        n0 = len(rep.checks)
        run_k8s(args.namespace, rep, skip_bonus=args.skip_bonus)
        for c in rep.checks[n0:]:
            if args.skip_bonus and c.id in ("BON-B2", "BON-B3"):
                continue
            rep.print_row(c)
        if args.skip_bonus:
            rep.checks = [c for c in rep.checks if c.id not in ("BON-B2", "BON-B3")]
    if args.image:
        print(style.bold("\n[6] Docker image"))
        n0 = len(rep.checks)
        run_image(args.image, rep)
        for c in rep.checks[n0:]:
            rep.print_row(c)

    totals = summarize(rep, args, reachable, started)
    if args.json:
        doc = {
            "grader": "snaplink", "version": VERSION, "run_id": args.run_id,
            "url": args.url, "repo": args.repo, "namespace": args.namespace, "image": args.image,
            "reachable": reachable, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
            "duration_s": round(time.time() - started, 1),
            "checks": [c.to_dict() for c in rep.checks], "totals": totals,
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
        print("JSON report written to %s" % args.json)
    return 0 if reachable else 2


if __name__ == "__main__":
    sys.exit(main())
