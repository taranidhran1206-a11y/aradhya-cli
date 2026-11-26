"""Signing in through the browser: Google (for Gemini) and OpenRouter.

Both use PKCE with a one-off listener on 127.0.0.1. On a server over SSH (EC2) or anywhere without a browser,
she prints the address instead; you open it on any device and paste back what you get.

Google sign-in needs an OAuth "Desktop app" client from a Google Cloud project that has the Generative
Language API turned on. She looks for it in ~/.aradhya/google_client.json (import one with
`ara login google --client client_secret.json`), then $ARA_GOOGLE_CLIENT, then the copy that ships with her.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from . import engines

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE = "https://oauth2.googleapis.com/revoke"
GOOGLE_SCOPES = ["openid", "email", "https://www.googleapis.com/auth/cloud-platform",
                 "https://www.googleapis.com/auth/generative-language.retriever"]
OPENROUTER_AUTH = "https://openrouter.ai/auth"
OPENROUTER_KEYS = "https://openrouter.ai/api/v1/auth/keys"
BUNDLED_CLIENT = Path(__file__).parent / "google_client.json"
CLIENT_HELP = "https://ai.google.dev/gemini-api/docs/oauth"


class LoginError(Exception):
    pass


# ─────────────────────────── helpers ───────────────────────────

def _verifier():
    return secrets.token_urlsafe(64)[:96]


def _challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def is_remote():
    """True when there's no browser on this machine to open: SSH sessions and desktop-less Linux."""
    env = os.environ
    if env.get("SSH_CONNECTION") or env.get("SSH_CLIENT") or env.get("SSH_TTY"):
        return True
    if "com.termux" in env.get("PREFIX", ""):
        return False  # Termux opens the phone's browser
    if sys.platform.startswith("linux") and not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
        return True
    return False


def open_browser(url):
    if "com.termux" in os.environ.get("PREFIX", "") and shutil.which("termux-open-url"):
        try:
            subprocess.run(["termux-open-url", url], check=False, timeout=10)
            return True
        except Exception:
            pass
    try:
        return webbrowser.open(url)
    except Exception:
        return False


DONE_PAGE = """<!doctype html><meta charset=utf-8><title>Aradhya Code</title>
<body style="background:#14161b;color:#e9e6df;font:16px/1.5 system-ui,sans-serif;display:grid;place-items:center;
height:100vh;margin:0"><div style="text-align:center;max-width:28rem;padding:2rem">
<div style="font-size:2.4rem;color:#E8B55B">&#10022;</div><h1 style="font-weight:600;font-size:1.5rem;margin:.4rem 0">
{title}</h1><p style="color:#8A8F98">{body}</p></div></body>"""


class _Listener:
    """A one-shot web server on 127.0.0.1 that catches the browser coming back with ?code=…"""

    def __init__(self, path="/"):
        self.path, self.result = path, None
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                u = urllib.parse.urlparse(self.path)
                if u.path != outer.path:
                    self.send_response(404)
                    self.end_headers()
                    return
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                ok = "code" in q
                page = DONE_PAGE.format(
                    title="You're signed in" if ok else "Sign-in didn't finish",
                    body="You can close this tab and go back to your terminal." if ok
                    else "Go back to your terminal and try again.")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(page.encode())
                outer.result = q

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.server.timeout = 0.3
        self._stop = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self._stop and self.result is None:
            self.server.handle_request()

    def close(self):
        self._stop = True
        try:
            self.server.server_close()
        except Exception:
            pass


def _wait(listener, ask, timeout=600):
    """Wait for the browser to come back, while also letting the person paste the address or code.
    Returns a dict of query parameters."""
    if listener is not None and not ask:
        end = time.time() + timeout
        while listener.result is None and time.time() < end:
            time.sleep(0.2)
        if listener.result is None:
            raise LoginError("Timed out waiting for the browser.")
        return listener.result
    pasted = _prompt_until(ask, lambda: listener is not None and listener.result is not None,
                           can_wait=listener is not None)
    if listener is not None and listener.result is not None:
        return listener.result
    pasted = (pasted or "").strip().strip('"').strip("'")
    if not pasted:
        raise LoginError("Nothing was pasted.")
    if "://" in pasted or pasted.startswith("/?") or pasted.startswith("?"):
        query = urllib.parse.urlparse(pasted).query or pasted.split("?", 1)[-1]
        q = {k: v[0] for k, v in urllib.parse.parse_qs(query).items()}
        if "code" not in q and "error" not in q:
            raise LoginError("That address doesn't have a sign-in code in it.")
        return q
    return {"code": pasted}


def _prompt_until(message, done, can_wait=True):
    """Ask for a line of input, but give up quietly as soon as done() turns true."""
    if not sys.stdin.isatty():
        if not can_wait:  # nothing will come back on its own: read the pasted code from stdin
            print(message, end="", flush=True)
            return sys.stdin.readline()
        while not done():
            time.sleep(0.2)
        return ""
    try:
        from prompt_toolkit import PromptSession
    except ImportError:
        return input(message)
    session = PromptSession()

    def watch():
        while not done():
            if getattr(session.app, "_is_done", False):
                return
            time.sleep(0.2)
        while not session.app.is_running:
            if getattr(session.app, "_is_done", False):
                return
            time.sleep(0.05)
        try:
            session.app.loop.call_soon_threadsafe(lambda: session.app.exit(result=""))
        except Exception:
            pass

    t = threading.Thread(target=watch, daemon=True)
    t.start()
    try:
        return session.prompt(message)
    except (EOFError, KeyboardInterrupt):
        if done():
            return ""
        raise KeyboardInterrupt
    finally:
        session.app._is_done = True


def _post_form(url, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read().decode())
            msg = j.get("error_description") or j.get("error") or str(j)
        except Exception:
            msg = f"HTTP {e.code}"
        raise LoginError(msg)


def _post_json(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise LoginError("OpenRouter said the code was used already or is older than 10 minutes. Try again.")
        raise LoginError(f"OpenRouter answered {e.code}.")


# ─────────────────────────── Google ───────────────────────────

def _client_from(data):
    c = data.get("installed") or data.get("web") or data
    if not c.get("client_id"):
        return None
    return {"client_id": c["client_id"], "client_secret": c.get("client_secret", ""), "project_id": c.get("project_id", "")}


def google_client():
    """The OAuth client to sign in with, or None if there isn't one yet."""
    for p in (engines.HOME / "google_client.json", os.environ.get("ARA_GOOGLE_CLIENT"), BUNDLED_CLIENT):
        if not p:
            continue
        try:
            c = _client_from(json.loads(Path(p).read_text("utf-8")))
        except (OSError, ValueError):
            continue
        if c:
            return c
    return None


def import_google_client(path):
    """Copy a client_secret.json downloaded from Google Cloud into ~/.aradhya."""
    data = json.loads(Path(path).expanduser().read_text("utf-8"))
    c = _client_from(data)
    if not c:
        raise LoginError("That file isn't an OAuth client from Google Cloud (no client_id in it).")
    engines.HOME.mkdir(parents=True, exist_ok=True)
    target = engines.HOME / "google_client.json"
    target.write_text(json.dumps({"installed": c}, indent=2), "utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return c


def _email_from(id_token):
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("email")
    except Exception:
        return None


def google_auth_url(client, redirect_uri, state, challenge):
    return GOOGLE_AUTH + "?" + urllib.parse.urlencode({
        "client_id": client["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES), "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent"})


def google_login(say, browser=True):
    """Sign in with Google and save the refresh token. say(markup) prints a line. Returns the email."""
    client = google_client()
    if not client:
        raise LoginError("NO_CLIENT")
    verifier, state = _verifier(), secrets.token_urlsafe(16)
    listener = _Listener("/")
    redirect = f"http://127.0.0.1:{listener.port}/"
    url = google_auth_url(client, redirect, state, _challenge(verifier))
    remote = is_remote() or not browser
    try:
        if remote:
            say("Open this on any phone or computer and sign in:")
            say(f"[link={url}]{url}[/link]", "url")
            say("When it's done, the page will say it can't connect. That's fine: copy that page's address and paste it here.")
            q = _wait(listener, "  Address: ")
        else:
            opened = open_browser(url)
            say("I opened Google in your browser. Pick your account and allow access." if opened
                else "Open this in your browser and sign in:")
            if not opened:
                say(f"[link={url}]{url}[/link]", "url")
            say("Waiting for you… (or paste the address from the browser here)", "dim")
            q = _wait(listener, "  ")
    finally:
        listener.close()
    if q.get("error"):
        raise LoginError("Google said: " + q.get("error_description", q["error"]).replace("_", " "))
    if q.get("state") and q["state"] != state:
        raise LoginError("That sign-in didn't come from this attempt. Try again.")
    tok = _post_form(GOOGLE_TOKEN, {
        "code": q["code"], "client_id": client["client_id"], "client_secret": client["client_secret"],
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier})
    if not tok.get("refresh_token"):
        raise LoginError("Google didn't give a long-lived sign-in. Remove Aradhya at myaccount.google.com/permissions and try again.")
    email = _email_from(tok.get("id_token", ""))
    engines.save_auth("google", {
        "type": "oauth", "refresh_token": tok["refresh_token"], "access_token": tok.get("access_token"),
        "expires_at": int(time.time()) + int(tok.get("expires_in", 3600)), "email": email,
        "project": client.get("project_id"), "client_id": client["client_id"]})
    return email


def google_access_token():
    """A fresh access token (and the quota project) for the saved Google sign-in."""
    entry = engines.load_auth().get("google") or {}
    if not entry.get("refresh_token"):
        raise LoginError("Not signed in to Google. Run: ara login google")
    if entry.get("access_token") and entry.get("expires_at", 0) - 90 > time.time():
        return entry["access_token"], entry.get("project")
    client = google_client()
    if not client:
        raise LoginError("The Google sign-in client is missing. Run: ara login google")
    try:
        tok = _post_form(GOOGLE_TOKEN, {
            "client_id": client["client_id"], "client_secret": client["client_secret"],
            "refresh_token": entry["refresh_token"], "grant_type": "refresh_token"})
    except LoginError as e:
        if "invalid_grant" in str(e) or "expired" in str(e).lower() or "revoked" in str(e).lower():
            raise LoginError("Your Google sign-in expired. Run: ara login google")
        raise
    entry.update(access_token=tok["access_token"], expires_at=int(time.time()) + int(tok.get("expires_in", 3600)))
    entry.setdefault("project", client.get("project_id"))
    engines.save_auth("google", entry)
    return entry["access_token"], entry.get("project")


def google_logout():
    entry = engines.load_auth().get("google") or {}
    if entry.get("refresh_token"):
        try:
            _post_form(GOOGLE_REVOKE, {"token": entry["refresh_token"]})
        except Exception:
            pass
    engines.save_auth("google", None)


# ─────────────────────────── OpenRouter ───────────────────────────

def openrouter_login(say, browser=True):
    """Sign in to OpenRouter; it hands back a key that's saved like any other. Returns the key."""
    verifier = _verifier()
    params = {"code_challenge": _challenge(verifier), "code_challenge_method": "S256", "key_label": "Aradhya Code"}
    if is_remote() or not browser:
        url = OPENROUTER_AUTH + "?" + urllib.parse.urlencode(params)
        say("Open this on any phone or computer and sign in:")
        say(f"[link={url}]{url}[/link]", "url")
        say("OpenRouter will show you a code. Paste it here.")
        q = _wait(None, "  Code: ")
    else:
        nonce = secrets.token_urlsafe(12)
        listener = _Listener(f"/callback/{nonce}")
        url = OPENROUTER_AUTH + "?" + urllib.parse.urlencode(
            {"callback_url": f"http://127.0.0.1:{listener.port}/callback/{nonce}", **params})
        try:
            opened = open_browser(url)
            say("I opened OpenRouter in your browser. Sign in and press Authorize." if opened
                else "Open this in your browser and sign in:")
            if not opened:
                say(f"[link={url}]{url}[/link]", "url")
            say("Waiting for you…", "dim")
            q = _wait(listener, "  ")
        finally:
            listener.close()
    if q.get("error"):
        raise LoginError("OpenRouter said: " + q.get("error_description", q["error"]))
    key = (_post_json(OPENROUTER_KEYS, {"code": q["code"], "code_verifier": verifier,
                                        "code_challenge_method": "S256"}) or {}).get("key")
    if not key:
        raise LoginError("OpenRouter didn't send a key back.")
    engines.save_auth("openrouter", {"type": "key", "key": key, "who": "signed in"})
    return key
