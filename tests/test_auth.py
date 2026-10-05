"""
Credential acquisition.

The legacy script hardcoded Visual Studio Code's OAuth client id and asked for
the `public_repo` WRITE scope. Neither is reachable from here: these tests pin
the resolution order, and prove no provider can prompt, open a browser, or hand
back something that is not a GitHub token.
"""
import subprocess

import pytest

from iemod_fetch import auth
from iemod_fetch.errors import ConfigError, ModFetchError

# Captured before the autouse fixture stubs it out, so the helper tests below
# exercise the real implementation rather than the stub.
REAL_GIT_CREDENTIAL = auth._from_git_credential

VALID = "ghp_" + "A" * 36
GCM_OAUTH = "gho_" + "B" * 36
FINE_GRAINED = "github_pat_" + "C" * 30


class FakeProc:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout, self.returncode = stdout, returncode


@pytest.fixture(autouse=True)
def no_ambient_credentials(monkeypatch):
    """Never let the host's real environment or helpers leak into a test."""
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(auth, "_from_gh_cli", lambda: None)
    monkeypatch.setattr(auth, "_from_git_credential", lambda *a, **k: None)


# ------------------------------------------------------------------- order
def test_token_file_wins(tmp_path, monkeypatch):
    path = tmp_path / "tok"
    path.write_text(VALID + "\n")
    monkeypatch.setenv("GH_TOKEN", "env-token")
    cred = auth.resolve_credential(token_file=str(path))
    assert cred.token == VALID and "--token-file" in cred.source


def test_env_beats_helpers(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", VALID)
    monkeypatch.setattr(auth, "_from_gh_cli", lambda: "gh-token")
    assert auth.resolve_credential().source == "$GH_TOKEN"


def test_gh_cli_beats_git_credential(monkeypatch):
    monkeypatch.setattr(auth, "_from_gh_cli", lambda: VALID)
    monkeypatch.setattr(auth, "_from_git_credential", lambda *a, **k: GCM_OAUTH)
    cred = auth.resolve_credential()
    assert cred.token == VALID and "gh auth token" in cred.source


def test_git_credential_is_used_when_gh_is_absent(monkeypatch):
    """The Windows case: git installed, gh not installed."""
    monkeypatch.setattr(auth, "_from_git_credential", lambda *a, **k: GCM_OAUTH)
    cred = auth.resolve_credential()
    assert cred.token == GCM_OAUTH
    assert cred.source == "git credential helper"


def test_anonymous_is_a_valid_outcome():
    cred = auth.resolve_credential()
    assert cred.anonymous and "60 GitHub API requests" in cred.describe()


def test_each_provider_can_be_disabled(monkeypatch):
    monkeypatch.setattr(auth, "_from_gh_cli", lambda: "gh")
    monkeypatch.setattr(auth, "_from_git_credential", lambda *a, **k: GCM_OAUTH)
    assert auth.resolve_credential(use_gh=False).token == GCM_OAUTH
    assert auth.resolve_credential(use_git_credential=False).token == "gh"
    assert auth.resolve_credential(use_gh=False,
                                   use_git_credential=False).anonymous


def test_an_empty_token_file_is_a_configuration_error(tmp_path):
    path = tmp_path / "tok"
    path.write_text("   \n")
    with pytest.raises(ConfigError, match="empty"):
        auth.resolve_credential(token_file=str(path))


def test_a_missing_token_file_is_a_configuration_error(tmp_path):
    with pytest.raises(ConfigError, match="cannot read"):
        auth.resolve_credential(token_file=str(tmp_path / "nope"))


# --------------------------------------------------- git credential helper
def run_helper(monkeypatch, stdout=b"", returncode=0, exc=None):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        if exc:
            raise exc
        return FakeProc(stdout, returncode)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


@pytest.mark.parametrize("token", [VALID, GCM_OAUTH, FINE_GRAINED])
def test_a_stored_github_token_is_returned(monkeypatch, token):
    run_helper(monkeypatch, f"username=x\npassword={token}\n".encode())
    assert REAL_GIT_CREDENTIAL() == token


@pytest.mark.parametrize("password", [
    "hunter2",                       # an actual password, not a token
    "",                              # empty
    "ghp_short",                     # malformed
    "not-a-token-at-all",
])
def test_a_non_token_password_is_never_used_as_a_bearer(monkeypatch, password):
    run_helper(monkeypatch, f"username=x\npassword={password}\n".encode())
    assert REAL_GIT_CREDENTIAL() is None


def test_no_stored_credential_returns_none(monkeypatch):
    run_helper(monkeypatch, b"", returncode=1)
    assert REAL_GIT_CREDENTIAL() is None


def test_a_missing_git_binary_is_not_fatal(monkeypatch):
    run_helper(monkeypatch, exc=FileNotFoundError("git"))
    assert REAL_GIT_CREDENTIAL() is None


def test_a_hanging_helper_is_not_fatal(monkeypatch):
    run_helper(monkeypatch, exc=subprocess.TimeoutExpired("git", 15))
    assert REAL_GIT_CREDENTIAL() is None


def test_the_helper_can_never_prompt_or_open_a_browser(monkeypatch):
    """A mod download must not trigger an interactive auth flow."""
    seen = run_helper(monkeypatch, f"password={VALID}\n".encode())
    REAL_GIT_CREDENTIAL()

    joined = " ".join(seen["cmd"])
    assert "credential.interactive=false" in joined
    assert "credential.guiPrompt=false" in joined
    env = seen["kw"]["env"]
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GCM_INTERACTIVE"] == "never"
    assert seen["kw"]["timeout"] == 15


def test_the_helper_is_asked_only_about_github(monkeypatch):
    seen = run_helper(monkeypatch, f"password={VALID}\n".encode())
    REAL_GIT_CREDENTIAL()
    assert b"host=github.com" in seen["kw"]["input"]
    assert b"protocol=https" in seen["kw"]["input"]


# -------------------------------------------------------------- device flow
def test_device_flow_requires_a_client_id_you_own():
    with pytest.raises(ConfigError, match="an app you own"):
        auth.device_flow("", client=None)


def test_device_flow_requests_no_scope():
    posted = []

    class Client:
        def post_form(self, url, fields):
            posted.append((url, fields))
            if "device/code" in url:
                return {"device_code": "d", "user_code": "U", "interval": 0,
                        "expires_in": 100}
            return {"access_token": VALID}

    assert auth.device_flow("my-own-client-id", Client(),
                            sleep=lambda *_: None) == VALID
    assert posted[0][1]["scope"] == ""          # never `public_repo`


def test_device_flow_gives_up_instead_of_polling_forever():
    class Pending:
        def post_form(self, url, fields):
            if "device/code" in url:
                return {"device_code": "d", "interval": 1, "expires_in": 3}
            return {"error": "authorization_pending"}

    clock = iter([0, 1, 2, 3, 4, 5, 6])
    with pytest.raises(ModFetchError, match="timed out"):
        auth.device_flow("id", Pending(), sleep=lambda *_: None,
                         now=lambda: next(clock))


def test_device_flow_backs_off_when_told_to_slow_down():
    intervals = []

    class SlowDown:
        def __init__(self):
            self.n = 0

        def post_form(self, url, fields):
            if "device/code" in url:
                return {"device_code": "d", "interval": 5, "expires_in": 100}
            self.n += 1
            if self.n == 1:
                return {"error": "slow_down", "interval": 5}
            return {"access_token": VALID}

    assert auth.device_flow("id", SlowDown(), sleep=intervals.append) == VALID
    assert intervals == [5.0, 10.0]             # honoured the back-off
