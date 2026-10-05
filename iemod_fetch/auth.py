"""
GitHub credential acquisition.

ADR-0005: the tool is usable with NO credential at all. A token only raises the
API rate limit (60/h -> 5000/h), which matters here because the real manifest
needs ~110 API calls. Nothing this tool does requires write access, so the
recommended credential is a fine-grained PAT with no repository permissions.

The legacy script hardcoded Visual Studio Code's OAuth client ID and requested
the `public_repo` WRITE scope. Both are removed: impersonating another vendor's
OAuth client is not ours to do, and a fetcher must never hold write access.
"""
import getpass
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

from .errors import ConfigError, ModFetchError

# Shapes GitHub issues: classic PAT, OAuth app, user-to-server, server-to-server,
# refresh, and fine-grained PAT. Anything else from a credential helper is not a
# token and must not be sent as a bearer.
_TOKEN_SHAPE = re.compile(r"^(gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,})$")

DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"


@dataclass
class Credential:
    token: Optional[str]
    source: str

    @property
    def anonymous(self) -> bool:
        return not self.token

    def describe(self) -> str:
        if self.anonymous:
            return "anonymous (60 GitHub API requests/hour)"
        return f"token from {self.source} (5000 requests/hour)"


def _from_gh_cli() -> Optional[str]:
    try:
        out = subprocess.run(["gh", "auth", "token"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    token = out.stdout.decode("utf-8", "replace").strip()
    return token or None


def _from_git_credential(host: str = "github.com") -> Optional[str]:
    """
    Ask git's own credential helper for an existing GitHub token.

    On Windows, Git for Windows bundles Git Credential Manager, which already
    holds a token if you have ever pushed to GitHub over HTTPS - so `git` alone
    is enough and `gh` need not be installed.

    Interaction is suppressed on every channel we know of: a missing credential
    must fail silently, never pop a browser or a prompt in the middle of a mod
    download. The value is only accepted if it actually looks like a GitHub
    token, so a stored username/password is never sent as a bearer.
    """
    command = ["git",
               "-c", "credential.interactive=false",
               "-c", "credential.guiPrompt=false",
               "credential", "fill"]
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    try:
        proc = subprocess.run(command,
                              input=f"protocol=https\nhost={host}\n\n".encode(),
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=15, check=False, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if line.startswith("password="):
            token = line.partition("=")[2].strip()
            return token if _TOKEN_SHAPE.match(token) else None
    return None


def resolve_credential(token_file: Optional[str] = None, use_gh: bool = True,
                       allow_prompt: bool = False,
                       oauth_client_id: Optional[str] = None,
                       use_git_credential: bool = True,
                       client=None) -> Credential:
    """
    Resolution order, most explicit first. Never echoes the token.
    """
    token: Optional[str]
    if token_file:
        try:
            with open(token_file, "r", encoding="utf-8") as fh:
                token = fh.read().strip()
        except OSError as exc:
            raise ConfigError(f"cannot read --token-file {token_file}: {exc}") from exc
        if not token:
            raise ConfigError(f"--token-file {token_file} is empty")
        return Credential(token, f"--token-file {token_file}")

    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(var):
            return Credential(os.environ[var].strip(), f"${var}")

    if use_gh:
        token = _from_gh_cli()
        if token:
            return Credential(token, "`gh auth token`")

    if use_git_credential:
        token = _from_git_credential()
        if token:
            return Credential(token, "git credential helper")

    if oauth_client_id and client is not None:
        return Credential(device_flow(oauth_client_id, client), "OAuth device flow")

    if allow_prompt and sys.stdin.isatty():
        token = getpass.getpass("GitHub token (input hidden, blank for anonymous): ").strip()
        if token:
            return Credential(token, "interactive prompt")

    return Credential(None, "none")


def device_flow(client_id: str, client, sleep=time.sleep, now=time.monotonic,
                on_code=None) -> str:
    """
    OAuth 2.0 device flow against the caller's OWN registered app.

    Requests an empty scope (public read only). Honours `interval`, `slow_down`
    and `expires_in`, so it terminates instead of polling forever.
    """
    if not client_id:
        raise ConfigError("device flow requires --oauth-client-id of an app you own")

    data = client.post_form(DEVICE_CODE_URL, {"client_id": client_id, "scope": ""})
    if "device_code" not in data:
        raise ModFetchError(f"device authorization failed: {data.get('error', data)}")

    interval = float(data.get("interval", 5)) or 5.0
    expires_in = float(data.get("expires_in", 900))
    deadline = now() + expires_in
    if on_code:
        on_code(data.get("user_code", ""),
                data.get("verification_uri_complete")
                or data.get("verification_uri", "https://github.com/login/device"))

    poll = {"client_id": client_id, "device_code": data["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}
    while now() < deadline:
        sleep(interval)
        result = client.post_form(ACCESS_TOKEN_URL, poll)
        granted = result.get("access_token")
        if isinstance(granted, str) and granted:
            return granted
        error = result.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += float(result.get("interval", 5))
            continue
        raise ModFetchError(f"device authorization failed: {error or result}")
    raise ModFetchError("device authorization timed out; no token obtained")
