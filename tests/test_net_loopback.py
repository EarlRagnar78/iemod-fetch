"""
The transport against a real socket, not a test double.

Every other network test replaces urllib's opener with a hand-written double,
which encodes what we *believe* http.client does. These run a stdlib HTTP
server on 127.0.0.1, so the real urllib/http.client stack decides what a cut
connection, a Retry-After or an oversized Content-Length turns into. Offline:
nothing leaves the loopback interface.
"""
import http.server
import io
import threading
import zipfile

import pytest

from iemod_fetch.errors import HttpStatusError, TooLarge
from iemod_fetch.net import HttpClient


def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mod/mod.tp2", "BACKUP ~mod/backup~\n" * 200)
    return buf.getvalue()


ZIP = _zip_bytes()


class _Script(http.server.BaseHTTPRequestHandler):
    """Answers each request with the next step of `server.script`."""

    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802 - the stdlib's name
        self.server.hits.append(self.path)
        step = self.server.script.pop(0) if self.server.script else "ok"
        if step == "ok":
            self._send(200, ZIP)
        elif step == "truncated":
            # Promise the whole archive, deliver a fraction, hang up.
            self.send_response(200)
            self.send_header("Content-Length", str(len(ZIP)))
            self.end_headers()
            self.wfile.write(ZIP[:64])
            self.wfile.flush()
            self.close_connection = True
        elif step == "busy":
            self._send(503, b"busy", {"Retry-After": "0"})
        elif step == "huge":
            self.send_response(200)
            self.send_header("Content-Length", str(10 ** 12))
            self.end_headers()
            self.close_connection = True
        elif step == "gone":
            self._send(404, b"no")

    def _send(self, status, body, headers=None):
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@pytest.fixture
def server(monkeypatch):
    # The sandbox and some CI runners export a proxy; loopback must bypass it.
    for var in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Script)
    httpd.daemon_threads = True
    httpd.script, httpd.hits = [], []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(5)


def _client():
    return HttpClient(allow_http=True, retries=3, timeout=10, sleep=lambda *_: None)


def _url(httpd, name="m.zip"):
    return f"http://127.0.0.1:{httpd.server_address[1]}/{name}"


def test_a_connection_cut_mid_body_is_retried_and_completes(server, tmp_path):
    server.script = ["truncated", "ok"]
    result = _client().download(_url(server), str(tmp_path / "m.zip"))
    assert result.size == len(ZIP)
    assert (tmp_path / "m.zip").read_bytes() == ZIP
    assert len(server.hits) == 2
    assert not (tmp_path / "m.zip.part").exists()


def test_a_503_with_retry_after_is_retried(server, tmp_path):
    server.script = ["busy", "busy", "ok"]
    assert _client().download(_url(server), str(tmp_path / "m.zip")).size == len(ZIP)
    assert len(server.hits) == 3


def test_an_oversized_content_length_is_refused_before_the_body(server, tmp_path):
    server.script = ["huge"]
    with pytest.raises(TooLarge):
        _client().download(_url(server), str(tmp_path / "m.zip"))
    assert not (tmp_path / "m.zip").exists()


def test_a_404_is_typed_and_not_retried(server, tmp_path):
    server.script = ["gone"]
    with pytest.raises(HttpStatusError) as caught:
        _client().download(_url(server), str(tmp_path / "m.zip"))
    assert caught.value.status == 404
    assert len(server.hits) == 1


# Progress and cancellation (ADR-0030): a UI shows bytes as they arrive and can
# stop a download within one chunk, leaving nothing half-written behind.
def test_progress_is_reported_up_to_the_full_size(server, tmp_path):
    server.script = ["ok"]
    seen = []
    _client().download(_url(server), str(tmp_path / "m.zip"),
                       progress=lambda done, total: seen.append((done, total)))
    assert seen and seen[-1] == (len(ZIP), len(ZIP))
    assert [d for d, _t in seen] == sorted(d for d, _t in seen)


def test_a_cancelled_download_stops_and_leaves_no_file(server, tmp_path):
    from iemod_fetch.errors import Cancelled
    server.script = ["ok"]
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        _client().download(_url(server), str(tmp_path / "m.zip"), cancel=cancel)
    assert not (tmp_path / "m.zip").exists()
    assert not (tmp_path / "m.zip.part").exists()
    assert server.hits == []         # cancelled before it starts: not even sent (#61)
