"""A page read once is not embedded again, and one deadline bounds every stage: past it
ranking falls back to word overlap, an unscored page is withheld under --decipher, and the
relay refuses rather than hand back undeciphered pages."""
import os
import time
from unittest import mock

from tests.harness import GrilleCase

import _embed as embed  # noqa: E402
import _web as web  # noqa: E402
from grillelib import config, pipeline, rank, store, vcache  # noqa: E402


class Scale(GrilleCase):
    def test_a_page_read_once_is_not_embedded_again(self):
        seen = []

        def fake(texts, quiet):
            seen.extend(texts)
            return [[float(len(t)), 1.0] for t in texts]
        with mock.patch.object(embed, "_embed_ollama", fake), \
                mock.patch.object(embed, "resolve_backend", lambda want=None: ("ollama", "m")):
            pages = ["alpha beta " * 50, "gamma delta " * 50]
            rank.rank_each(["alpha?"], pages)
            first = len(seen)
            rank.rank_each(["alpha?"], pages)
        self.assertGreater(first, 0)
        self.assertEqual(len(seen), first, "a cached page was embedded again")

    def test_the_cache_keeps_vectors(self):
        c = vcache.open_cache(config._home())
        c["k"] = [1.0, 2.0]
        c.close()
        c = vcache.open_cache(config._home())
        self.assertEqual(list(c.get("k")), [1.0, 2.0])
        c.close()

    def test_past_the_deadline_nothing_undeciphered_is_returned(self):
        with mock.patch.dict(os.environ, {"PANOPLY_DEADLINE": str(time.time() + 0.01)}):
            d = web.Deadline()
            time.sleep(0.05)
            r = pipeline.sift(str(self.f), ["engine oil?"], store.store_dir(), score=True, strict=True, deadline=d)
            self.assertIn("word overlap", r.method)
            self.assertTrue(all("withheld" in p.body for p in r.pages), "an unscored page passed under --decipher")
            text, code = pipeline.decipher(r, {"url": "http://127.0.0.1:9/v1", "model": "m"}, str(self.f), d)
        self.assertEqual(code, pipeline.RELAY_FAILED)


class AuditFixes(Scale):
    def test_two_runs_share_the_cache_without_a_lock_crash(self):
        a, b = vcache.open_cache(config._home()), vcache.open_cache(config._home())
        a["x"] = [1.0]
        b["y"] = [2.0]
        a.close()
        b.close()
        c = vcache.open_cache(config._home())
        self.assertEqual((list(c.get("x")), list(c.get("y"))), ([1.0], [2.0]))
        c.close()

    def test_detect_finds_a_local_server(self):
        import json as _json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from grillelib import admin

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = _json.dumps({"data": [{"id": "chat-1"}, {"id": "nomic-embed"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.assertEqual(admin._models_at(f"http://127.0.0.1:{srv.server_address[1]}/v1"), ["chat-1"])
