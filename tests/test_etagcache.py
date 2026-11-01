"""
GitHub API answers kept by ETag (GUI-AUDIT M7 item 45, part 2): a run asks
with If-None-Match, and a 304 means the kept answer stands. GitHub's docs, and
a measurement on 2026-10-23: an authorized 304 does not count against the
rate limit (X-RateLimit-Remaining 14984 before and after it).
"""
import io
import json
import os
import urllib.error

import pytest

from conftest import FakeResponse
from iemod_fetch.errors import HttpStatusError, NetworkError
from iemod_fetch.etagcache import ETagCache
from iemod_fetch.net import HttpClient

URL = "https://api.github.com/repos/o/r/releases/latest"


def github(etag='"v1"', body=b'{"tag_name": "v1"}'):
    """GitHub as an opener: 304 when If-None-Match matches, else the body."""
    seen = []

    def answer(req):
        sent = req.get_header("If-none-match")
        seen.append(sent)
        if sent and sent == etag:
            raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, io.BytesIO())
        return FakeResponse(body, headers={"ETag": etag})
    return answer, seen


def client(tmp_path):
    c = HttpClient(sleep=lambda *_: None)
    c.etags = ETagCache(str(tmp_path / "etags"))
    return c


def test_the_second_run_asks_with_the_etag_and_uses_the_kept_answer(fake_opener, tmp_path):
    answer, seen = github()
    fake_opener(default=answer)
    first = client(tmp_path)
    assert first.get_json(URL) == {"tag_name": "v1"} and first.not_modified == 0
    second = client(tmp_path)                    # a new run, the same cache folder
    assert second.get_json(URL) == {"tag_name": "v1"}
    assert seen == [None, '"v1"'] and second.not_modified == 1


def test_a_changed_answer_replaces_the_kept_one(fake_opener, tmp_path):
    answer, _seen = github()
    fake_opener(default=answer)
    client(tmp_path).get_json(URL)
    answer2, seen2 = github(etag='"v2"', body=b'{"tag_name": "v2"}')
    fake_opener(default=answer2)
    assert client(tmp_path).get_json(URL) == {"tag_name": "v2"}
    fake_opener(default=answer2)
    later = client(tmp_path)
    assert later.get_json(URL) == {"tag_name": "v2"} and later.not_modified == 1


def test_only_the_github_api_is_asked_conditionally(fake_opener, tmp_path):
    answer, seen = github()
    fake_opener(default=answer)
    c = client(tmp_path)
    c.get_json("https://example.org/x.json")
    c.get_json("https://example.org/x.json")
    assert seen == [None, None]
    assert not (tmp_path / "etags").exists()       # nothing kept for another host


def test_a_git_tree_named_by_its_commit_is_not_kept(fake_opener, tmp_path):
    """Every new commit of the community data is a new tree URL whose answer
    never changes: keeping it would only grow the folder, one whole tree per
    commit, with nothing to remove it."""
    answer, seen = github(body=b'{"tree": []}')
    fake_opener(default=answer)
    c = client(tmp_path)
    for sha in ("a" * 40, "b" * 40):
        c.get_json(f"https://api.github.com/repos/o/r/git/trees/{sha}?recursive=1")
    assert seen == [None, None]
    assert not (tmp_path / "etags").exists()


def test_a_304_with_nothing_kept_is_an_error_not_an_empty_answer(fake_opener, tmp_path):
    fake_opener(default=lambda req: (_ for _ in ()).throw(
        urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, io.BytesIO())))
    with pytest.raises(HttpStatusError):
        client(tmp_path).get_json(URL)


def test_an_answer_that_is_not_json_is_not_kept(fake_opener, tmp_path):
    answer, _seen = github(body=b"<html>busy</html>")
    fake_opener(default=answer)
    with pytest.raises(NetworkError):
        client(tmp_path).get_json(URL)
    assert ETagCache(str(tmp_path / "etags")).get(URL) is None


@pytest.mark.parametrize("content", ["not json", "[]", '{"url": "https://other", "etag": "x", "body": "{}"}',
                                     json.dumps({"url": URL, "etag": "", "body": "{}"})])
def test_a_damaged_or_foreign_entry_is_ignored(tmp_path, content):
    cache = ETagCache(str(tmp_path))
    cache.put(URL, '"v1"', b"{}")
    with open(cache._path(URL), "w", encoding="utf-8") as fh:
        fh.write(content)
    assert cache.get(URL) is None


@pytest.mark.skipif(os.name == "nt", reason="file modes are POSIX")
def test_the_kept_answers_are_the_owners_only(tmp_path):
    cache = ETagCache(str(tmp_path / "etags"))
    cache.put(URL, '"v1"', json.dumps({"a": 1}).encode())
    assert os.stat(cache._path(URL)).st_mode & 0o077 == 0


def test_the_cache_sits_beside_the_community_data_never_inside(tmp_path):
    """A refresh swaps the data folder whole; the kept answers must survive it."""
    from iemod_fetch import api
    settings = api.Settings(data_dir=str(tmp_path / "data"))
    assert api._etag_dir(settings) == str(tmp_path / "data") + "-http"
