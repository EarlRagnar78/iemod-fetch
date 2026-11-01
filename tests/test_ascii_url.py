"""Links typed with accents are sent as http.client needs them (ADR-0039 measurement)."""
import pytest

from iemod_fetch.errors import NetworkError


def test_a_url_typed_with_accents_is_sent_percent_encoded():
    # lcc-docs links Derats_Ogre to .../BG2_Mes_créations: http.client refused
    # it with UnicodeEncodeError and the mod failed as an internal error
    from iemod_fetch.net import HttpClient, ascii_url
    assert ascii_url("https://h.example/f/BG2_Mes_créations?q=é") == \
        "https://h.example/f/BG2_Mes_cr%C3%A9ations?q=%C3%A9"
    assert ascii_url("https://exämple.org/a") == "https://xn--exmple-cua.org/a"
    assert ascii_url("https://github.com/o/r/a%20b") == "https://github.com/o/r/a%20b"
    sent = []

    class Opener:
        def open(self, req, timeout=None):
            sent.append(req.full_url)
            raise OSError("stop here")
    client = HttpClient(retries=1)
    client._opener = Opener()
    with pytest.raises(NetworkError):
        client.read_bytes("https://h.example/f/BG2_Mes_créations")
    assert sent == ["https://h.example/f/BG2_Mes_cr%C3%A9ations"]
