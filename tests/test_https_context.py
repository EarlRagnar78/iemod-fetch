"""
One TLS context per process (ADR-0048): building one loads the system's
trust store - on Windows every certificate of the store, parsed while the
GIL is held, 50-240 ms measured on the runner - so a download started from
the wizard froze its window. Built once, shared by every HttpClient, and
built by the wizard before its window is drawn.
"""
import ssl
import urllib.request

import pytest

from iemod_fetch import api, net


@pytest.fixture
def fresh(monkeypatch):
    """No context built yet, and every build counted."""
    monkeypatch.setattr(net, "_HTTPS_CONTEXT", None)
    built = []
    real = ssl.create_default_context

    def counting(*args, **kwargs):
        built.append(1)
        return real(*args, **kwargs)
    # http.client builds through this hook (PEP 476), and so does net
    monkeypatch.setattr(net.ssl, "_create_default_https_context", counting)
    return built


def _https_handler(client):
    return next(h for h in client._opener.handlers
                if isinstance(h, urllib.request.HTTPSHandler))


def test_every_client_shares_one_context_built_once(fresh):
    first, second = net.HttpClient(), net.HttpClient(allow_http=True)
    assert len(fresh) == 1
    assert _https_handler(first)._context is _https_handler(second)._context
    assert _https_handler(first)._context is net.https_context()


def test_the_shared_context_still_verifies(fresh):
    """Sharing changes when it is built, not what it accepts: the settings
    of the context http.client would have built itself."""
    import http.client
    context = net.https_context()
    theirs = http.client._create_https_context(11)
    assert context.verify_mode == theirs.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is theirs.check_hostname is True
    assert context.minimum_version == theirs.minimum_version
    assert context.options == theirs.options
    assert context.post_handshake_auth == theirs.post_handshake_auth


def test_prepare_https_builds_it_ahead_of_any_run(fresh):
    api.prepare_https()
    assert len(fresh) == 1 and net._HTTPS_CONTEXT is not None
    net.HttpClient()
    assert len(fresh) == 1          # the run finds it built


def test_a_site_s_pep_476_hook_is_still_honoured(monkeypatch):
    """A site that sets ssl._create_default_https_context (a corporate CA, a
    test) got that context from urllib before; it still does."""
    monkeypatch.setattr(net, "_HTTPS_CONTEXT", None)
    theirs = ssl.create_default_context()
    monkeypatch.setattr(net.ssl, "_create_default_https_context", lambda: theirs)
    assert _https_handler(net.HttpClient())._context is theirs


def test_a_failed_early_build_does_not_stop_the_wizard(monkeypatch):
    """SSLKEYLOGFILE in a folder that does not exist makes the build raise:
    prepare_https lets the window open, keeps nothing, and the first run
    meets the error itself, as a failed run, as before ADR-0048."""
    monkeypatch.setattr(net, "_HTTPS_CONTEXT", None)

    def broken():
        raise FileNotFoundError(2, "No such file or directory", "/nowhere/keys.log")
    monkeypatch.setattr(net.ssl, "_create_default_https_context", broken)
    api.prepare_https()
    assert net._HTTPS_CONTEXT is None
    with pytest.raises(FileNotFoundError):
        net.HttpClient()
