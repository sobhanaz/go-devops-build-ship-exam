#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
grade_minibank.py - auto-grader for the "Build & Ship" exam, Version A: MiniBank.

Talks to a RUNNING MiniBank over HTTP and grades the API contract (8 pts) and
the concurrency storms (3 pts) with certainty, plus the automatic bonus checks
B1 (metrics, +4) and B4 (deadlock-safe transfers, +4). Optional assist checks
look at the student's repository (--repo), a live Kubernetes namespace
(--namespace) and the built image (--image) and SUGGEST points that the
instructor confirms by eye.

Python 3.9+ standard library only. Single file. Safe to run repeatedly
against a database that already contains data (random owner names, no id
assumptions).
"""

import argparse
import concurrent.futures
import datetime
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
import urllib.error
import urllib.request

GRADER_VERSION = "1.0.0"
TIMEOUT = 5.0  # seconds, every normal request
STORM_TIMEOUT = 30.0  # seconds, requests inside concurrency storms
STORM_WORKERS = 50
RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
MAX_AMOUNT = 1000000000

HELP_EPILOG = """\
examples:
  # API + concurrency + bonus B1/B4 only
  python3 grade_minibank.py --url http://localhost:8080

  # everything: repo assists, live Kubernetes checks, image size, JSON report.
  # Run the grader from OUTSIDE the student repo and point --repo at the clone:
  python3 /path/to/graders/grade_minibank.py --url http://localhost:8080 \\
      --repo /path/to/student-repo --namespace minibank --image minibank:v1 --json sara.json

what is graded:
  AUTO     API-01..API-10 (8 pts) and CON-1, CON-2 (3 pts): certain, from HTTP only.
           BON-B1 (/metrics, +4) and BON-B4 (bidirectional transfer storm, +4).
  ASSIST   --repo: REPO-S0, S2..S8 static checks; also RUNS `go vet`, `gofmt -l`,
           `go test -race ./...` (DB env vars removed), scripts/check-env.sh and
           scripts/smoke.sh <url>.  Only use --repo on code you are willing to execute.
  LIVE     --namespace: `kubectl get ... -o json` (replicas, probes, resources, image
           tag, postgres, K8S-STORE, ingress object = B2 1/3) and `helm list -A` (B3, any
           namespace, e.g. minibank-helm).
  IMAGE    --image: `docker image inspect` size <= 30 MB.
  MANUAL   everything a human must judge is listed with its max points at the end.

Grade against the REAL datastore: the server behind --url must run with STORE=postgres
(compose or the kind deployment). With STORE=memory the storms prove nothing about
PostgreSQL; with --namespace the K8S-STORE row warns when the deployment uses memory.
Exit code: 0 (always, whatever the score) or 2 if the server is unreachable.
"""


# ----------------------------------------------------------------------------
# output helpers
# ----------------------------------------------------------------------------

class Style:
    def __init__(self, enabled):
        self.enabled = enabled

    def _c(self, code, text):
        return "\033[%sm%s\033[0m" % (code, text) if self.enabled else text

    def green(self, t):
        return self._c("32", t)

    def red(self, t):
        return self._c("31", t)

    def yellow(self, t):
        return self._c("33", t)

    def cyan(self, t):
        return self._c("36", t)

    def blue(self, t):
        return self._c("34", t)

    def grey(self, t):
        return self._c("90", t)

    def bold(self, t):
        return self._c("1", t)


def fmt_pts(x):
    return ("%.2f" % x).rstrip("0").rstrip(".") if x != int(x) else str(int(x))


def round_q(x, q=0.05):
    """round to a multiple of q, avoiding float noise."""
    return round(round(x / q) * q, 4)


# ----------------------------------------------------------------------------
# result model
# ----------------------------------------------------------------------------

class Check:
    """One line of the report."""

    def __init__(self, cid, section, title, max_pts, kind="AUTO", stage=None):
        self.cid = cid
        self.section = section
        self.title = title
        self.max = float(max_pts)
        self.kind = kind  # AUTO | ASSIST | LIVE | IMAGE | INFO
        self.stage = stage  # S0..S8, B1..B4 (for summaries)
        self.earned = 0.0
        self.status = "FAIL"
        self.notes = []
        self.parts = []  # (label, earned, max, ok, reason)
        self.items = {}  # S7 item -> earned (for merging static and live)

    def part(self, label, pts, ok, reason=""):
        """add a sub-check worth pts; ok may be a float 0..1 for proportional credit."""
        if isinstance(ok, (int, float)) and not isinstance(ok, bool):
            frac = max(0.0, min(1.0, float(ok)))
        else:
            frac = 1.0 if ok else 0.0
        earned = pts * frac
        self.parts.append((label, earned, pts, frac, reason))
        self.earned += earned
        if frac < 1.0:
            line = "%s: %s" % (label, reason) if reason else label
            if pts:
                line += "  [%s/%s]" % (fmt_pts(round_q(earned, 0.01)), fmt_pts(pts))
            self.notes.append(line)
        return frac == 1.0

    def note(self, text):
        self.notes.append(text)

    def finish(self, status=None):
        self.earned = round_q(min(self.earned, self.max), 0.01)
        if status:
            self.status = status
        elif self.kind in ("ASSIST", "LIVE", "IMAGE"):
            self.status = "ASSIST"
        elif self.kind == "INFO":
            self.status = "INFO"
        elif self.earned >= self.max - 1e-9:
            self.status = "PASS"
        elif self.earned > 0:
            self.status = "PARTIAL"
        else:
            self.status = "FAIL"
        return self

    def to_json(self):
        return {
            "id": self.cid, "section": self.section, "kind": self.kind, "stage": self.stage,
            "title": self.title, "earned": self.earned, "max": self.max, "status": self.status,
            "notes": self.notes,
            "parts": [{"label": l, "earned": round_q(e, 0.01), "max": m, "ok": f >= 1.0, "reason": r}
                      for (l, e, m, f, r) in self.parts],
        }


class Report:
    def __init__(self):
        self.checks = []

    def add(self, check):
        self.checks.append(check)
        return check

    def by_section(self, section):
        return [c for c in self.checks if c.section == section]

    def get(self, cid):
        for c in self.checks:
            if c.cid == cid:
                return c
        return None


# ----------------------------------------------------------------------------
# HTTP client (stdlib only, never follows redirects, no proxies)
# ----------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NOBODY = object()


class Resp:
    def __init__(self, method, path, status, headers, body, error=None):
        self.method = method
        self.path = path
        self.status = status
        self.headers = headers
        self.body = body or b""
        self.error = error
        self.ctype = (headers.get("Content-Type", "") if headers is not None else "") or ""
        self.json = None
        self.json_ok = False
        if self.body:
            try:
                self.json = json.loads(self.body.decode("utf-8"))
                self.json_ok = True
            except Exception:
                pass

    @property
    def is_json_ct(self):
        return self.ctype.lower().startswith("application/json")

    @property
    def has_error_key(self):
        return isinstance(self.json, dict) and isinstance(self.json.get("error"), str)

    def short(self, n=90):
        text = self.body.decode("utf-8", "replace").strip().replace("\n", " ")
        return text if len(text) <= n else text[: n - 3] + "..."

    def describe(self):
        if self.status is None:
            return "no response (%s)" % self.error
        return "%s %s %s" % (self.status, self.ctype or "<no Content-Type>", self.short() or "<empty body>")


class Client:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
        self.records = []
        self.recording = False
        self._lock = threading.Lock()

    def call(self, method, path, body=_NOBODY, raw=None, timeout=TIMEOUT):
        headers = {"Accept": "application/json"}
        data = None
        if raw is not None:
            data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif body is not _NOBODY:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                r = Resp(method, path, resp.status, resp.headers, resp.read())
        except urllib.error.HTTPError as e:
            try:
                payload = e.read()
            except Exception:
                payload = b""
            r = Resp(method, path, e.code, e.headers, payload)
        except Exception as e:  # refused, timeout, reset, bad status line...
            reason = getattr(e, "reason", None) or e
            r = Resp(method, path, None, None, b"", error="%s: %s" % (type(e).__name__, reason))
        if self.recording:
            with self._lock:
                self.records.append(r)
        return r


def storm(client, jobs):
    """run [(method, path, body)] in parallel with 50 workers; returns [Resp]."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=STORM_WORKERS) as pool:
        futures = [pool.submit(client.call, m, p, b, None, STORM_TIMEOUT) for (m, p, b) in jobs]
        return [f.result() for f in futures]


def status_counts(resps):
    counts = {}
    for r in resps:
        key = r.status if r.status is not None else "no-response"
        counts[key] = counts.get(key, 0) + 1
    return ", ".join("%s×%d" % (k, v) for k, v in sorted(counts.items(), key=lambda kv: str(kv[0])))


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_2xx(r):
    return r.status is not None and 200 <= r.status < 300


MUX_DEFAULT_BODIES = (b"404 page not found\n", b"Method Not Allowed\n")


def is_mux_default(r):
    """net/http ServeMux's own plain-text 404/405 bodies (not written by the app's handlers)."""
    return r.status in (404, 405) and r.body in MUX_DEFAULT_BODIES


def app_404(r):
    """a 404 written by the app (unknown account), not ServeMux's 404 for a missing route."""
    return r.status == 404 and not is_mux_default(r)


# ----------------------------------------------------------------------------
# API contract (8 pts) — ids API-01..API-10 (= A1..A10 of the contract)
# ----------------------------------------------------------------------------

class Ctx:
    """state shared by the HTTP suites."""

    def __init__(self, client, run_id):
        self.c = client
        self.run_id = run_id
        self.seq = 0
        self._unknown = None
        self.created = []

    def owner(self, label):
        self.seq += 1
        return "G-%s-%s%d" % (self.run_id, label, self.seq)

    def new_account(self, label):
        """helper account for later checks. Tolerant on purpose: a wrong create status
        (e.g. 200 instead of 201) only costs API-03/API-04, not every check after it."""
        r = self.c.call("POST", "/accounts", {"owner": self.owner(label)})
        if r.status in (200, 201) and isinstance(r.json, dict) and is_int(r.json.get("id")):
            self.created.append(r.json["id"])
            return r.json["id"], r
        return None, r

    def balance(self, acc_id):
        r = self.c.call("GET", "/accounts/%s" % acc_id)
        if r.status == 200 and isinstance(r.json, dict) and is_int(r.json.get("balance")):
            return r.json["balance"]
        return None

    def unknown_id(self):
        """an id that surely does not exist (never assume ids start at 1)."""
        if self._unknown is None:
            ids = list(self.created)
            r = self.c.call("GET", "/accounts")
            if isinstance(r.json, list):
                ids += [a.get("id") for a in r.json if isinstance(a, dict) and is_int(a.get("id"))]
            self._unknown = max([999999999999] + [i + 1000000 for i in ids])
        return self._unknown


def run_api_suite(ctx, rep):
    c = ctx.c
    c.recording = True
    sec = "API contract"

    # API-01 healthz
    chk = rep.add(Check("API-01", sec, "GET /healthz -> 200 JSON {\"status\":\"ok\"}", 0.25))
    r = c.call("GET", "/healthz")
    ok = r.status == 200 and r.is_json_ct and isinstance(r.json, dict) and r.json.get("status") == "ok"
    chk.part("healthz", 0.25, ok, "expected 200 application/json {\"status\":\"ok\"}, got %s" % r.describe())
    chk.finish()

    # API-02 readyz
    chk = rep.add(Check("API-02", sec, "GET /readyz -> 200 JSON {\"status\":\"ready\"}", 0.25))
    r = c.call("GET", "/readyz")
    ok = r.status == 200 and r.is_json_ct and isinstance(r.json, dict) and r.json.get("status") == "ready"
    chk.part("readyz", 0.25, ok, "expected 200 application/json {\"status\":\"ready\"}, got %s" % r.describe())
    chk.finish()

    # API-03 create account (trim, shape)
    chk = rep.add(Check("API-03", sec, "POST /accounts (trimmed owner) -> 201 Account", 1.0))
    owner = "Grader-%s" % ctx.run_id
    r = c.call("POST", "/accounts", {"owner": "  %s  " % owner})
    acc_a = r.json if isinstance(r.json, dict) else {}
    problems = []
    if r.status != 201:
        problems.append("status %s (want 201)" % r.status)
    if not is_int(acc_a.get("id")) or acc_a.get("id", 0) <= 0:
        problems.append("id %r is not a positive integer" % acc_a.get("id"))
    if acc_a.get("owner") != owner:
        problems.append("owner %r (want trimmed %r)" % (acc_a.get("owner"), owner))
    if not (is_int(acc_a.get("balance")) and acc_a.get("balance") == 0):
        problems.append("balance %r (want integer 0)" % acc_a.get("balance"))
    if not (isinstance(acc_a.get("created_at"), str) and RFC3339.match(acc_a["created_at"])):
        problems.append("created_at %r is not RFC 3339" % acc_a.get("created_at"))
    chk.part("create", 1.0, not problems, "; ".join(problems) + " — response: " + r.describe() if problems else "")
    chk.finish()
    id_a = acc_a.get("id") if is_int(acc_a.get("id")) else None
    if id_a:
        ctx.created.append(id_a)

    # API-04 owner validation (proportional over 7 cases). "سارا" alone cannot tell rune
    # from byte counting (8 bytes is inside 2..40), so two discriminating cases are added:
    # 1 rune / 2 bytes must be rejected, 25 runes / 50 bytes must be accepted.
    chk = rep.add(Check("API-04", sec, "owner validation, rune counting (proportional, 7 cases)", 1.0))
    cases = [
        ("owner \"a\" -> 400", {"owner": "a"}, None, 400),
        ("41-rune owner -> 400", {"owner": "x" * 41}, None, 400),
        ("whitespace-only owner -> 400", {"owner": "   \t   "}, None, 400),
        ("invalid JSON -> 400", None, b'{"owner": "Sara"', 400),
        ("owner \"\u0633\u0627\u0631\u0627\" (4 runes / 8 bytes) -> 201", {"owner": "\u0633\u0627\u0631\u0627"}, None, 201),
        ("owner \"\u0633\" (1 rune / 2 bytes) -> 400", {"owner": "\u0633"}, None, 400),
        ("owner 25 x \"\u0628\" (25 runes / 50 bytes) -> 201", {"owner": "\u0628" * 25}, None, 201),
    ]
    id_sara = None
    byte_hint = False
    for label, body, raw, want in cases:
        r = c.call("POST", "/accounts", body if raw is None else _NOBODY, raw=raw)
        if isinstance(r.json, dict) and is_int(r.json.get("id")):
            ctx.created.append(r.json["id"])
            if body and body.get("owner") == "\u0633\u0627\u0631\u0627":
                id_sara = r.json["id"]
        if want == 400:
            ok = r.status == 400 and r.has_error_key
            reason = "expected 400 with JSON {\"error\":...}, got %s" % r.describe()
        else:
            ok = r.status == 201 and isinstance(r.json, dict) and r.json.get("owner") == body["owner"]
            reason = "expected 201 with the same owner, got %s" % r.describe()
        if not ok and body and body.get("owner") in ("\u0633", "\u0628" * 25):
            # 1-rune accepted or 25-rune (50-byte) rejected: the classic len() bug
            if (want == 400 and r.status in (200, 201)) or (want == 201 and r.status == 400):
                byte_hint = True
        chk.part(label, 1.0 / 7, ok, reason)
    if byte_hint:
        chk.note("looks like the owner length is counted in BYTES (len) instead of runes (utf8.RuneCountInString)")
    chk.finish()

    # API-05 list / get / 404 / 400
    chk = rep.add(Check("API-05", sec, "GET /accounts, /accounts/{id}, unknown -> 404, abc -> 400", 1.0))
    r = c.call("GET", "/accounts")
    want_ids = [i for i in (id_a, id_sara) if i]
    if r.status == 200 and isinstance(r.json, list):
        ids = [a.get("id") for a in r.json if isinstance(a, dict)]
        sorted_ok = all(is_int(i) for i in ids) and all(ids[k] < ids[k + 1] for k in range(len(ids) - 1))
        missing = [i for i in want_ids if i not in ids]
        reason = []
        if not sorted_ok:
            reason.append("ids are not strictly ascending")
        if missing:
            reason.append("new ids %s missing from the list" % missing)
        if not want_ids:
            reason.append("no account was created earlier, cannot verify")
        chk.part("GET /accounts sorted, contains new ids", 0.25, not reason, "; ".join(reason))
    else:
        chk.part("GET /accounts sorted, contains new ids", 0.25, False, "expected 200 JSON array, got %s" % r.describe())
    if id_a:
        r = c.call("GET", "/accounts/%d" % id_a)
        same = (r.status == 200 and isinstance(r.json, dict) and r.json.get("id") == id_a
                and r.json.get("owner") == acc_a.get("owner") and r.json.get("balance") == acc_a.get("balance")
                and same_instant(r.json.get("created_at"), acc_a.get("created_at")))
        chk.part("GET /accounts/{id} same data", 0.25, same, "expected 200 with the created account, got %s" % r.describe())
    else:
        chk.part("GET /accounts/{id} same data", 0.25, False, "no account from API-03 to fetch")
    unknown = ctx.unknown_id()
    r = c.call("GET", "/accounts/%d" % unknown)
    chk.part("GET /accounts/%d -> 404" % unknown, 0.25, app_404(r), "got %s" % r.describe())
    r = c.call("GET", "/accounts/abc")
    chk.part("GET /accounts/abc -> 400", 0.25, r.status == 400, "got %s" % r.describe())
    chk.finish()

    # API-06 deposit
    chk = rep.add(Check("API-06", sec, "deposit: 500 -> 200; bad amounts -> 400; unknown -> 404", 1.0))
    id_d, rd = ctx.new_account("dep")
    if not id_d:
        chk.part("setup", 0, False, "could not create an account: %s" % rd.describe())
    r = c.call("POST", "/accounts/%s/deposit" % id_d, {"amount": 500})
    ok = r.status == 200 and isinstance(r.json, dict) and r.json.get("balance") == 500 and r.json.get("id") == id_d
    chk.part("deposit 500 -> 200 balance 500", 0.4, ok, "got %s" % r.describe())
    bad = [("0", {"amount": 0}, None), ("-5", {"amount": -5}, None), ("10.5", None, b'{"amount":10.5}'),
           ("\"100\"", {"amount": "100"}, None), ("1000000001", {"amount": 1000000001}, None)]
    wrong = []
    for label, body, raw in bad:
        r = c.call("POST", "/accounts/%s/deposit" % id_d, body if raw is None else _NOBODY, raw=raw)
        if r.status != 400:
            wrong.append("amount %s -> %s" % (label, r.status))
    chk.part("amounts 0, -5, 10.5, \"100\", 1000000001 -> all 400", 0.4, not wrong, "; ".join(wrong))
    r = c.call("POST", "/accounts/%d/deposit" % unknown, {"amount": 10})
    chk.part("deposit to unknown account -> 404", 0.2, app_404(r), "got %s" % r.describe())
    chk.finish()

    # API-07 withdraw (continues on the API-06 account: 500 -> 300)
    chk = rep.add(Check("API-07", sec, "withdraw 200 -> 200 (300); 10000 -> 409, balance unchanged", 1.0))
    r = c.call("POST", "/accounts/%s/withdraw" % id_d, {"amount": 200})
    ok = r.status == 200 and isinstance(r.json, dict) and r.json.get("balance") == 300
    chk.part("withdraw 200 -> 200 balance 300", 0.5, ok, "got %s (needs the API-06 deposit)" % r.describe())
    r = c.call("POST", "/accounts/%s/withdraw" % id_d, {"amount": 10000})
    after = ctx.balance(id_d)
    ok = r.status == 409 and after == 300
    chk.part("withdraw 10000 -> 409 and balance unchanged", 0.5, ok,
             "got %s; balance on re-GET = %s (want 300)" % (r.describe(), after))
    if r.status == 409 and not (isinstance(r.json, dict) and r.json.get("error") == "insufficient funds"):
        chk.note("hint (0 pts): contract message is {\"error\":\"insufficient funds\"}, got %s" % r.short())
    chk.finish()

    # API-08 transfers
    chk = rep.add(Check("API-08", sec, "transfers: 201 shape, 400 same, 404 unknown, 409, 404-before-409", 1.0))
    id_s, rs = ctx.new_account("src")
    id_r, rr = ctx.new_account("dst")
    setup = c.call("POST", "/accounts/%s/deposit" % id_s, {"amount": 1000})
    if not (id_s and id_r and is_2xx(setup)):
        chk.note("setup failed (create 2 accounts + deposit 1000): %s / %s / %s"
                 % (rs.describe(), rr.describe(), setup.describe()))
    r = c.call("POST", "/transfers", {"from": id_s, "to": id_r, "amount": 300})
    tr = r.json if isinstance(r.json, dict) else {}
    problems = []
    if r.status != 201:
        problems.append("status %s (want 201)" % r.status)
    if tr.get("type") != "transfer":
        problems.append("type %r" % tr.get("type"))
    if tr.get("from") != id_s or tr.get("to") != id_r:
        problems.append("from/to %r/%r (want %s/%s)" % (tr.get("from"), tr.get("to"), id_s, id_r))
    if tr.get("amount") != 300:
        problems.append("amount %r" % tr.get("amount"))
    if not (is_int(tr.get("id")) and tr.get("id") > 0):
        problems.append("id %r" % tr.get("id"))
    if not (isinstance(tr.get("created_at"), str) and RFC3339.match(tr.get("created_at"))):
        problems.append("created_at %r not RFC 3339" % tr.get("created_at"))
    chk.part("valid transfer -> 201 Transaction", 0.4, not problems, "; ".join(problems) + " — " + r.describe() if problems else "")
    tr_id = tr.get("id") if is_int(tr.get("id")) else None
    r = c.call("POST", "/transfers", {"from": id_s, "to": id_s, "amount": 10})
    chk.part("from == to -> 400", 0.15, r.status == 400, "got %s" % r.describe())
    r = c.call("POST", "/transfers", {"from": id_s, "to": unknown, "amount": 10})
    chk.part("unknown to -> 404", 0.15, app_404(r), "got %s" % r.describe())
    r = c.call("POST", "/transfers", {"from": id_s, "to": id_r, "amount": 5000})
    chk.part("insufficient funds -> 409", 0.15, r.status == 409, "got %s (sender has 700)" % r.describe())
    r = c.call("POST", "/transfers", {"from": id_s, "to": unknown, "amount": MAX_AMOUNT})
    chk.part("precedence: existing poor sender + unknown to + 1e9 -> 404 (not 409)", 0.15, app_404(r),
             "got %s" % r.describe())
    chk.finish()

    # API-09 history
    chk = rep.add(Check("API-09", sec, "GET /accounts/{id}/transactions: order, omitted keys, both sides", 1.0))
    problems = []
    r = c.call("GET", "/accounts/%s/transactions" % id_d)
    txs = r.json if (r.status == 200 and isinstance(r.json, list)) else None
    if txs is None:
        problems.append("history of the deposit account: expected 200 JSON array, got %s" % r.describe())
    else:
        items = [t for t in txs if isinstance(t, dict)]
        ids = [t.get("id") for t in items]
        if not (all(is_int(i) for i in ids) and all(ids[k] < ids[k + 1] for k in range(len(ids) - 1))):
            problems.append("not oldest first (ids %s)" % ids)
        dep = [t for t in items if t.get("type") == "deposit" and t.get("amount") == 500]
        wd = [t for t in items if t.get("type") == "withdraw" and t.get("amount") == 200]
        if not dep:
            problems.append("deposit of 500 not found")
        elif "from" in dep[0] or dep[0].get("to") != id_d:
            problems.append("deposit item must have \"to\":%s and NO \"from\" key: %s" % (id_d, json.dumps(dep[0])))
        if not wd:
            problems.append("withdraw of 200 not found")
        elif "to" in wd[0] or wd[0].get("from") != id_d:
            problems.append("withdraw item must have \"from\":%s and NO \"to\" key: %s" % (id_d, json.dumps(wd[0])))
        if dep and wd and items.index(dep[0]) > items.index(wd[0]):
            problems.append("deposit must come before withdraw")
        if len(items) != 2:
            chk.note("hint (0 pts): expected exactly 2 entries (failed operations must not be recorded), got %d" % len(items))
    for who, acc in (("sender", id_s), ("receiver", id_r)):
        r = c.call("GET", "/accounts/%s/transactions" % acc)
        lst = r.json if (r.status == 200 and isinstance(r.json, list)) else []
        found = [t for t in lst if isinstance(t, dict) and t.get("type") == "transfer"
                 and (t.get("id") == tr_id if tr_id else t.get("amount") == 300)]
        if not found:
            problems.append("transfer missing from the %s's history (%s)" % (who, r.describe()))
    chk.part("order, deposit/withdraw keys, transfer in both lists", 0.75, not problems, "; ".join(problems))
    r = c.call("GET", "/accounts/%d/transactions" % unknown)
    chk.part("unknown account -> 404", 0.25, app_404(r), "got %s" % r.describe())
    chk.finish()

    info = rep.add(Check("INFO-EMPTY", sec, "new account history is [] not null (0 pts, hint)", 0, "INFO"))
    id_e, _ = ctx.new_account("empty")
    r = c.call("GET", "/accounts/%s/transactions" % id_e)
    if r.status == 200 and r.json_ok and r.json == []:
        info.note("OK: []")
    else:
        info.note("expected 200 [], got %s" % r.describe())
    info.finish()

    # API-10 error format + content type + no 5xx (whole suite)
    c.recording = False
    chk = rep.add(Check("API-10", sec, "all responses JSON content type, errors {\"error\"}, no 5xx", 0.5))
    bad_errors, bad_ct, fives, noresp = [], [], [], []
    for x in c.records:
        tag = "%s %s -> %s" % (x.method, x.path, x.status)
        if x.status is None:
            noresp.append("%s %s (%s)" % (x.method, x.path, x.error))
            continue
        if x.status >= 500:
            fives.append(tag)
        if is_mux_default(x):
            continue  # ServeMux's own 404/405 for an unregistered route: graded by the route's check
        if not x.is_json_ct:
            bad_ct.append("%s [Content-Type %r]" % (tag, x.ctype))
        if x.status >= 400 and not x.has_error_key:
            bad_errors.append("%s [body %s]" % (tag, x.short(40)))
    problems = []
    if fives:
        problems.append("%d x 5xx: %s" % (len(fives), "; ".join(fives[:4])))
    if bad_errors:
        problems.append("%d error(s) without JSON {\"error\"}: %s" % (len(bad_errors), "; ".join(bad_errors[:3])))
    if bad_ct:
        problems.append("%d response(s) without application/json: %s" % (len(bad_ct), "; ".join(bad_ct[:3])))
    if noresp:
        problems.append("%d request(s) got no response (crash?): %s" % (len(noresp), "; ".join(noresp[:2])))
    chk.part("%d responses checked" % len(c.records), 0.5, not problems, " | ".join(problems))
    chk.finish()


def same_instant(a, b):
    """created_at equal within 1 s (DBs may truncate to microseconds)."""
    if a == b:
        return True
    try:
        return abs((parse_ts(a) - parse_ts(b)).total_seconds()) <= 1.0
    except Exception:
        return False


def parse_ts(s):
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})$", s)
    base = datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")
    frac = float(m.group(2) or 0)
    tz = m.group(3)
    offset = 0 if tz == "Z" else (int(tz[1:3]) * 60 + int(tz[4:6])) * (1 if tz[0] == "+" else -1)
    return base + datetime.timedelta(seconds=frac) - datetime.timedelta(minutes=offset)


# ----------------------------------------------------------------------------
# concurrency (3 pts) + bonus B4 (+4) + bonus B1 (+4)
# ----------------------------------------------------------------------------

def run_concurrency(ctx, rep):
    c = ctx.c
    sec = "Concurrency"

    # Storms grade concurrency, not status codes (those are graded in API-0x): success is
    # any 2xx, a rejection any 4xx. Unusual codes only produce a note.
    chk = rep.add(Check("CON-1", sec, "100 parallel deposits of 10 -> all 2xx, balance exactly 1000", 1.5))
    x, rx = ctx.new_account("conx")
    if not x:
        chk.part("storm", 1.5, False, "could not create account: %s" % rx.describe())
    else:
        resps = storm(c, [("POST", "/accounts/%d/deposit" % x, {"amount": 10})] * 100)
        bal = ctx.balance(x)
        all_ok = all(is_2xx(r) for r in resps)
        chk.part("storm", 1.5, all_ok and bal == 1000,
                 "statuses: %s; final balance %s (want 1000)" % (status_counts(resps), bal))
        if all_ok and any(r.status != 200 for r in resps):
            chk.note("deposits answered %s instead of 200 (status codes are graded in API-06)" % status_counts(resps))
    chk.finish()

    chk = rep.add(Check("CON-2", sec, "50 parallel transfers of 30 from 1000 -> 33 ok (2xx) + 17 rejected (4xx), X=10, Y=990", 1.5))
    if not x or ctx.balance(x) != 1000:
        # CON-2 must not depend on CON-1: fund a fresh sender with ONE deposit
        x, rx = ctx.new_account("conx2")
        dep = c.call("POST", "/accounts/%s/deposit" % x, {"amount": 1000})
        chk.note("CON-1 did not leave 1000; used a fresh sender funded with one deposit (%s)" % dep.status)
    y, ry = ctx.new_account("cony")
    if not (x and y):
        chk.part("storm", 1.5, False, "could not create accounts: %s / %s" % (rx.describe(), ry.describe()))
    else:
        resps = storm(c, [("POST", "/transfers", {"from": x, "to": y, "amount": 30})] * 50)
        n_ok = sum(1 for r in resps if is_2xx(r))
        n_rej = sum(1 for r in resps if r.status is not None and 400 <= r.status < 500)
        n5xx = sum(1 for r in resps if r.status is None or r.status >= 500)
        bx, by = ctx.balance(x), ctx.balance(y)
        ok = n_ok == 33 and n_rej == 17 and n5xx == 0 and bx == 10 and by == 990
        chk.part("storm", 1.5, ok, "statuses: %s (want 33 x 2xx + 17 x 4xx, no 5xx); X=%s (want 10), Y=%s (want 990)"
                 % (status_counts(resps), bx, by))
        if ok and any(r.status not in (201, 409) for r in resps):
            chk.note("transfers answered %s instead of 201/409 (status codes are graded in API-08)" % status_counts(resps))
    chk.finish()


def run_bonus_b4(ctx, rep):
    c = ctx.c
    chk = rep.add(Check("BON-B4", "Bonus (auto)", "deadlock-safe: 2x100 alternating P<->Q transfers of 7 -> all 2xx, P=Q=1000", 4,
                        stage="B4"))
    p, rp = ctx.new_account("p")
    q, rq = ctx.new_account("q")
    d1 = c.call("POST", "/accounts/%s/deposit" % p, {"amount": 1000})
    d2 = c.call("POST", "/accounts/%s/deposit" % q, {"amount": 1000})
    if not (p and q and is_2xx(d1) and is_2xx(d2)):
        chk.part("setup", 4, False, "could not create/fund P and Q: %s / %s" % (d1.describe(), d2.describe()))
        return chk.finish()
    resps = []
    for _ in range(2):
        jobs = []
        for i in range(100):
            src, dst = (p, q) if i % 2 == 0 else (q, p)
            jobs.append(("POST", "/transfers", {"from": src, "to": dst, "amount": 7}))
        resps += storm(c, jobs)
    bp, bq = ctx.balance(p), ctx.balance(q)
    all_ok = all(is_2xx(r) for r in resps)
    conserved = is_int(bp) and is_int(bq) and bp + bq == 2000
    detail = "statuses: %s; P=%s Q=%s (P+Q=%s, want 1000/1000/2000)" % (
        status_counts(resps), bp, bq, (bp + bq) if conserved or (is_int(bp) and is_int(bq)) else "?")
    if all_ok and bp == 1000 and bq == 1000:
        chk.part("storm", 4, True)
        if any(r.status != 201 for r in resps):
            chk.note("transfers answered %s instead of 201 (status codes are graded in API-08)" % status_counts(resps))
    elif conserved:
        chk.part("storm", 4, 0.25, "money conserved but not every response was 2xx (deadlock 40P01 -> 500?) — " + detail)
    else:
        chk.part("storm", 4, False, detail)
    return chk.finish()


def parse_prometheus(text):
    samples = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{(.*)\})?\s+(\S+)", line)
        if not m:
            continue
        labels = dict(re.findall(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"', m.group(3) or ""))
        samples.append((m.group(1), labels, m.group(4)))
    return samples


def run_bonus_b1(ctx, rep):
    chk = rep.add(Check("BON-B1", "Bonus (auto)", "GET /metrics: TYPE, http_requests_total{method,path,status}, histogram, transfers", 4,
                        stage="B1"))
    r = ctx.c.call("GET", "/metrics")
    text = r.body.decode("utf-8", "replace") if r.status == 200 else ""
    chk.part("200 Prometheus text with # TYPE", 1, r.status == 200 and "# TYPE" in text,
             "got %s" % (r.describe() if r.status != 200 else "no '# TYPE' line"))
    samples = parse_prometheus(text)
    reqs = [s for s in samples if s[0] == "http_requests_total"]
    problems = []
    if not reqs:
        problems.append("http_requests_total not found")
    else:
        missing = [s for s in reqs if not all(k in s[1] for k in ("method", "path", "status"))]
        if missing:
            problems.append("%d sample(s) without method/path/status labels" % len(missing))
        paths = sorted(set(s[1].get("path", "") for s in reqs))
        raw = [p for p in paths if re.search(r"/\d+(/|$)", p)]
        if raw:
            problems.append("raw ids used as path labels: %s" % ", ".join(raw[:4]))
        if not any("{" in p for p in paths):
            problems.append("no route pattern like /accounts/{id} among path labels %s" % paths[:6])
    chk.part("http_requests_total{method,path,status} with route patterns", 1, not problems, "; ".join(problems))
    chk.part("http_request_duration_seconds_bucket present", 1,
             any(s[0] == "http_request_duration_seconds_bucket" for s in samples), "histogram buckets not found")
    tr = [s for s in samples if s[0] == "minibank_transfers_total"]
    results = sorted(set(s[1].get("result", "<none>") for s in tr))
    allowed = {"ok", "insufficient_funds", "error"}
    ok = bool(tr) and all("result" in s[1] for s in tr) and set(results) <= allowed
    chk.part("minibank_transfers_total{result}", 1, ok,
             "found result values %s (allowed: ok, insufficient_funds, error)" % results if tr else "minibank_transfers_total not found")
    return chk.finish()


# ----------------------------------------------------------------------------
# generic helpers for repo checks
# ----------------------------------------------------------------------------

SKIP_DIRS = {".git", "vendor", "node_modules", ".idea", ".vscode", "bin", "dist"}


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def walk_files(root, suffixes=None):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if suffixes is None or name.endswith(tuple(suffixes)):
                yield os.path.join(dirpath, name)


def run_cmd(cmd, cwd=None, timeout=120, env=None, stdin_text=None):
    """returns (rc, stdout, stderr); rc None = not found, -9 = timeout."""
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", input=stdin_text)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return None, "", "%s: command not found" % cmd[0]
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
        return -9, out, "timed out after %ss" % timeout


def git(repo, *args):
    rc, out, err = run_cmd(["git", "-C", repo] + list(args), timeout=30)
    return (rc if rc is not None else 127), out


def first_line(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def strip_yaml_comments(text):
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            out.append("")
            continue
        # drop " # comment" when the # is outside quotes
        quote = None
        cut = None
        for i, ch in enumerate(line):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == "#" and i > 0 and line[i - 1] in " \t":
                cut = i
                break
        out.append(line[:cut].rstrip() if cut is not None else line.rstrip())
    return "\n".join(out)


def indent_of(line):
    return len(line) - len(line.lstrip(" "))


def yaml_block(lines, i):
    """lines that belong to the key on lines[i] (more indented, or a compact '- ' list)."""
    base = indent_of(lines[i])
    key_is_item = lines[i].lstrip().startswith("- ")
    out = []
    for line in lines[i + 1:]:
        if not line.strip():
            out.append(line)
            continue
        ind = indent_of(line)
        if ind > base or (ind == base and line.lstrip().startswith("- ") and not key_is_item):
            out.append(line)
        else:
            break
    return out


def yaml_children(lines):
    """split a block into its direct child keys: {name: [lines]}"""
    real = [l for l in lines if l.strip()]
    if not real:
        return {}
    ind = min(indent_of(l) for l in real)
    children, current = {}, None
    for line in lines:
        if line.strip() and indent_of(line) == ind:
            m = re.match(r"^\s*([A-Za-z0-9_.\-\"']+)\s*:", line)
            current = m.group(1).strip("\"'") if m else None
            if current:
                children[current] = [line]
            continue
        if current:
            children[current].append(line)
    return children


def find_key(lines, key):
    for i, line in enumerate(lines):
        if re.match(r"^\s*-?\s*%s\s*:" % re.escape(key), line):
            return i
    return None


# ----------------------------------------------------------------------------
# REPO-S0 kickoff: decisions, go.mod, .gitignore, merges
# ----------------------------------------------------------------------------

DECISION_KEYS = ["OUT OF SCOPE", "AI PLAN", "CONCURRENCY", "STRUCTURE", "SECURITY", "RISKS", "DATA", "WHAT"]
PLACEHOLDER = "اینجا بنویس"
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def norm_fa(s):
    for ch in ("\u200c", "\u200d", "\u200e", "\u200f", "\u00a0"):
        s = s.replace(ch, "" if ch != "\u00a0" else " ")
    return s


def md_lines_outside_code(text):
    """yield (line, is_code) so '#' comments inside ``` blocks are not headings."""
    in_code = False
    for line in text.splitlines():
        if line.lstrip().startswith("```") or line.lstrip().startswith("~~~"):
            in_code = not in_code
            yield line, True
            continue
        yield line, in_code


def parse_decisions(text):
    """returns None or {"keys": {KEY: "answered"|"answered_ph"|"placeholder"|"empty"}, "words": n}"""
    lines = list(md_lines_outside_code(text))
    start, level = None, None
    for i, (line, code) in enumerate(lines):
        m = HEADING.match(line) if not code else None
        if m:
            h = norm_fa(m.group(2))
            if "my decisions" in h.lower() or "تصمیمهای من" in h or "تصمیم های من" in h:
                start, level = i, len(m.group(1))
                break
    if start is None:
        return None
    section = []
    for line, code in lines[start + 1:]:
        m = HEADING.match(line) if not code else None
        if m and len(m.group(1)) <= level:
            break
        section.append((line, code))
    answers, current = {}, None
    for line, code in section:
        m = HEADING.match(line) if not code else None
        if m:
            h = norm_fa(m.group(2)).upper()
            current = None
            for key in DECISION_KEYS:
                if re.search(r"(^|[^A-Z])%s([^A-Z]|$)" % re.escape(key), h):
                    current = key
                    break
            if current and current not in answers:
                answers[current] = []
            continue
        if current:
            answers[current].append(line)
    # FILLED = after removing the placeholder line(s) and `>` guidance lines, >= 40 chars
    # of real text remain. A placeholder line left next to a real answer still counts as
    # filled ("answered_ph"), with a note.
    state, total_words = {}, 0
    for key in DECISION_KEYS:
        if key not in answers:
            continue
        body = answers[key]
        has_ph = any(PLACEHOLDER in norm_fa(l) for l in body)
        content = [l.strip() for l in body if l.strip() and not l.lstrip().startswith(">")
                   and PLACEHOLDER not in norm_fa(l)]
        text = " ".join(content)
        total_words += len(re.findall(r"\w+", text, re.UNICODE))
        if len(text) >= 40:
            state[key] = "answered_ph" if has_ph else "answered"
        elif has_ph:
            state[key] = "placeholder"
        else:
            state[key] = "empty"
    return {"keys": state, "words": total_words}


def check_s0(repo, rep):
    chk = rep.add(Check("REPO-S0", "Repo assists", "kickoff: My decisions, go.mod/.gitignore, >= 4 stage merges", 5,
                        "ASSIST", "S0"))
    # decisions
    found = None  # the candidate file with the most answered decisions wins
    for name in ("PLAN.md", "DECISIONS.md", "docs/PLAN.md", "docs/DECISIONS.md", "README.md"):
        p = os.path.join(repo, name)
        if os.path.isfile(p):
            parsed = parse_decisions(read_text(p))
            if parsed is not None:
                score = sum(1 for v in parsed["keys"].values() if v.startswith("answered"))
                if found is None or score > found[2]:
                    found = (name, parsed, score)
    if not found:
        chk.part("\"My decisions\" section", 2, False, "no heading with \"My decisions\" / \"تصمیم‌های من\" in PLAN.md or DECISIONS.md")
    else:
        name, parsed, _ = found
        st = parsed["keys"]
        answered = [k for k in DECISION_KEYS if st.get(k, "").startswith("answered")]
        left_ph = [k for k in DECISION_KEYS if st.get(k) == "answered_ph"]
        missing = [k for k in DECISION_KEYS if k not in st]
        placeholder = [k for k in DECISION_KEYS if st.get(k) == "placeholder"]
        empty = [k for k in DECISION_KEYS if st.get(k) == "empty"]
        frac = len(answered) / 8.0
        why = "%s: %d/8 answered (%d words)" % (name, len(answered), parsed["words"])
        if missing:
            why += "; missing headings: %s" % ", ".join(missing)
        if placeholder:
            why += "; still placeholder: %s" % ", ".join(placeholder)
        if empty:
            why += "; too short (< 40 chars): %s" % ", ".join(empty)
        chk.part("\"My decisions\" filled (8 answers, >= 40 chars each)", 2, round_q(frac, 0.125), why)
        if left_ph:
            chk.note("placeholder line not deleted (answer counted as filled): %s" % ", ".join(left_ph))
        if frac == 1.0:
            chk.note("decisions: %s — all 8 answered (%d words). Quality is MANUAL." % (name, parsed["words"]))
        when = decisions_completed_at(repo, name)
        if when:
            chk.note(when)
    # go.mod / .gitignore
    gomod = read_text(os.path.join(repo, "go.mod"))
    mm = re.search(r"^module\s+(\S+)", gomod, re.M)
    gov = re.search(r"^go\s+(\S+)", gomod, re.M)
    chk.part("go.mod with module line", 0.5, bool(mm), "go.mod missing or has no module line")
    if mm:
        chk.note("go.mod: module %s, go %s" % (mm.group(1), gov.group(1) if gov else "?"))
    gi = read_text(os.path.join(repo, ".gitignore"))
    gi_lines = [l.strip() for l in gi.splitlines() if l.strip() and not l.startswith("#")]
    has_env = any(re.match(r"^/?\.env(\*|\.\*)?$", l) for l in gi_lines)
    binname = mm.group(1).split("/")[-1] if mm else "minibank"
    has_bin = any(l in ("bin", "bin/", "/bin", "/bin/", "*.exe", binname, "/" + binname, "dist/", "/dist")
                  or l.endswith("/" + binname) for l in gi_lines)
    has_cov = any("cover" in l or l in ("*.out", "*.test", "*.prof") for l in gi_lines)
    got = [n for n, ok in (("binaries", has_bin), (".env", has_env), ("coverage", has_cov)) if ok]
    chk.part(".gitignore covers binaries, .env, coverage", 0.5, len(got) / 3.0,
             "covers only: %s" % (", ".join(got) or "nothing") if gi else ".gitignore missing")
    rc, remotes = git(repo, "remote", "-v")
    if "github.com" not in remotes:
        chk.note("no github.com remote configured in this clone (pushed? confirm on GitHub)")
    # merges on main
    main = main_branch(repo)
    if not main:
        chk.part(">= 4 stage branches merged into main", 2, False, "not a git repository")
    else:
        # every merge commit on main's first-parent line: `git merge --no-ff` and GitHub
        # "Merge pull request #N" both create one (squash/rebase merges do not).
        rc, out = git(repo, "log", "--merges", "--first-parent", main, "--format=%s")
        merges = [l for l in out.splitlines() if l.strip()]
        prs = [l for l in merges if re.match(r"Merge pull request #\d+", l)]
        chk.part("stage merges into %s: 0.5 per merge, max 2 (4 merges)" % main, 2, min(1.0, 0.5 * len(merges) / 2.0),
                 "%d merge commit(s) on %s" % (len(merges), main))
        if merges:
            chk.note("%d merge commit(s) on %s (%d GitHub PR merge(s)), e.g. %s"
                     % (len(merges), main, len(prs), "; ".join(merges[:4])))
    return chk.finish()


def main_branch(repo):
    for ref in ("main", "master", "origin/main", "origin/master", "HEAD"):
        rc, _ = git(repo, "rev-parse", "--verify", "--quiet", ref)
        if rc == 0:
            return ref
    return None


def decisions_completed_at(repo, name):
    rc, out = git(repo, "log", "--all", "--reverse", "--format=%ct", "--max-count=1000")
    times = [int(t) for t in out.split() if t.isdigit()]
    if not times:
        return None
    t0 = min(times)
    rc, out = git(repo, "log", "--reverse", "--format=%H %ct", "--", name)
    for line in out.splitlines()[:30]:
        sha, ct = line.split()
        rc2, content = git(repo, "show", "%s:%s" % (sha, name))
        parsed = parse_decisions(content) if rc2 == 0 else None
        if parsed and sum(1 for v in parsed["keys"].values() if v.startswith("answered")) == 8:
            minutes = (int(ct) - t0) / 60.0
            flag = "OK" if minutes <= 15 else "LATE (target <= 15 min)"
            return "decisions complete in commit %s at +%.0f min after the first commit: %s" % (sha[:7], minutes, flag)
    return "decisions never complete in any commit of %s" % name


# ----------------------------------------------------------------------------
# REPO-S1 hints (0 pts) — help the manual S1 review
# ----------------------------------------------------------------------------

def check_s1_hints(repo, rep):
    chk = rep.add(Check("REPO-S1", "Repo assists", "S1 code hints for the manual review (0 pts)", 0, "INFO", "S1"))
    src, tests = "", ""
    sprintf_sql, floats = [], []
    for path in walk_files(repo, [".go"]):
        text = read_text(path)
        rel = os.path.relpath(path, repo)
        if path.endswith("_test.go"):
            tests += text
            continue
        src += text
        for n, line in enumerate(text.splitlines(), 1):
            if re.search(r"Sprintf\(\s*[`\"][^`\"]*\b(SELECT|INSERT|UPDATE|DELETE)\b", line, re.I):
                sprintf_sql.append("%s:%d" % (rel, n))
            if "float64" in line and re.search(r"(?i)amount|balance|money", line):
                floats.append("%s:%d" % (rel, n))
    if not src:
        chk.note("no Go source files found")
        return chk.finish()

    def has(pattern, flags=0):
        return re.search(pattern, src, flags) is not None

    hints = [
        ("rune counting (utf8.RuneCountInString)", has(r"utf8\.RuneCountInString|\[\]rune\(")),
        ("strings.TrimSpace on owner", has(r"strings\.TrimSpace")),
        ("sentinel errors (%d/5 contract names)" % sum(1 for n in ("ErrInvalidOwner", "ErrInvalidAmount", "ErrSameAccount",
                                                                    "ErrAccountNotFound", "ErrInsufficientFunds") if n in src),
         all(n in src for n in ("ErrInvalidOwner", "ErrInvalidAmount", "ErrSameAccount", "ErrAccountNotFound", "ErrInsufficientFunds"))),
        ("errors.Is used", has(r"errors\.Is\(")),
        ("Store interface", has(r"type\s+Store\s+interface")),
        ("in-memory store with sync.Mutex/RWMutex", has(r"sync\.(RW)?Mutex")),
        ("STORE env selection", has(r"\"STORE\"")),
        ("pgx driver", has(r"jackc/pgx/v5")),
        ("CREATE TABLE IF NOT EXISTS", has(r"CREATE TABLE IF NOT EXISTS", re.I)),
        ("CHECK (balance >= 0)", has(r"CHECK\s*\(\s*balance\s*>=\s*0\s*\)", re.I)),
        ("SQL transaction (Begin/BeginFunc/BeginTx)", has(r"\.Begin(Tx|Func)?\(|BeginFunc\(")),
        ("no read-check-write (FOR UPDATE or balance >= $n)", has(r"FOR\s+(NO\s+KEY\s+)?UPDATE|balance\s*>=\s*\$\d", re.I)),
        ("parameterized SQL ($1)", has(r"\$1")),
        ("http.MaxBytesReader", has(r"MaxBytesReader")),
        ("log/slog JSON handler", has(r"slog\.NewJSONHandler")),
        ("panic recovery (recover())", has(r"recover\(\)")),
        ("graceful shutdown (signal + Shutdown)", has(r"signal\.Notify") and has(r"\.Shutdown\(")),
        ("/readyz with context timeout", has(r"/readyz") and has(r"context\.WithTimeout")),
    ]
    for label, ok in hints:
        chk.note("%s %s" % ("found  " if ok else "MISSING", label))
    if sprintf_sql:
        chk.note("RED FLAG fmt.Sprintf SQL at %s" % ", ".join(sprintf_sql[:5]))
    if floats:
        chk.note("check float64 near money at %s" % ", ".join(floats[:5]))
    return chk.finish()


# ----------------------------------------------------------------------------
# REPO-S2 tests
# ----------------------------------------------------------------------------

def check_s2(repo, rep):
    chk = rep.add(Check("REPO-S2", "Repo assists", "tests: table-driven, concurrency, httptest, go test -race (no DB)", 8,
                        "ASSIST", "S2"))
    tests = {os.path.relpath(p, repo): read_text(p) for p in walk_files(repo, ["_test.go"])}
    alltext = "\n".join(tests.values())
    if not tests:
        chk.part("test files", 8, False, "no *_test.go files")
        return chk.finish()
    chk.note("%d test file(s): %s" % (len(tests), ", ".join(sorted(tests)[:6])))
    table = re.search(r"\[\]struct\s*\{", alltext) is not None
    trun = "t.Run(" in alltext
    eis = "errors.Is(" in alltext
    frac = (1.0 if table and trun and eis else (2.0 / 3 if table and trun else (1.0 / 3 if table or trun else 0)))
    chk.part("table-driven tests ([]struct + t.Run + errors.Is)", 3, round_q(frac, 0.01),
             "[]struct %s, t.Run %s, errors.Is %s (>= 5 cases: confirm by eye)"
             % (yes(table), yes(trun), yes(eis)))
    # concurrency: 2 = one test file with sync.WaitGroup + `go func` + >= 100 goroutines
    # (literal or loop bound >= 100); 1 = WaitGroup + go func only
    conc_files = [f for f, t in tests.items() if "sync.WaitGroup" in t and re.search(r"\bgo\s+func\b", t)]
    counts = {f: goroutine_bound(tests[f]) for f in conc_files}
    best = max(counts.values()) if counts else 0
    conc = 1.0 if best >= 100 else (0.5 if conc_files else 0)
    chk.part("concurrency test: sync.WaitGroup + go func + >= 100 goroutines", 2, conc,
             "WaitGroup + go func in %s; largest goroutine count / loop bound found: %s (want >= 100)"
             % (", ".join(conc_files) or "no test file", best or "none"))
    if conc == 1.0:
        chk.note("concurrency test in %s with %d goroutines (exact final assert: confirm by eye)"
                 % (max(counts, key=counts.get), best))
    # httptest: 2 = httptest + >= 3 distinct method/route pairs + an error status literal
    ht_files = [f for f, t in tests.items() if "httptest." in t]
    httext = "\n".join(tests[f] for f in ht_files)
    pairs = route_pairs(httext)
    err_status = re.search(r"http\.Status(BadRequest|NotFound|Conflict)\b|\b(400|404|409)\b", httext) is not None
    ht = 1.0 if (ht_files and len(pairs) >= 3 and err_status) else (0.5 if ht_files else 0)
    chk.part("httptest: >= 3 endpoints incl. an error case", 2, ht,
             "httptest in %s; %d distinct method/route pair(s) %s; error status literal %s"
             % (", ".join(ht_files) or "no test file", len(pairs), sorted(pairs)[:6], yes(err_status)))
    if ht == 1.0:
        chk.note("httptest covers %d method/route pairs, e.g. %s" % (len(pairs), ", ".join(sorted(pairs)[:5])))
    if shutil.which("go") is None:
        chk.part("go test -race ./... without DB", 1, False, "go toolchain not installed on this machine")
        return chk.finish()
    env = dict(os.environ)
    for k in ("DATABASE_URL", "STORE", "MINIBANK_TEST_DATABASE_URL", "REDIS_ADDR", "REDIS_PASSWORD",
              "TEST_DATABASE_URL", "PGHOST"):
        env.pop(k, None)
    rc, out, err = run_cmd(["go", "vet", "./..."], cwd=repo, timeout=180, env=env)
    chk.note("go vet: %s" % ("OK" if rc == 0 else "FAIL %s" % first_line(err or out)))
    rc, out, err = run_cmd(["gofmt", "-l", "."], cwd=repo, timeout=60, env=env)
    unformatted = [l for l in out.splitlines() if l.strip() and not l.startswith("vendor/")]
    chk.note("gofmt -l: %s" % ("clean" if rc == 0 and not unformatted else "not formatted: %s" % ", ".join(unformatted[:5])))
    t0 = time.time()
    rc, out, err = run_cmd(["go", "test", "-race", "-count=1", "./..."], cwd=repo, timeout=240, env=env)
    took = time.time() - t0
    failing = [l for l in (out + err).splitlines() if l.startswith(("FAIL", "--- FAIL", "panic:"))]
    reason = "timed out after 240 s" if rc == -9 else ("exit %s: %s" % (rc, "; ".join(failing[:4]) or first_line(err)))
    chk.part("go test -race -count=1 ./... (DB env vars removed)", 1, rc == 0, reason)
    if rc == 0:
        skipped = len(re.findall(r"\bno test files\b", out))
        chk.note("go test -race OK in %.0f s (%d package(s) without tests)" % (took, skipped))
    return chk.finish()


def yes(b):
    return "yes" if b else "NO"


def goroutine_bound(text):
    """largest goroutine count in a test file: wg.Add(N) or a for-loop bound (literal or a
    const/var assigned a literal), e.g. `for range 100`, `for i := 0; i < n; i++` with n = 100."""
    def value(tok):
        tok = tok.replace("_", "")
        if tok.isdigit():
            return int(tok)
        m = re.search(r"\b%s\b\s*(?::=|=)\s*(\d[\d_]*)\b" % re.escape(tok), text)
        return int(m.group(1).replace("_", "")) if m else 0
    bounds = re.findall(r"\bfor\b[^{\n]*?(?:<=?|\brange)\s*([A-Za-z_]\w*|\d[\d_]*)\s*(?:;|\{)", text)
    bounds += re.findall(r"\.Add\(\s*(\d[\d_]*)\s*\)", text)
    return max([value(b) for b in bounds] + [0])


def route_pairs(text):
    """distinct (METHOD /path) pairs in test code; numeric segments and %d become {id}."""
    found = set()
    pat = (r"(?:http\.Method(Get|Post|Put|Patch|Delete)|\"(GET|POST|PUT|PATCH|DELETE)\")\s*,\s*"
           r"(?:fmt\.Sprintf\(\s*)?\"(/[^\"]*)\"")
    for m in re.finditer(pat, text):
        method = (m.group(1) or m.group(2)).upper()
        path = m.group(3).split("?", 1)[0]
        path = "/".join("{id}" if (seg.isdigit() or seg in ("%d", "%v", "%s")) else seg for seg in path.split("/"))
        found.add("%s %s" % (method, path))
    return found


# ----------------------------------------------------------------------------
# REPO-S3 scripts
# ----------------------------------------------------------------------------

def strict_mode(text):
    """a `set` line whose flags include e, u and -o pipefail: set -euo pipefail,
    set -Eeuo pipefail, set -e -u -o pipefail, ..."""
    for m in re.finditer(r"(?m)^\s*set\s+([^#\n]*)", text):
        toks = m.group(1).split()
        letters, pipefail = set(), False
        for i, tok in enumerate(toks):
            if tok.startswith("-") and not tok.startswith("--"):
                letters |= set(tok[1:])
                if "o" in tok[1:] and i + 1 < len(toks) and toks[i + 1] == "pipefail":
                    pipefail = True
        if "e" in letters and "u" in letters and pipefail:
            return True
    return False


def git_mode(repo, rel):
    rc, out = git(repo, "ls-files", "-s", "--", rel)
    return out.split()[0] if rc == 0 and out.strip() else None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def check_s3(repo, rep, url, reachable):
    chk = rep.add(Check("REPO-S3", "Repo assists", "scripts: check-env.sh + smoke.sh (static + runs)", 7, "ASSIST", "S3"))
    ce = os.path.join(repo, "scripts", "check-env.sh")
    sm = os.path.join(repo, "scripts", "smoke.sh")
    texts = {}
    basics = 0.0
    for rel, path in (("scripts/check-env.sh", ce), ("scripts/smoke.sh", sm)):
        if not os.path.isfile(path):
            chk.note("%s missing" % rel)
            continue
        t = read_text(path)
        texts[rel] = t
        shebang = t.startswith("#!/usr/bin/env bash")
        strict = strict_mode(t)
        mode = git_mode(repo, rel)
        rc, _, err = run_cmd(["bash", "-n", path], timeout=20)
        syntax = rc == 0
        good = sum([shebang, strict, mode == "100755", syntax]) / 4.0
        basics += 0.5 * good
        if good < 1:
            chk.note("%s: shebang %s, strict mode (e,u,-o pipefail) %s, git mode %s (want 100755), bash -n %s"
                     % (rel, yes(shebang), yes(strict), mode or "untracked", "OK" if syntax else "FAIL " + first_line(err)))
    chk.part("both scripts (0.5 each): env-bash shebang, strict mode (e, u, -o pipefail), mode 100755, bash -n", 1, basics,
             "see notes above")
    t = texts.get("scripts/check-env.sh", "")
    tools = {name: re.search(r"\b%s\b" % name, t) is not None for name in ("go", "git", "docker", "kubectl")}
    cluster = re.search(r"\bkind\b|\bminikube\b", t) is not None
    lines_ok = "ALL GOOD" in t and "MISSING" in t
    marks = "✓" in t and "✗" in t
    score = (sum(tools.values()) + cluster + lines_ok + marks) / 7.0
    if not t:
        chk.part("check-env: go git docker kubectl kind|minikube, ✓/✗, ALL GOOD / MISSING", 1, False, "check-env.sh missing")
        chk.part("check-env checks the Docker daemon (docker info)", 1, False, "check-env.sh missing")
    else:
        chk.part("check-env: go git docker kubectl kind|minikube, ✓/✗, ALL GOOD / MISSING", 1, round_q(score, 0.01),
                 "%s, kind|minikube %s, ALL GOOD+MISSING lines %s, ✓/✗ marks %s"
                 % (", ".join("%s %s" % (k, yes(v)) for k, v in tools.items()), yes(cluster), yes(lines_ok), yes(marks)))
        chk.part("check-env checks the Docker daemon (docker info)", 1, "docker info" in t, "no `docker info` in check-env.sh")
    if t:
        rc, out, err = run_cmd(["bash", ce], cwd=repo, timeout=60)
        chk.note("check-env.sh on this machine: exit %s, last line %r" % (rc, (out.strip().splitlines() or [""])[-1]))
    s = texts.get("scripts/smoke.sh", "")
    dynamic = re.search(r"\bjq\b|\bsed\b|grep\s+-o|\bawk\b|python", s) is not None
    # small literal ids are hard-coded; very large ones (999999999999) are fine "unknown" ids
    hard = ["/accounts/" + x for x in re.findall(r"/accounts/([0-9]+)\b", s) if len(x) < 7]
    chk.part("smoke captures ids dynamically (jq/sed/grep, no hard-coded ids)", 1, dynamic and not hard,
             "parser %s, hard-coded ids %s" % (yes(dynamic), hard[:3] or "none"))
    if not s:
        chk.part("smoke >= 6 checks", 1, False, "smoke.sh missing")
        chk.part("closed-port run: non-zero exit + >= 1 FAIL line + 'N passed, M failed'", 1, False, "smoke.sh missing")
        chk.part("smoke green against --url", 1, False, "smoke.sh missing")
        return chk.finish()
    # negative run: against a closed port it must FAIL and exit non-zero
    dead = "http://127.0.0.1:%d" % free_port()
    rc_dead, out_dead, _ = run_cmd(["bash", sm, dead], cwd=repo, timeout=120)
    fail_lines = len(re.findall(r"^FAIL\b", out_dead, re.M))
    dead_summary = re.search(r"(\d+)\s+passed,\s+(\d+)\s+failed", out_dead)
    if reachable:
        rc, out, err = run_cmd(["bash", sm, url], cwd=repo, timeout=180)
        pass_lines = len(re.findall(r"^PASS\b", out, re.M))
        fails = len(re.findall(r"^FAIL\b", out, re.M))
        summary = re.search(r"(\d+)\s+passed,\s+(\d+)\s+failed", out)
        chk.part("smoke >= 6 checks (PASS/FAIL lines against --url)", 1, pass_lines + fails >= 6,
                 "%d PASS/FAIL lines" % (pass_lines + fails))
        fmt_ok = bool(dead_summary) and rc_dead not in (0, None) and fail_lines >= 1
        chk.part("closed-port run: non-zero exit + >= 1 FAIL line + 'N passed, M failed'", 1, fmt_ok,
                 "against %s: exit %s, %d FAIL line(s), summary line %s" % (dead, rc_dead, fail_lines, yes(bool(dead_summary))))
        chk.part("smoke green against %s" % url, 1, rc == 0,
                 "exit %s; failing: %s" % (rc, "; ".join(l for l in out.splitlines() if l.startswith("FAIL"))[:200]))
        if rc == 0:
            chk.note("smoke.sh %s -> exit 0 (%s). Confirm it is also green on compose AND k8s." %
                     (url, summary.group(0) if summary else "%d PASS" % pass_lines))
    else:
        chk.part("smoke >= 6 checks", 1, False, "server unreachable, smoke not run")
        chk.part("closed-port run: non-zero exit + >= 1 FAIL line + 'N passed, M failed'", 1,
                 bool(dead_summary) and rc_dead not in (0, None) and fail_lines >= 1,
                 "against %s: exit %s, %d FAIL line(s), summary line %s" % (dead, rc_dead, fail_lines, yes(bool(dead_summary))))
        chk.part("smoke green against --url", 1, False, "server unreachable")
    return chk.finish()


# ----------------------------------------------------------------------------
# REPO-S4 Dockerfile (+ IMG-1)
# ----------------------------------------------------------------------------

def check_s4(repo, rep):
    chk = rep.add(Check("REPO-S4", "Repo assists", "Dockerfile: multi-stage, non-root, cache order, static, .dockerignore", 6,
                        "ASSIST", "S4"))
    path = os.path.join(repo, "Dockerfile")
    if not os.path.isfile(path):
        chk.part("Dockerfile", 6, False, "no Dockerfile at the repo root")
        return chk.finish()
    raw = read_text(path)
    lines = [l.strip() for l in raw.splitlines() if l.strip() and not l.strip().startswith("#")]
    froms = [l for l in lines if re.match(r"(?i)^FROM\s", l)]
    images = []
    for f in froms:  # FROM [--platform=...] image[:tag] [AS name]
        toks = [t for t in f.split()[1:] if not t.startswith("--")]
        images.append(toks[0].lower() if toks else "")
    builder = any("golang" in i for i in images[:-1])
    final = images[-1] if images else ""
    final_name = final.rsplit("/", 1)[-1]
    final_ok = final_name == "scratch" or "distroless" in final or final_name.startswith("alpine")
    chk.part("multi-stage: golang builder -> final FROM scratch/distroless/alpine", 2, len(froms) >= 2 and builder and final_ok,
             "%d FROM line(s), golang builder %s, final %r" % (len(froms), yes(builder), final or "-"))
    if froms:
        chk.note("final base: %s" % froms[-1])
    last_from = max(i for i, l in enumerate(lines) if re.match(r"(?i)^FROM\s", l)) if froms else 0
    users = [l for l in lines[last_from:] if re.match(r"(?i)^USER\s", l)]
    user = users[-1].split(None, 1)[1].strip() if users else ""
    nonroot = bool(user) and not re.match(r"^(root|0)(:|$)", user)
    if not users and froms and ":nonroot" in froms[-1]:
        nonroot = True
        chk.note("no USER line, but the distroless :nonroot base runs as 65532")
    chk.part("runs as non-root (USER in final stage)", 1, nonroot, "final stage USER %r" % (user or "not set"))
    di = os.path.join(repo, ".dockerignore")
    dtext = read_text(di)
    di_ok = 1.0 if (".git" in dtext and ".env" in dtext) else (0.5 if os.path.isfile(di) else 0)
    chk.part(".dockerignore (excludes .git, .env, ...)", 1, di_ok,
             "missing" if not os.path.isfile(di) else "does not exclude both .git and .env")
    joined = "\n".join(lines)
    i_mod = re.search(r"(?im)^COPY\s+(--\S+\s+)*go\.mod", joined)
    i_dl = re.search(r"(?im)^RUN\s+.*go mod download", joined)
    i_all = re.search(r"(?im)^COPY\s+(--\S+\s+)*\.\s+\.", joined)
    order = bool(i_mod and i_dl and i_all and i_mod.start() < i_dl.start() < i_all.start())
    chk.part("cache-friendly: COPY go.mod go.sum -> go mod download -> COPY . .", 1, order,
             "go.mod copy %s, go mod download %s, COPY . . %s, order %s"
             % (yes(bool(i_mod)), yes(bool(i_dl)), yes(bool(i_all)), "OK" if order else "wrong"))
    cgo = "CGO_ENABLED=0" in joined
    sw = re.search(r"-s\s+-w|-w\s+-s", joined) is not None
    execform = re.search(r"(?im)^(ENTRYPOINT|CMD)\s+\[", joined) is not None
    expose = re.search(r"(?im)^EXPOSE\s+8080\b", joined) is not None
    chk.part("static: CGO_ENABLED=0, -ldflags \"-s -w\", exec-form ENTRYPOINT, EXPOSE 8080", 1,
             (cgo + sw + execform + expose) / 4.0,
             "CGO_ENABLED=0 %s, -s -w %s, exec-form %s, EXPOSE 8080 %s" % (yes(cgo), yes(sw), yes(execform), yes(expose)))
    return chk.finish()


def check_image(image, rep):
    chk = rep.add(Check("IMG-1", "Image", "docker image %s size <= 30 MB" % image, 2, "IMAGE", "S4"))
    if shutil.which("docker") is None:
        chk.part("size", 2, False, "docker CLI not installed")
        return chk.finish("SKIP")
    rc, out, err = run_cmd(["docker", "image", "inspect", image, "--format", "{{.Size}} {{.Config.User}}"], timeout=30)
    if rc != 0:
        msg = first_line(err)
        status = "SKIP" if "daemon" in msg.lower() or "connect" in msg.lower() else None
        chk.part("size", 2, False, msg or "inspect failed")
        return chk.finish(status)
    parts = out.split()
    size = int(parts[0])
    mb = size / 1e6
    chk.part("size %.1f MB" % mb, 2, size <= 30 * 1000 * 1000, "%.1f MB > 30 MB" % mb)
    chk.note("image %s: %.1f MB, Config.User %r" % (image, mb, parts[1] if len(parts) > 1 else ""))
    return chk.finish()


# ----------------------------------------------------------------------------
# REPO-S5 compose
# ----------------------------------------------------------------------------

def compose_file(repo):
    for name in ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml"):
        if os.path.isfile(os.path.join(repo, name)):
            return name
    return None


def check_s5(repo, rep):
    chk = rep.add(Check("REPO-S5", "Repo assists", "compose: app + postgres, healthcheck, service_healthy, volume, .env", 6,
                        "ASSIST", "S5"))
    name = compose_file(repo)
    if not name:
        chk.part("compose file", 6, False, "no compose.yaml / docker-compose.yml")
        return chk.finish()
    text = strip_yaml_comments(read_text(os.path.join(repo, name)))
    lines = text.splitlines()
    top = yaml_children(lines)
    services = yaml_children(top.get("services", [""])[1:]) if "services" in top else {}
    app = next((n for n, b in services.items() if re.search(r"^\s*build\s*:", "\n".join(b), re.M)), None)
    db = next((n for n, b in services.items() if re.search(r"image:\s*[\"']?postgres", "\n".join(b))), None)
    chk.note("%s: services %s (app=%s, db=%s)" % (name, ", ".join(services) or "none", app, db))
    dbtext = "\n".join(services.get(db, [])) if db else ""
    apptext = "\n".join(services.get(app, [])) if app else ""
    pg16 = re.search(r"image:\s*[\"']?postgres:16-alpine", dbtext) is not None
    chk.part("services: app (build:) + db (postgres:16-alpine)", 1,
             (0.5 if app else 0) + (0.5 if pg16 else (0.25 if db else 0)),
             "app with build: %s, postgres service %s, tag 16-alpine %s" % (yes(bool(app)), yes(bool(db)), yes(pg16)))
    hc = re.search(r"healthcheck\s*:", dbtext) is not None and "pg_isready" in dbtext
    healthy = re.search(r"condition\s*:\s*[\"']?service_healthy", apptext) is not None and (db or "") in apptext
    chk.part("db healthcheck with pg_isready", 1, hc, "no healthcheck/pg_isready on the db service")
    chk.part("app depends_on db condition: service_healthy", 1, healthy, "no `condition: service_healthy` on app")
    vols = list(yaml_children(top.get("volumes", [""])[1:]).keys()) if "volumes" in top else []
    named = any(re.search(r"-\s*[\"']?%s:/|source:\s*[\"']?%s\b" % (re.escape(v), re.escape(v)), dbtext) for v in vols)
    chk.part("named volume for postgres data", 1, named, "top-level volumes %s; db mounts a named one: %s" % (vols, yes(named)))
    env_example = os.path.isfile(os.path.join(repo, ".env.example"))
    rc, tracked = git(repo, "ls-files", ".env")
    env_tracked = bool(tracked.strip())
    chk.part(".env.example present and .env NOT committed", 1, (0.5 if env_example else 0) + (0.5 if not env_tracked else 0),
             ".env.example %s, .env tracked %s" % (yes(env_example), "YES (secret leak)" if env_tracked else "no"))
    restart = re.search(r"restart\s*:\s*[\"']?unless-stopped", apptext) is not None
    dbports = re.search(r"^\s*ports\s*:", dbtext, re.M) is not None
    chk.part("app restart: unless-stopped + db port NOT published", 1, (0.5 if restart else 0) + (0.5 if not dbports else 0),
             "restart unless-stopped %s, db publishes ports %s" % (yes(restart), "YES" if dbports else "no"))
    return chk.finish()


# ----------------------------------------------------------------------------
# REPO-S6 CI
# ----------------------------------------------------------------------------

def gofmt_fails_build(text):
    """a workflow step that runs `gofmt -l` AND fails when it lists files, e.g.
    test -z "$(gofmt -l .)", [ -n "$(gofmt -l .)" ] && exit 1, if ...; then exit 1; fi."""
    steps = re.split(r"(?m)^\s*-\s+(?=(?:name|uses|run|id|if|with|env|shell|working-directory)\s*:)", text)
    fail = re.compile(r"test\s+-z|\[\[?\s+-z|exit\s+1|\|\|\s*exit|&&\s*exit|\|\s*grep\s+-q?\s*\.\s*&&")
    for step in steps:
        if re.search(r"gofmt\s+(-[a-z]+\s+)*-l", step) and fail.search(step):
            return True
    return False


def check_s6(repo, rep):
    chk = rep.add(Check("REPO-S6", "Repo assists", "CI workflow: triggers, test job, build job (needs:), PR merge", 5,
                        "ASSIST", "S6"))
    wdir = os.path.join(repo, ".github", "workflows")
    files = sorted(f for f in (os.listdir(wdir) if os.path.isdir(wdir) else []) if f.endswith((".yml", ".yaml")))
    if not files:
        chk.part("workflow", 4, False, "no .github/workflows/*.yml")
    else:
        text = strip_yaml_comments("\n".join(read_text(os.path.join(wdir, f)) for f in files))
        chk.note("workflow file(s): %s" % ", ".join(files))
        push = re.search(r"^\s*push\s*:", text, re.M) is not None or re.search(r"on\s*:\s*\[[^\]]*push", text) is not None
        push_main = push and re.search(r"branches\s*:\s*(\[[^\]]*\bmain\b|\s*\n\s*-\s*[\"']?main)", text) is not None
        pr = re.search(r"\bpull_request\b", text) is not None
        chk.part("triggers: push to main + pull_request", 1, (0.5 if push_main else (0.25 if push else 0)) + (0.5 if pr else 0),
                 "push %s (to main %s), pull_request %s" % (yes(push), yes(push_main), yes(pr)))
        checkout = "actions/checkout" in text
        setup = "actions/setup-go" in text
        gvf = "go-version-file" in text
        gofmt = gofmt_fails_build(text)
        vet = "go vet" in text
        race = re.search(r"go test[^\n]*-race", text) is not None
        score = (checkout + setup + gofmt + vet + race) / 5.0
        chk.part("test job: checkout, setup-go, gofmt check that fails, go vet, go test -race", 2, score,
                 "checkout %s, setup-go %s (go-version-file %s), failing gofmt %s, vet %s, -race %s"
                 % (yes(checkout), yes(setup), yes(gvf), yes(gofmt), yes(vet), yes(race)))
        build = "docker build" in text or "docker/build-push-action" in text
        needs = re.search(r"^\s*needs\s*:", text, re.M) is not None
        chk.part("build job: docker build with needs:", 1, (0.5 if build else 0) + (0.5 if needs else 0),
                 "docker build %s, needs: %s" % (yes(build), yes(needs)))
    readme = read_text(os.path.join(repo, "README.md"))
    if re.search(r"actions/workflows/[^)\s]+/badge\.svg|badge\.svg", readme):
        chk.note("CI badge found in README (green latest run on main: confirm on GitHub — MANUAL 1 pt)")
    else:
        chk.note("no CI badge in README (MANUAL item: latest run green + badge)")
    rc, out = git(repo, "log", "--all", "--merges", "--format=%s")
    prs = [l for l in out.splitlines() if re.match(r"Merge pull request #\d+", l)]
    chk.part(">= 1 stage merged through a GitHub Pull Request", 1, bool(prs),
             "no 'Merge pull request #N' commit (squash/rebase merges cannot be seen locally: confirm on GitHub)")
    if prs:
        chk.note("PR merges: %s (confirm the CI check is shown on GitHub)" % "; ".join(prs[:3]))
    return chk.finish()


# ----------------------------------------------------------------------------
# REPO-S7 k8s manifests (static) and K8S-* live checks
# ----------------------------------------------------------------------------

S7_ITEMS = [("ns", 1, "Namespace + apply order"), ("cfg", 2, "ConfigMap + Secret consumed"),
            ("db", 2, "postgres workload + ClusterIP Service + PVC/emptyDir"),
            ("app", 2, "app: replicas 2, requests+limits, pinned tag, IfNotPresent"),
            ("probes", 2, "liveness /healthz + readiness /readyz"), ("svc", 1, "app Service :80 -> 8080")]


def k8s_docs(repo):
    kdir = os.path.join(repo, "k8s")
    docs = []
    if not os.path.isdir(kdir):
        return docs, []
    files = sorted(f for f in os.listdir(kdir) if f.endswith((".yaml", ".yml")))
    for f in files:
        for raw in re.split(r"(?m)^---\s*$", read_text(os.path.join(kdir, f))):
            text = strip_yaml_comments(raw)
            km = re.search(r"(?m)^kind:\s*[\"']?(\w+)", text)
            if not km:
                continue
            lines = text.splitlines()
            mi = find_key(lines, "metadata")
            name = None
            if mi is not None:
                nm = re.search(r"(?m)^\s+name:\s*[\"']?([^\s\"']+)", "\n".join(yaml_block(lines, mi)))
                name = nm.group(1) if nm else None
            docs.append({"file": f, "kind": km.group(1), "name": name, "text": text, "lines": lines})
    return docs, files


def probe_path(lines, key):
    i = find_key(lines, key)
    if i is None:
        return None
    m = re.search(r"path:\s*[\"']?([^\s\"']+)", "\n".join(yaml_block(lines, i)))
    return m.group(1) if m else "(no httpGet path)"


def images_of(text):
    return re.findall(r"(?m)^\s*-?\s*image:\s*[\"']?([^\s\"']+)", text)


def pinned(image):
    if "@sha256:" in image:
        return True
    last = image.rsplit("/", 1)[-1]
    return ":" in last and not last.endswith(":latest")


def check_s7_static(repo, rep):
    chk = rep.add(Check("REPO-S7", "Repo assists", "k8s/ manifests (static)", 10, "ASSIST", "S7"))
    docs, files = k8s_docs(repo)
    if not docs:
        chk.part("k8s/", 10, False, "no k8s/*.yaml manifests")
        for key, pts, _ in S7_ITEMS:
            chk.items[key] = 0.0
        return chk.finish()
    chk.note("files: %s; kinds: %s" % (", ".join(files), ", ".join("%s/%s" % (d["kind"], d["name"]) for d in docs)))
    kinds = lambda k: [d for d in docs if d["kind"] == k]
    ns = [d for d in kinds("Namespace") if d["name"] == "minibank"]
    first_ok = bool(ns) and ns[0]["file"] == files[0]
    chk.part("Namespace minibank, applied first (00- prefix)", 1, (0.5 if ns else 0) + (0.5 if first_ok else 0),
                 "Namespace minibank %s, its file sorts first %s" % (yes(bool(ns)), yes(first_ok)))
    chk.items["ns"] = chk.parts[-1][1]
    deps = kinds("Deployment") + kinds("StatefulSet")
    dbw = [d for d in deps if any("postgres" in i for i in images_of(d["text"]))]
    appw = [d for d in kinds("Deployment") if d not in dbw and images_of(d["text"])]
    app = next((d for d in appw if "minibank" in (d["name"] or "")), appw[0] if appw else None)
    apptext = app["text"] if app else ""
    cm, sec = bool(kinds("ConfigMap")), bool(kinds("Secret"))
    cm_used = re.search(r"configMapRef|configMapKeyRef", apptext) is not None
    sec_used = re.search(r"secretKeyRef|secretRef", apptext) is not None
    chk.part("ConfigMap + Secret, consumed by the app (envFrom / secretKeyRef)", 2,
             (cm * 0.25 + sec * 0.25 + cm_used * 0.25 + sec_used * 0.25),
             "ConfigMap %s, Secret %s, app uses ConfigMap %s, app uses Secret %s"
             % (yes(cm), yes(sec), yes(cm_used), yes(sec_used)))
    chk.items["cfg"] = chk.parts[-1][1]
    dbsvc = [d for d in kinds("Service") if re.search(r"port:\s*5432", d["text"])]
    dbsvc_ci = bool(dbsvc) and not re.search(r"type:\s*(NodePort|LoadBalancer)", dbsvc[0]["text"])
    storage = bool(kinds("PersistentVolumeClaim")) or any("emptyDir" in d["text"] or "volumeClaimTemplates" in d["text"]
                                                         or "persistentVolumeClaim" in d["text"] for d in dbw)
    chk.part("postgres Deployment/StatefulSet + ClusterIP Service + PVC or emptyDir", 2,
             (0.5 if dbw else 0) + (0.25 if dbsvc_ci else 0) + (0.25 if storage else 0),
             "postgres workload %s, ClusterIP :5432 Service %s, PVC/emptyDir %s" % (yes(bool(dbw)), yes(dbsvc_ci), yes(storage)))
    chk.items["db"] = chk.parts[-1][1]
    if app:
        rm = re.search(r"(?m)^\s*replicas:\s*(\d+)", apptext)
        reps = int(rm.group(1)) if rm else None
        lines = app["lines"]
        ri = find_key(lines, "resources")
        rb = "\n".join(yaml_block(lines, ri)) if ri is not None else ""
        res = "requests:" in rb and "limits:" in rb
        imgs = [i for i in images_of(apptext)]
        pin = bool(imgs) and all(pinned(i) for i in imgs)
        ifnp = re.search(r"imagePullPolicy:\s*[\"']?IfNotPresent", apptext) is not None
        chk.part("app Deployment: replicas 2, requests+limits, pinned tag, IfNotPresent", 2,
                 ((reps == 2) + res + pin + ifnp) / 4.0,
                 "replicas %s, requests+limits %s, images %s pinned %s, IfNotPresent %s"
                 % (reps, yes(res), imgs, yes(pin), yes(ifnp)))
        chk.items["app"] = chk.parts[-1][1]
        lp, rp = probe_path(lines, "livenessProbe"), probe_path(lines, "readinessProbe")
        chk.part("livenessProbe /healthz + readinessProbe /readyz", 2, (lp == "/healthz") * 0.5 + (rp == "/readyz") * 0.5,
                 "liveness %s, readiness %s" % (lp, rp))
        chk.items["probes"] = chk.parts[-1][1]
    else:
        chk.part("app Deployment", 2, False, "no non-postgres Deployment found")
        chk.part("probes", 2, False, "no app Deployment")
        chk.items["app"] = chk.items["probes"] = 0.0
    appsvc = [d for d in kinds("Service") if re.search(r"(?m)^\s*-?\s*port:\s*80\s*$", d["text"])]
    tp = re.search(r"targetPort:\s*[\"']?(\w+)", appsvc[0]["text"]) if appsvc else None
    svc_ok = bool(appsvc) and (tp is None or tp.group(1) in ("8080", "http"))
    chk.part("app Service port 80 -> 8080 (smoke via port-forward: confirm)", 1, svc_ok,
             "Service with port 80 %s, targetPort %s" % (yes(bool(appsvc)), tp.group(1) if tp else "-"))
    chk.items["svc"] = chk.parts[-1][1]
    chk.max = 10
    ing = [d for d in kinds("Ingress") if "minibank.local" in d["text"]]
    if ing:
        chk.note("bonus B2 hint: Ingress for minibank.local in %s (verify live with --namespace)" % ing[0]["file"])
    chart = os.path.join(repo, "charts", "minibank")
    if os.path.isfile(os.path.join(chart, "Chart.yaml")):
        vals = read_text(os.path.join(chart, "values.yaml"))
        tdir = os.path.join(chart, "templates")
        tnames = " ".join(os.listdir(tdir)) if os.path.isdir(tdir) else ""
        want = [w for w in ("deployment", "service", "configmap", "secret") if w in tnames.lower()]
        chk.note("bonus B3 hint: chart charts/minibank (values: tag %s, replicaCount %s, resources %s; templates: %s)"
                 % (yes("tag:" in vals), yes("replicaCount" in vals), yes("resources" in vals), ", ".join(want)))
    return chk.finish()


def kubectl_json(ns, kinds):
    rc, out, err = run_cmd(["kubectl", "--request-timeout=10s", "-n", ns, "get", kinds, "-o", "json"], timeout=30)
    if rc is None:
        return None, "kubectl not installed"
    if rc != 0:
        return None, first_line(err) or "kubectl failed (exit %s)" % rc
    try:
        return json.loads(out).get("items", []), None
    except ValueError:
        return None, "kubectl returned invalid JSON"


def deployed_store(containers, configmaps, secrets):
    """STORE value seen by the app containers: env value / configMapKeyRef / secretKeyRef,
    then envFrom configMapRef / secretRef. Returns (value or None, source)."""
    import base64
    cms = {c["metadata"]["name"]: (c.get("data") or {}) for c in configmaps}
    secs = {}
    for s_ in secrets:
        data = {}
        for k, v in (s_.get("data") or {}).items():
            try:
                data[k] = base64.b64decode(v).decode("utf-8", "replace")
            except Exception:
                pass
        data.update(s_.get("stringData") or {})
        secs[s_["metadata"]["name"]] = data
    for c in containers:
        for e in c.get("env") or []:
            if e.get("name") != "STORE":
                continue
            if "value" in e:
                return e["value"], "env value"
            vf = e.get("valueFrom") or {}
            if "configMapKeyRef" in vf:
                ref = vf["configMapKeyRef"]
                return cms.get(ref.get("name"), {}).get(ref.get("key")), "configmap/%s" % ref.get("name")
            if "secretKeyRef" in vf:
                ref = vf["secretKeyRef"]
                return secs.get(ref.get("name"), {}).get(ref.get("key")), "secret/%s" % ref.get("name")
        for ef in c.get("envFrom") or []:
            if "configMapRef" in ef and "STORE" in cms.get(ef["configMapRef"].get("name"), {}):
                return cms[ef["configMapRef"]["name"]]["STORE"], "configmap/%s" % ef["configMapRef"]["name"]
            if "secretRef" in ef and "STORE" in secs.get(ef["secretRef"].get("name"), {}):
                return secs[ef["secretRef"]["name"]]["STORE"], "secret/%s" % ef["secretRef"]["name"]
    return None, "-"


def check_live(ns, rep, skip_bonus):
    sec = "Kubernetes (live)"
    items, err = kubectl_json(ns, "deploy,sts,svc,cm,secret,ingress,pvc")
    live = {}
    if items is None:
        chk = rep.add(Check("K8S-0", sec, "kubectl -n %s get ..." % ns, 0, "LIVE", "S7"))
        chk.note("skipped: %s" % err)
        chk.finish("SKIP")
        return live
    by = lambda kind: [i for i in items if i.get("kind") == kind]

    def containers(obj):
        return obj.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []) or []

    workloads = by("Deployment") + by("StatefulSet")
    dbw = [w for w in workloads if any("postgres" in c.get("image", "") for c in containers(w))]
    appw = [w for w in by("Deployment") if w not in dbw]
    app = next((w for w in appw if "minibank" in w["metadata"]["name"]), appw[0] if appw else None)

    chk = rep.add(Check("K8S-NS", sec, "namespace %s has objects (kubectl apply worked)" % ns, 1, "LIVE", "S7"))
    chk.part("objects", 1, bool(items), "namespace empty or missing")
    chk.note("%d object(s): %s" % (len(items), ", ".join(sorted(set(i.get("kind", "?") for i in items)))))
    live["ns"] = chk.finish().earned

    chk = rep.add(Check("K8S-APP", sec, "app Deployment: replicas 2 ready, resources, pinned tag, IfNotPresent", 2, "LIVE", "S7"))
    if not app:
        chk.part("app Deployment", 2, False, "no non-postgres Deployment in %s" % ns)
    else:
        spec_rep = app.get("spec", {}).get("replicas")
        ready = app.get("status", {}).get("readyReplicas", 0) or 0
        cs = containers(app)
        res = all(c.get("resources", {}).get("requests") and c.get("resources", {}).get("limits") for c in cs) and bool(cs)
        imgs = [c.get("image", "") for c in cs]
        pin = bool(imgs) and all(pinned(i) for i in imgs)
        ifnp = all(c.get("imagePullPolicy") == "IfNotPresent" for c in cs) and bool(cs)
        chk.part("replicas 2 and readyReplicas >= 2", 0.5, spec_rep == 2 and ready >= 2,
                 "spec.replicas %s, readyReplicas %s" % (spec_rep, ready))
        chk.part("requests + limits", 0.5, res, "resources missing on a container")
        chk.part("pinned image tag", 0.5, pin, "images %s" % imgs)
        chk.part("imagePullPolicy IfNotPresent", 0.5, ifnp, "%s" % [c.get("imagePullPolicy") for c in cs])
        chk.note("deployment/%s: %s/%s ready, image %s" % (app["metadata"]["name"], ready, spec_rep, ", ".join(imgs)))
    live["app"] = chk.finish().earned

    chk = rep.add(Check("K8S-PROBES", sec, "livenessProbe /healthz + readinessProbe /readyz", 2, "LIVE", "S7"))
    cs = containers(app) if app else []
    lp = [((c.get("livenessProbe") or {}).get("httpGet") or {}).get("path") for c in cs]
    rp = [((c.get("readinessProbe") or {}).get("httpGet") or {}).get("path") for c in cs]
    chk.part("liveness /healthz", 1, "/healthz" in lp, "liveness paths %s" % lp)
    chk.part("readiness /readyz", 1, "/readyz" in rp, "readiness paths %s" % rp)
    live["probes"] = chk.finish().earned

    chk = rep.add(Check("K8S-DB", sec, "postgres ready + ClusterIP Service + PVC/emptyDir", 2, "LIVE", "S7"))
    if dbw:
        w = dbw[0]
        ready = w.get("status", {}).get("readyReplicas", 0) or 0
        chk.part("postgres %s/%s ready" % (w["kind"], w["metadata"]["name"]), 1, ready >= 1, "readyReplicas %s" % ready)
        vols = w.get("spec", {}).get("template", {}).get("spec", {}).get("volumes", []) or []
        storage = bool(by("PersistentVolumeClaim")) or any("emptyDir" in v or "persistentVolumeClaim" in v for v in vols) \
            or bool(w.get("spec", {}).get("volumeClaimTemplates"))
        chk.part("PVC or emptyDir", 0.5, storage, "no volume for the data directory")
    else:
        chk.part("postgres workload", 1.5, False, "no Deployment/StatefulSet with a postgres image")
    svc5432 = [s for s in by("Service") if any(p.get("port") == 5432 for p in s.get("spec", {}).get("ports", []))]
    chk.part("ClusterIP Service :5432", 0.5, bool(svc5432) and svc5432[0]["spec"].get("type", "ClusterIP") == "ClusterIP",
             "no ClusterIP service on 5432")
    live["db"] = chk.finish().earned

    chk = rep.add(Check("K8S-CFG", sec, "ConfigMap + Secret exist and are used by the app", 2, "LIVE", "S7"))
    cms = [c for c in by("ConfigMap") if c["metadata"]["name"] != "kube-root-ca.crt"]
    secs = [s for s in by("Secret") if s.get("type") in ("Opaque", None)]
    refs = json.dumps([{k: c.get(k) for k in ("env", "envFrom")} for c in cs])
    chk.part("ConfigMap", 0.5, bool(cms), "no ConfigMap (besides kube-root-ca.crt)")
    chk.part("Secret (Opaque)", 0.5, bool(secs), "no Opaque Secret")
    chk.part("app uses ConfigMap", 0.5, "configMapRef" in refs or "configMapKeyRef" in refs, "no configMapRef/KeyRef in app env")
    chk.part("app uses Secret", 0.5, "secretKeyRef" in refs or "secretRef" in refs, "no secretKeyRef/secretRef in app env")
    live["cfg"] = chk.finish().earned

    # K8S-STORE (0 pts): which datastore does the deployed app really use?
    chk = rep.add(Check("K8S-STORE", sec, "STORE of the app Deployment (0 pts; memory => storms do not count)", 0, "LIVE", "S7"))
    store_val, src = deployed_store(cs, by("ConfigMap"), by("Secret"))
    if store_val is None:
        chk.note("STORE not set in the app Deployment (contract default: postgres)")
        chk.finish("OK")
    elif store_val.strip().lower() == "memory":
        chk.note("!! STORE=memory (from %s): CON-1/CON-2/BON-B4 must be set to 0: app is not using PostgreSQL" % src)
        chk.finish("WARN")
        live["_store_memory"] = src
    else:
        chk.note("STORE=%s (from %s)" % (store_val, src))
        chk.finish("OK")

    chk = rep.add(Check("K8S-SVC", sec, "app Service port 80 (port-forward + smoke: confirm)", 1, "LIVE", "S7"))
    appsvc = [s for s in by("Service") if any(p.get("port") == 80 for p in s.get("spec", {}).get("ports", []))]
    ready_app = app and (app.get("status", {}).get("readyReplicas", 0) or 0) >= 2
    chk.part("Service :80 with ready app pods", 1, (0.5 if appsvc else 0) + (0.5 if appsvc and ready_app else 0),
             "Service :80 %s, app ready %s" % (yes(bool(appsvc)), yes(bool(ready_app))))
    if appsvc:
        chk.note("kubectl -n %s port-forward svc/%s 8080:80 && scripts/smoke.sh" % (ns, appsvc[0]["metadata"]["name"]))
    live["svc"] = chk.finish().earned

    if skip_bonus:
        return live
    chk = rep.add(Check("BON-B2", "Bonus (assist)", "Ingress host minibank.local -> app Service (live object; curl is MANUAL)", 3,
                        "LIVE", "B2"))
    app_svcs = set(s["metadata"]["name"] for s in appsvc)
    ing_ok, ing_note = False, "no Ingress with host minibank.local in %s" % ns
    for i in by("Ingress"):
        for rule in i.get("spec", {}).get("rules", []) or []:
            if rule.get("host") != "minibank.local":
                continue
            backends = [((p.get("backend") or {}).get("service") or {}).get("name")
                        for p in ((rule.get("http") or {}).get("paths") or [])]
            cls = i["spec"].get("ingressClassName") or i["metadata"].get("annotations", {}).get("kubernetes.io/ingress.class")
            if any(b in app_svcs for b in backends):
                ing_ok = True
                ing_note = "ingress/%s (class %s) -> service %s" % (i["metadata"]["name"], cls, ", ".join(b for b in backends if b))
            else:
                ing_note = "ingress/%s host minibank.local points to %s, not the app Service %s" % (
                    i["metadata"]["name"], backends, sorted(app_svcs))
    chk.part("Ingress object minibank.local -> app Service (1 of 3; the other 2 = curl through the controller, MANUAL)",
             3, 1.0 / 3 if ing_ok else 0, ing_note)
    if ing_ok:
        chk.note(ing_note)
    chk.finish()

    chk = rep.add(Check("BON-B3", "Bonus (assist)", "Helm release of the minibank chart deployed (live)", 4, "LIVE", "B3"))
    if shutil.which("helm") is None:
        chk.part("helm list", 4, False, "helm not installed on this machine")
        chk.finish("SKIP")
    else:
        rc, out, err = run_cmd(["helm", "list", "-A", "-o", "json"], timeout=30)  # chart may live in minibank-helm
        try:
            rels = json.loads(out) if rc == 0 else []
        except ValueError:
            rels = []
        mine = [r for r in rels if str(r.get("chart", "")).startswith("minibank") and r.get("status") == "deployed"]
        chk.part("deployed release (any namespace)", 4, bool(mine),
                 "no deployed release of chart minibank-* in any namespace (%s)" % (first_line(err) or "helm list -A empty"))
        for r in mine[:3]:
            chk.note("release %s in namespace %s: chart %s rev %s, status %s"
                     % (r.get("name"), r.get("namespace"), r.get("chart"), r.get("revision"), r.get("status")))
        chk.finish()
    return live


# ----------------------------------------------------------------------------
# REPO-S8 docs + history
# ----------------------------------------------------------------------------

CONVENTIONAL = re.compile(r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([^)]*\))?!?:\s*\S")


def section_after_heading(text, pred):
    lines = list(md_lines_outside_code(text))
    for i, (line, code) in enumerate(lines):
        m = HEADING.match(line) if not code else None
        if m and pred(norm_fa(m.group(2))):
            level = len(m.group(1))
            body = []
            for l2, c2 in lines[i + 1:]:
                m2 = HEADING.match(l2) if not c2 else None
                if m2 and len(m2.group(1)) <= level:
                    break
                body.append(l2)
            return m.group(2), "\n".join(body)
    return None, ""


def check_s8(repo, rep):
    chk = rep.add(Check("REPO-S8", "Repo assists", "README (run, diagram, env), AI usage section, git history", 3,
                        "ASSIST", "S8"))
    readme = read_text(os.path.join(repo, "README.md"))
    if not readme:
        chk.part("README", 2, False, "README.md missing")
    else:
        mem = re.search(r"STORE=memory|go run", readme) is not None
        comp = re.search(r"docker compose|docker-compose", readme) is not None
        k8s = re.search(r"kubectl apply|kind load|minikube image load|port-forward", readme) is not None
        diagram = re.search(r"```mermaid|[┌└│─►▶→]|-->|\+--|\|\s*\n\s*v\b", readme) is not None
        envtab = re.search(r"\|\s*`?(PORT|STORE|DATABASE_URL)`?\s*\|", readme) is not None
        chk.part("README: run memory / compose / k8s, architecture diagram, env table", 1,
                 (mem + comp + k8s) / 6.0 + diagram * 0.25 + envtab * 0.25,
                 "run: memory %s, compose %s, k8s %s; diagram %s; env table %s"
                 % (yes(mem), yes(comp), yes(k8s), yes(diagram), yes(envtab)))
        title, body = section_after_heading(
            readme, lambda h: re.search(r"(?i)(^|[^A-Za-z])AI([^A-Za-z]|$)", h) is not None or "هوش مصنوعی" in h)
        words = len(re.findall(r"\w+", body, re.UNICODE))
        wrong = re.search(r"(?i)wrong|mistake|incorrect|bug|fixed|caught|اشتباه|غلط|خطا|درست کرد", body) is not None
        chk.part("\"AI usage\" section (tools, used for, >= 1 AI mistake fixed)", 1,
                 0 if not title else (1.0 if words >= 40 and wrong else 0.5),
                 "no heading containing AI / هوش مصنوعی" if not title else
                 "section %r: %d words, mentions a mistake/fix %s" % (title, words, yes(wrong)))
        if title:
            chk.note("AI section %r: %d words — quality is MANUAL" % (title, words))
    main = main_branch(repo)
    if not main:
        chk.part("git history", 1, False, "not a git repository")
        return chk.finish()
    rc, out = git(repo, "log", main, "--no-merges", "--format=%ct%x09%s")
    commits = [l.split("\t", 1) for l in out.splitlines() if "\t" in l]
    n = len(commits)
    conv = sum(1 for _, s in commits if CONVENTIONAL.match(s))
    ratio = conv / float(n) if n else 0
    rc, allt = git(repo, "log", main, "--format=%ct")
    times = [int(t) for t in allt.split() if t.isdigit()]
    span = (max(times) - min(times)) / 60.0 if times else 0
    secrets, binaries = scan_secrets_binaries(repo)
    clean = not secrets and not binaries
    chk.part("history: >= 10 commits, conventional, spread over the exam, no secrets/binaries", 1,
             (n >= 10) * 0.25 + (ratio >= 0.7) * 0.25 + (span >= 90) * 0.25 + clean * 0.25,
             "%d non-merge commits, %.0f%% conventional, span %.0f min (want >= 90), secrets %s, binaries %s"
             % (n, ratio * 100, span, secrets[:3] or "none", binaries[:3] or "none"))
    chk.note("history: %d commits, %d%% conventional, first->last %.0f min%s"
             % (n, ratio * 100, span, " (more than 4 h: commits outside the exam window?)" if span > 240 else ""))
    return chk.finish()


def scan_secrets_binaries(repo):
    secrets = []
    pw = re.compile(r"(?i)\b(password|passwd|pwd|secret)\b\s*[:=]+\s*\"[^\"\s]{3,}\"")
    dsn = re.compile(r"postgres(?:ql)?://[^:\s\"/@]+:[^@\s\"]+@")
    for path in walk_files(repo, [".go"]):
        if path.endswith("_test.go"):
            continue
        for n, line in enumerate(read_text(path).splitlines(), 1):
            if pw.search(line) or dsn.search(line):
                secrets.append("%s:%d" % (os.path.relpath(path, repo), n))
    binaries = []
    rc, out = git(repo, "ls-files", "-z")
    for rel in out.split("\0"):
        if not rel:
            continue
        p = os.path.join(repo, rel)
        base = os.path.basename(rel)
        if base == ".env" or base.endswith((".exe", ".test", ".out")):
            binaries.append(rel)
            continue
        try:
            if os.path.getsize(p) > 1000000:
                with open(p, "rb") as f:
                    head = f.read(4)
                if head in (b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe") or head[:2] == b"MZ":
                    binaries.append(rel)
        except OSError:
            pass
    return secrets, binaries


# ----------------------------------------------------------------------------
# report
# ----------------------------------------------------------------------------

STAGES = [("S0", 5, "Kickoff"), ("S1", 25, "Go app"), ("S2", 8, "Tests"), ("S3", 7, "Linux & Bash"),
          ("S4", 9, "Docker"), ("S5", 7, "Compose"), ("S6", 6, "CI"), ("S7", 10, "Kubernetes"), ("S8", 3, "Docs & history")]


def print_report(rep, st, args, run_id, reachable, live_items):
    w = sys.stdout.write
    color = {"PASS": st.green, "FAIL": st.red, "PARTIAL": st.yellow, "ASSIST": st.cyan, "SKIP": st.grey, "INFO": st.blue,
             "OK": st.green, "WARN": st.red}
    w("\n" + st.bold("MiniBank auto-grader %s" % GRADER_VERSION) + "  url=%s  run=%s  %s\n"
      % (args.url, run_id, datetime.datetime.now().strftime("%Y-%m-%d %H:%M")))
    sections = []
    for c in rep.checks:
        if c.section not in sections:
            sections.append(c.section)
    for sec in sections:
        rows = rep.by_section(sec)
        tot = sum(c.earned for c in rows if c.kind == "AUTO")
        mx = sum(c.max for c in rows if c.kind == "AUTO")
        head = "\n== %s" % sec
        if mx:
            head += "  (%s / %s)" % (fmt_pts(round_q(tot, 0.01)), fmt_pts(mx))
        elif any(c.kind in ("ASSIST", "LIVE", "IMAGE") for c in rows):
            head += "  (assist - confirm by eye)"
        w(st.bold(head) + "\n")
        for c in rows:
            pts = "" if c.kind == "INFO" or (c.max == 0) else "%5s/%-4s" % (fmt_pts(c.earned), fmt_pts(c.max))
            label = c.status
            w("  %-10s %-74s %10s  %s\n" % (c.cid, c.title[:74], pts, color.get(label, str)(label)))
            show = c.notes  # on PASS rows only informative hints (e.g. unusual status codes)
            for n in show:
                w("             - %s\n" % n)
    totals = compute_totals(rep, args, reachable, live_items)
    w(st.bold("\n== Summary\n"))
    a = totals["auto"]
    w("  AUTO (certain):       API %s/8 + CON %s/3 = %s / 11 core    bonus B1 %s/4 + B4 %s/4 = %s / 8\n"
      % (fmt_pts(a["api"]), fmt_pts(a["con"]), st.bold(fmt_pts(a["core"])), fmt_pts(a["b1"]), fmt_pts(a["b4"]),
         st.bold(fmt_pts(a["bonus"]))))
    w("  SUGGESTED (assist - confirm by eye):\n")
    for s in totals["stages"]:
        if s["stage"] == "S1":
            line = "    %-3s %-15s auto %s/11 + manual 14 (see MANUAL)" % (s["stage"], s["name"], fmt_pts(a["core"]))
        elif s["suggested"] is None:
            line = "    %-3s %-15s not checked (no --repo/--namespace)          stage max %s" % (s["stage"], s["name"], s["max"])
        else:
            line = "    %-3s %-15s %5s / %-4s assistable   (stage max %s%s)" % (
                s["stage"], s["name"], fmt_pts(s["suggested"]), fmt_pts(s["assist_max"]), s["max"],
                ", %s manual" % fmt_pts(s["max"] - s["assist_max"]) if s["max"] - s["assist_max"] > 0 else "")
            if s.get("how"):
                line += "  " + s["how"]
        w(line + "\n")
    for b in totals["bonus_assist"]:
        w("    %-3s %-15s %5s / %-4s %s\n" % (b["id"], b["name"], fmt_pts(b["suggested"]), fmt_pts(b["max"]), b["how"]))
    w("  => AUTO %s + SUGGESTED %s = %s / 80 build points before manual items; bonus so far %s / 15\n"
      % (fmt_pts(a["core"]), fmt_pts(totals["suggested_total"]), st.bold(fmt_pts(totals["provisional"])),
         fmt_pts(totals["bonus_total"])))
    w(st.bold("\n== MANUAL (instructor judges; [max points], [--] = confirm a suggestion, no extra points)\n"))
    for m in totals["manual"]:
        w("  [%2s] %s\n" % (fmt_pts(m["max"]) if m["max"] else "--", m["item"]))
    w("  MANUAL total: up to %s more points (build + defense + unverified bonus)\n"
      % fmt_pts(sum(m["max"] for m in totals["manual"])))
    if live_items.get("_store_memory"):
        w(st.red("\n  !! K8S-STORE: the deployed app uses STORE=memory (%s). If --url is this deployment,\n"
                 "  !! CON-1/CON-2/BON-B4 must be set to 0: app is not using PostgreSQL.\n" % live_items["_store_memory"]))
    if not reachable:
        w(st.red("\n  SERVER UNREACHABLE at %s: API/CON/bonus checks are 0. Start it and re-run.\n" % args.url))
    elif totals.get("died"):
        w(st.red("\n  WARNING: the server stopped answering during the run (crash? OOM? panic?) — check its logs.\n"))
    w(st.bold("\n== How to read this report\n"))
    w("  * AUTO points come from black-box HTTP checks and are certain: copy them as they are.\n"
      "  * ASSIST/LIVE/IMAGE points are suggestions from static heuristics, kubectl and docker: open the\n"
      "    repo/cluster and confirm each one (the '-' lines say why). Do not award blindly.\n"
      "  * MANUAL items cannot be measured by a script; their max points are listed above.\n"
      "  * Every FAIL line states expected vs got, so it can be read to the student as feedback.\n"
      "  * Re-running is safe: the grader only creates new accounts with random owner names.\n")
    return totals


def compute_totals(rep, args, reachable, live_items):
    g = lambda cid: rep.get(cid).earned if rep.get(cid) else 0.0
    api = round_q(sum(c.earned for c in rep.checks if c.cid.startswith("API-")), 0.01)
    con = round_q(sum(c.earned for c in rep.checks if c.cid.startswith("CON-")), 0.01)
    auto = {"api": api, "con": con, "core": round_q(api + con, 0.01), "b1": g("BON-B1"), "b4": g("BON-B4")}
    auto["bonus"] = round_q(auto["b1"] + auto["b4"], 0.01)
    stages = []
    suggested_total = 0.0
    for sid, smax, name in STAGES:
        entry = {"stage": sid, "name": name, "max": smax, "suggested": None, "assist_max": 0, "how": ""}
        if sid == "S1":
            stages.append(entry)
            continue
        rows = [c for c in rep.checks if c.stage == sid and c.kind in ("ASSIST", "IMAGE") and c.max > 0
                and c.status != "SKIP"]
        if sid == "S7":
            static = rep.get("REPO-S7")
            if static or live_items:
                merged = 0.0
                for key, pts, _ in S7_ITEMS:
                    merged += max(static.items.get(key, 0.0) if static else 0.0, live_items.get(key, 0.0))
                entry["suggested"] = round_q(merged, 0.01)
                entry["assist_max"] = 10
                entry["how"] = "(per item best of static REPO-S7 and live K8S-*)"
        elif rows:
            entry["suggested"] = round_q(sum(c.earned for c in rows), 0.01)
            entry["assist_max"] = sum(c.max for c in rows)
            if sid == "S4" and not rep.get("IMG-1"):
                entry["how"] = "(+2 image size needs --image)"
        if entry["suggested"] is not None:
            suggested_total += entry["suggested"]
        stages.append(entry)
    bonus_assist = []
    for bid, name, mx in (("B2", "Ingress", 3), ("B3", "Helm", 4)):
        c = rep.get("BON-" + bid)
        if c and c.status != "SKIP":
            bonus_assist.append({"id": bid, "name": name, "suggested": c.earned, "max": mx, "how": "(live, confirm)"})
    manual = [
        {"item": "S0 confirm REPO-S0: 'My decisions' specific & realistic, committed before 0:15", "max": 0}
        if rep.get("REPO-S0") else
        {"item": "S0 kickoff: 'My decisions' (2), go.mod/.gitignore (1), >= 4 stage merges (2) — or re-run with --repo", "max": 5},
        {"item": "S1 domain & validation: int64 money, rune owner check, amount range, sentinel errors + errors.Is, ONE error->status function", "max": 3},
        {"item": "S1 Store interface + memory (mutex) + postgres implementations, selected by STORE", "max": 4},
        {"item": "S1 Postgres correctness: CREATE TABLE IF NOT EXISTS + CHECK, only $n params, transfer in ONE tx, no read-check-write", "max": 3},
        {"item": "S1 config from env with defaults, fail fast with a clear log line", "max": 1},
        {"item": "S1 /healthz never touches DB; /readyz pings with <= 2 s timeout -> 503 (stop the DB and curl)", "max": 1},
        {"item": "S1 middleware: slog JSON line per request (method, path, status, duration_ms) + panic recovery -> 500 JSON", "max": 1},
        {"item": "S1 graceful shutdown: SIGTERM -> Shutdown(timeout <= 10 s), store closed, logged", "max": 1},
        {"item": "S4 `docker build -t minibank:v1 .` + `docker run -e STORE=memory -p 8080:8080` -> /healthz 200", "max": 1},
        {"item": "S5 smoke.sh green against `docker compose up -d --build` from a clean clone (+ data survives down/up)", "max": 1},
        {"item": "S6 latest CI run on main is green + badge in README (GitHub)", "max": 1},
        {"item": "S7 confirm: `kubectl apply -f k8s/` on a fresh cluster + port-forward -> smoke.sh green", "max": 0},
        {"item": "S8 confirm REPO-S8: README is accurate, AI note is honest and names a real AI mistake", "max": 0},
        {"item": "D1 request journey  D2 why-question  D3 debug the broken deployment  D4 live change (5 each, NO AI)", "max": 20},
    ]
    s6 = rep.get("REPO-S6")
    if not s6 or not any(l.startswith(">= 1 stage merged") and f >= 1 for (l, e, m, f, r) in s6.parts):
        manual.insert(11, {"item": "S6 >= 1 stage merged through a GitHub Pull Request showing the CI check", "max": 1})
    if not rep.get("IMG-1") or rep.get("IMG-1").status == "SKIP":
        manual.insert(9, {"item": "S4 final image <= 30 MB (`docker images minibank:v1`, or re-run with --image)", "max": 2})
    b2 = rep.get("BON-B2")
    curl_b2 = ("B2 curl through the ingress controller: kubectl -n ingress-nginx port-forward "
               "svc/ingress-nginx-controller 8081:80 & curl -H 'Host: minibank.local' localhost:8081/healthz -> 200")
    if b2 and b2.status != "SKIP":
        manual.append({"item": curl_b2, "max": 2})
    else:
        manual.append({"item": "B2 Ingress (not verified live): Ingress object minibank.local -> app Service (1) + " + curl_b2[3:]
                       + " (2)", "max": 3})
    b3 = rep.get("BON-B3")
    if not b3 or b3.status == "SKIP" or b3.earned < b3.max:
        manual.append({"item": "B3 Helm chart: values image.tag/replicaCount/resources, templates, `helm install` works"
                       + (" (not verified live)" if not b3 or b3.status == "SKIP" else ""), "max": 4})
    bonus_total = auto["bonus"] + sum(b["suggested"] for b in bonus_assist)
    return {"auto": auto, "stages": stages, "suggested_total": round_q(suggested_total, 0.01),
            "provisional": round_q(auto["core"] + suggested_total, 0.01), "bonus_assist": bonus_assist,
            "bonus_total": round_q(min(15, bonus_total), 0.01), "manual": manual,
            "died": getattr(args, "_died", False)}


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="grade_minibank.py",
        description="Auto-grader for the Build & Ship exam, Version A (MiniBank): grades a RUNNING server "
                    "(API contract 8 pts + concurrency 3 pts + bonus B1/B4) and optionally suggests points "
                    "from the repository, a live Kubernetes namespace and the Docker image.",
        epilog=HELP_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8080", help="base URL of the running MiniBank (default %(default)s)")
    ap.add_argument("--repo", metavar="PATH", help="student repository: run the S0-S8 assist checks (executes go test and the scripts)")
    ap.add_argument("--namespace", metavar="NS", help="live checks with kubectl/helm in this namespace (e.g. minibank)")
    ap.add_argument("--image", metavar="NAME:TAG", help="check the image size with docker image inspect (e.g. minibank:v1)")
    ap.add_argument("--json", metavar="FILE", help="also write a machine-readable report to FILE")
    ap.add_argument("--no-color", action="store_true", help="disable ANSI colors (also off when stdout is not a TTY or NO_COLOR is set)")
    ap.add_argument("--skip-bonus", action="store_true", help="skip the bonus checks (B1 metrics, B4 storm, B2/B3 live)")
    args = ap.parse_args(argv)

    st = Style(not args.no_color and sys.stdout.isatty() and not os.environ.get("NO_COLOR"))
    run_id = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    rep = Report()
    client = Client(args.url)

    probe = client.call("GET", "/healthz")
    reachable = probe.status is not None
    if not reachable:
        sys.stderr.write("error: %s is unreachable (%s)\n" % (args.url, probe.error))
    else:
        ctx = Ctx(client, run_id)
        run_api_suite(ctx, rep)
        run_concurrency(ctx, rep)
        if not args.skip_bonus:
            run_bonus_b4(ctx, rep)
            run_bonus_b1(ctx, rep)
        if client.call("GET", "/healthz").status is None:
            args._died = True
    if args.repo:
        repo = os.path.abspath(os.path.expanduser(args.repo))
        if not os.path.isdir(repo):
            sys.stderr.write("error: --repo %s is not a directory\n" % repo)
        else:
            check_s0(repo, rep)
            check_s1_hints(repo, rep)
            check_s2(repo, rep)
            check_s3(repo, rep, args.url, reachable)
            check_s4(repo, rep)
            check_s5(repo, rep)
            check_s6(repo, rep)
            check_s7_static(repo, rep)
            check_s8(repo, rep)
    live_items = {}
    if args.namespace:
        live_items = check_live(args.namespace, rep, args.skip_bonus)
        if live_items.get("_store_memory"):
            for cid in ("CON-1", "CON-2", "BON-B4"):
                if rep.get(cid):
                    rep.get(cid).note("!! K8S-STORE: deployment uses STORE=memory — set this row to 0 if --url is that deployment")
    if args.image:
        check_image(args.image, rep)

    totals = print_report(rep, st, args, run_id, reachable, live_items)
    if args.json:
        doc = {"grader": "grade_minibank.py", "version": GRADER_VERSION,
               "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
               "url": args.url, "repo": args.repo, "namespace": args.namespace, "image": args.image,
               "run_id": run_id, "reachable": reachable,
               "checks": [c.to_json() for c in rep.checks], "totals": totals}
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        sys.stdout.write("\nJSON report written to %s\n" % args.json)
    return 0 if reachable else 2


if __name__ == "__main__":
    sys.exit(main())
