"""Onboarding: engines, settings, sign-in flows (against a fake Google/OpenRouter), and the providers."""
import importlib
import json
import os
import stat
import sys
import threading
import time
import unittest
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class Fake(BaseHTTPRequestHandler):
    """Stands in for oauth2.googleapis.com/token, openrouter.ai/api/v1/auth/keys and a chat server."""
    seen = []

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        Fake.seen.append((self.path, body, dict(self.headers)))
        if self.path == "/token":
            form = dict(urllib.parse.parse_qsl(body))
            if form.get("grant_type") == "refresh_token":
                return self._json({"access_token": "ya29.refreshed", "expires_in": 3600})
            assert form["code"] == "good-code" and form["code_verifier"]
            claims = json.dumps({"email": "tarani@example.com"}).encode()
            import base64
            idt = "x." + base64.urlsafe_b64encode(claims).decode().rstrip("=") + ".y"
            return self._json({"access_token": "ya29.first", "expires_in": 3600, "refresh_token": "1//refresh",
                               "id_token": idt})
        if self.path == "/keys":
            j = json.loads(body)
            assert j["code"] == "or-code" and j["code_challenge_method"] == "S256"
            return self._json({"key": "sk-or-v1-fromsignin"})
        if self.path == "/v1/chat/completions":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n')
            return
        self._json({}, 404)

    def do_GET(self):
        Fake.seen.append((self.path, "", dict(self.headers)))
        if self.path.startswith("/v1/models"):
            return self._json({"data": [{"id": "big-coder"}, {"id": "text-embed"}, {"id": "small"}]})
        self._json({}, 404)


class OnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.old_env = dict(os.environ)
        os.environ["ARA_HOME"] = self.tmp.name
        for k in ("ARA_PROVIDER", "ARA_MODEL", "ARA_BASE_URL", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ARA_API_KEY",
                  "OPENROUTER_API_KEY", "SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY", "ARA_GOOGLE_CLIENT"):
            os.environ.pop(k, None)
        os.environ["DISPLAY"] = ":0"
        import ara_code.engines, ara_code.login, ara_code.providers
        self.engines = importlib.reload(ara_code.engines)
        self.login = importlib.reload(ara_code.login)
        self.providers = importlib.reload(ara_code.providers)
        Fake.seen.clear()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
        self.tmp.cleanup()

    # ── settings ──
    def test_nothing_set_up_means_onboarding(self):
        engine, model, url = self.engines.resolve()
        self.assertIsNone(engine)
        with self.assertRaises(self.providers.ProviderError) as cm:
            self.providers.make_provider()
        self.assertEqual(str(cm.exception), "NOT_SET_UP")

    def test_old_gemini_key_still_works_without_setup(self):
        os.environ["GEMINI_API_KEY"] = "AIzaOld"
        engine, model, _ = self.engines.resolve()
        self.assertEqual(engine.id, "gemini")
        self.assertEqual(model, "gemini-flash-latest")

    def test_config_flags_and_env_order(self):
        self.engines.save_config(engine="openrouter", model="anthropic/claude-sonnet-4.5")
        e, m, u = self.engines.resolve()
        self.assertEqual((e.id, m, u), ("openrouter", "anthropic/claude-sonnet-4.5", "https://openrouter.ai/api/v1"))
        os.environ["ARA_MODEL"] = "openai/gpt-5"
        self.assertEqual(self.engines.resolve()[1], "openai/gpt-5")
        e, m, _ = self.engines.resolve(provider="groq")  # another engine: its own default, not the saved model
        self.assertEqual(e.id, "groq")
        self.assertEqual(m, "openai/gpt-5")  # ARA_MODEL still wins
        del os.environ["ARA_MODEL"]
        self.assertEqual(self.engines.resolve(provider="groq")[1], "openai/gpt-oss-120b")
        e, _, u = self.engines.resolve(provider="openai", base_url="http://box:8642/v1")  # the old meaning
        self.assertEqual((e.id, u), ("custom", "http://box:8642/v1"))

    def test_auth_file_is_private(self):
        self.engines.save_auth("openai", {"type": "key", "key": "sk-secret-1234"})
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(self.engines.AUTH).st_mode), 0o600)
        self.assertEqual(self.engines.describe(self.engines.get("openai")), "key …1234 saved")

    def test_ranking_puts_coding_models_first_and_drops_non_chat(self):
        e = self.engines.get("gemini")
        ranked = self.engines.rank(e, ["text-embedding-004", "gemini-2.0-flash", "gemini-flash-latest",
                                       "imagen-4", "gemini-pro-latest", "gemini-3.5-flash"])
        self.assertEqual(ranked[0], "gemini-flash-latest")
        self.assertNotIn("text-embedding-004", ranked)
        self.assertNotIn("imagen-4", ranked)

    def test_list_models_from_an_openai_compatible_server(self):
        e = self.engines.get("custom")
        self.assertEqual(self.engines.list_models(e, self.url + "/v1", {"key": None}), ["big-coder", "small"])
        self.assertTrue(self.engines.reachable(self.url + "/v1"))
        self.assertFalse(self.engines.reachable("http://127.0.0.1:9/v1", timeout=0.5))

    # ── providers ──
    def test_gemini_headers_for_key_and_signin(self):
        self.assertEqual(self.engines.gemini_headers({"key": "AIza1"}), {"x-goog-api-key": "AIza1"})
        self.engines.save_auth("google", {"type": "oauth", "refresh_token": "r", "access_token": "ya29.x",
                                          "expires_at": int(time.time()) + 3000, "project": "ara-proj"})
        h = self.engines.gemini_headers({"oauth": {}})
        self.assertEqual(h, {"Authorization": "Bearer ya29.x"})  # quota goes to the client's own project
        os.environ["ARA_GOOGLE_QUOTA_PROJECT"] = "other"
        self.assertEqual(self.engines.gemini_headers({"oauth": {}})["x-goog-user-project"], "other")

    def test_openai_provider_sends_no_empty_tool_list(self):
        p = self.providers.OpenAIProvider(model="m", base_url=self.url + "/v1", api_key="k")
        out = list(p.stream([{"role": "user", "text": "hello"}], "sys", []))
        self.assertIn(("text", "hi"), out)
        sent = json.loads([b for path, b, _ in Fake.seen if path == "/v1/chat/completions"][-1])
        self.assertNotIn("tools", sent)

    # ── sign-in ──
    def _client(self):
        Path(self.tmp.name, "google_client.json").write_text(json.dumps(
            {"installed": {"client_id": "123.apps.googleusercontent.com", "client_secret": "GOCSPX-x",
                           "project_id": "ara-proj"}}))

    def _browser_that_says_yes(self, code, keep):
        def fake_open(url):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            keep.update(q)
            back = q.get("redirect_uri") or q.get("callback_url")
            sep = "&" if "?" in back else "?"
            target = back + sep + urllib.parse.urlencode({"code": code, **({"state": q["state"]} if "state" in q else {})})
            threading.Timer(0.3, lambda: urllib.request.urlopen(target).read()).start()
            return True
        return fake_open

    def test_google_signin_saves_a_refresh_token_and_refreshes(self):
        self._client()
        self.login.GOOGLE_TOKEN = self.url + "/token"
        seen = {}
        self.login.open_browser = self._browser_that_says_yes("good-code", seen)
        email = self.login.google_login(lambda *a: None)
        self.assertEqual(email, "tarani@example.com")
        self.assertEqual(seen["code_challenge_method"], "S256")
        self.assertIn("generative-language", seen["scope"])
        self.assertEqual(seen["access_type"], "offline")
        saved = self.engines.load_auth()["google"]
        self.assertEqual((saved["refresh_token"], saved["project"]), ("1//refresh", "ara-proj"))
        self.assertEqual(self.login.google_access_token(), ("ya29.first", "ara-proj"))
        saved["expires_at"] = 0
        self.engines.save_auth("google", saved)
        self.assertEqual(self.login.google_access_token(), ("ya29.refreshed", "ara-proj"))
        self.assertEqual(self.engines.describe(self.engines.get("google")), "signed in as tarani@example.com")

    def test_google_signin_without_a_client_explains(self):
        with self.assertRaises(self.login.LoginError) as cm:
            self.login.google_login(lambda *a: None)
        self.assertEqual(str(cm.exception), "NO_CLIENT")

    def test_google_rejects_a_mismatched_state(self):
        self._client()
        self.login.GOOGLE_TOKEN = self.url + "/token"

        def evil(url):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            target = q["redirect_uri"] + "?" + urllib.parse.urlencode({"code": "good-code", "state": "not-yours"})
            threading.Timer(0.3, lambda: urllib.request.urlopen(target).read()).start()
            return True

        self.login.open_browser = evil
        with self.assertRaises(self.login.LoginError):
            self.login.google_login(lambda *a: None)

    def test_openrouter_signin_gets_a_key(self):
        self.login.OPENROUTER_KEYS = self.url + "/keys"
        seen = {}
        self.login.open_browser = self._browser_that_says_yes("or-code", seen)
        key = self.login.openrouter_login(lambda *a: None)
        self.assertEqual(key, "sk-or-v1-fromsignin")
        self.assertIn("/callback/", seen["callback_url"])
        self.assertEqual(self.engines.credential(self.engines.get("openrouter"))["key"], "sk-or-v1-fromsignin")

    def test_pasting_the_address_works_on_a_server(self):
        self.login.OPENROUTER_KEYS = self.url + "/keys"
        os.environ["SSH_CONNECTION"] = "1.2.3.4 5 6.7.8.9 22"
        import io
        old = sys.stdin
        sys.stdin = io.StringIO("or-code\n")
        try:
            lines = []
            key = self.login.openrouter_login(lambda m, k="": lines.append(m))
        finally:
            sys.stdin = old
        self.assertEqual(key, "sk-or-v1-fromsignin")
        self.assertTrue(any("openrouter.ai/auth" in l and "callback_url" not in l for l in lines))

    def test_importing_a_client_file(self):
        f = Path(self.tmp.name, "client_secret_123.json")
        f.write_text(json.dumps({"installed": {"client_id": "abc.apps.googleusercontent.com",
                                               "client_secret": "s", "project_id": "p"}}))
        c = self.login.import_google_client(str(f))
        self.assertEqual(c["project_id"], "p")
        self.assertEqual(self.login.google_client()["client_id"], "abc.apps.googleusercontent.com")
        bad = Path(self.tmp.name, "bad.json")
        bad.write_text("{}")
        with self.assertRaises(self.login.LoginError):
            self.login.import_google_client(str(bad))


if __name__ == "__main__":
    unittest.main()
