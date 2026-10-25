"""Semantic Scholar pacing in the scholar server (PLAN_ideate_search §14 F1): every S2 request waits its turn on a clock
shared by all server processes, and a 429 is waited out (longer with a key) before the call gives up.

Run with the interpreter that has `mcp` (check_env.sh): python tests/search/test_server_pacing.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2].parent / "mcp" / "scholar_mcp"
sys.path.insert(0, str(SERVER_DIR))
try:
    import server  # noqa: E402
except ImportError as exc:                                  # no `mcp` in this interpreter
    server = None
    SKIP = str(exc)


@unittest.skipIf(server is None, "scholar server not importable (needs the interpreter with mcp)")
class TestPacing(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.clock = self.tmp / "clock"

    def test_turns_are_spaced_within_a_process(self):
        async def go():
            stamps = []

            async def one():
                await server._paced_turn(self.clock, 0.3)
                stamps.append(time.time())
            await asyncio.gather(one(), one(), one())
            return sorted(stamps)
        s = asyncio.run(go())
        self.assertGreaterEqual(s[1] - s[0], 0.28)
        self.assertGreaterEqual(s[2] - s[1], 0.28)

    def test_turns_are_spaced_across_processes(self):
        code = ("import asyncio,sys,time; sys.path.insert(0, %r); import server; "
                "asyncio.run(server._paced_turn(__import__('pathlib').Path(%r), 0.5)); print(time.time())"
                % (str(SERVER_DIR), str(self.clock)))
        procs = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True) for _ in range(2)]
        t = sorted(float(p.communicate()[0].strip().splitlines()[-1]) for p in procs)
        self.assertGreaterEqual(t[1] - t[0], 0.45)

    def test_backoff_longer_with_a_key(self):
        keep = server.SEMANTIC_SCHOLAR_API_KEY
        try:
            server.SEMANTIC_SCHOLAR_API_KEY = "x"
            self.assertEqual([server._s2_backoff(i) for i in range(3)], list(server.S2_BACKOFF))
            server.SEMANTIC_SCHOLAR_API_KEY = None
            self.assertEqual([server._s2_backoff(i) for i in range(3)], list(server.S2_BACKOFF_KEYLESS))
        finally:
            server.SEMANTIC_SCHOLAR_API_KEY = keep

    def test_recommendations_wait_out_a_429(self):
        calls, waits = [], []

        class Resp:
            def __init__(self, code):
                self.status_code, self.headers = code, ({"Retry-After": "12"} if code == 429 else {})

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(self.status_code)

            def json(self):
                return {"recommendedPapers": [{"title": "A neighbour", "paperId": "p1", "externalIds": {}}]}

        class Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, params=None, json=None):
                calls.append(url)
                return Resp(429 if len(calls) < 3 else 200)

        async def nosleep(s):
            waits.append(s)
        keep = (server.httpx.AsyncClient, server.asyncio.sleep, server.S2_CLOCK, server.S2_GAP,
                server.SEMANTIC_SCHOLAR_API_KEY)
        try:
            server.httpx.AsyncClient, server.asyncio.sleep = Client, nosleep
            server.S2_CLOCK, server.S2_GAP, server.SEMANTIC_SCHOLAR_API_KEY = self.clock, 0.0, "x"
            out = json.loads(asyncio.run(server.scholar_recommend(server.RecommendInput(paper_ids=["DOI:10.1/x"]))))
        finally:
            (server.httpx.AsyncClient, server.asyncio.sleep, server.S2_CLOCK, server.S2_GAP,
             server.SEMANTIC_SCHOLAR_API_KEY) = keep
        self.assertEqual(out["count"], 1)
        self.assertEqual(len(calls), 3)
        self.assertEqual([w for w in waits if w >= 10], [12.0, 30.0])     # Retry-After 12 > 10; then the 30 s step

    def test_abstracts_batch(self):
        """§15 G3: one batch request; a row S2 has no abstract for, and a null row, are `missing`; a 429 is waited out."""
        calls, waits = [], []

        class Resp:
            def __init__(self, code, rows=None):
                self.status_code, self.headers, self.rows = code, {}, rows

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(self.status_code)

            def json(self):
                return self.rows

        class Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, params=None, json=None):
                calls.append((url, params, json))
                return Resp(429) if len(calls) == 1 else Resp(200, [{"abstract": "A real abstract."}, {"abstract": None}, None])

        async def nosleep(s):
            waits.append(s)
        keep = (server.httpx.AsyncClient, server.asyncio.sleep, server.S2_CLOCK, server.S2_GAP,
                server.SEMANTIC_SCHOLAR_API_KEY)
        try:
            server.httpx.AsyncClient, server.asyncio.sleep = Client, nosleep
            server.S2_CLOCK, server.S2_GAP, server.SEMANTIC_SCHOLAR_API_KEY = self.clock, 0.0, "x"
            ids = ["DOI:10.1/a", "DOI:10.1/b", "S2ID"]
            out = json.loads(asyncio.run(server.scholar_abstracts(server.AbstractsInput(paper_ids=ids))))
        finally:
            (server.httpx.AsyncClient, server.asyncio.sleep, server.S2_CLOCK, server.S2_GAP,
             server.SEMANTIC_SCHOLAR_API_KEY) = keep
        self.assertEqual(out["abstracts"], {"DOI:10.1/a": "A real abstract."})
        self.assertEqual(out["missing"], ["DOI:10.1/b", "S2ID"])
        self.assertTrue(calls[-1][0].endswith("/paper/batch") and calls[-1][2] == {"ids": ids})
        self.assertEqual([w for w in waits if w >= 10], [10.0])


if __name__ == "__main__":
    unittest.main()
