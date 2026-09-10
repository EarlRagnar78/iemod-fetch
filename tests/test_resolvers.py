"""Resolution without guessing - the fix for legacy defects L7, L11, L12."""
import pytest

from conftest import FakeResponse
from iemod_fetch.errors import HttpStatusError, NetworkError
from iemod_fetch.manifest import ModSource
from iemod_fetch.resolvers import (GitHubResolver, LandingPageResolver,
                                   normalize_dropbox, repo_from_url)


class StubClient:
    """Records every URL it is asked for, so 'did it search?' is assertable."""

    def __init__(self, json_map=None, pages=None):
        self.json_map = json_map or {}
        self.pages = pages or {}
        self.calls = []

    def get_json(self, url):
        self.calls.append(url)
        for needle, payload in self.json_map.items():
            if needle in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        # match the real client: a deterministic 404 is typed and carries .status
        raise HttpStatusError(url, 404, "Not Found")

    def open(self, url):
        self.calls.append(url)
        for needle, resp in self.pages.items():
            if needle in url:
                return resp() if callable(resp) else resp
        raise NetworkError(f"404 {url}")


def release(assets, tag="v1.2.3", **extra):
    payload = {"tag_name": tag,
               "assets": [{"name": n, "browser_download_url":
                           f"https://github.com/o/r/releases/download/{tag}/{n}"}
                          for n in assets]}
    payload.update(extra)
    return payload


def src(**kw):
    kw.setdefault("key", "DlcMerger")
    kw.setdefault("name", "DLC Merger")
    return ModSource(**kw)


# ---------------------------------------------------------------- selection
def test_iemod_is_preferred_over_zip():
    client = StubClient({"releases/latest": release(["mod.zip", "mod.iemod"])})
    res = GitHubResolver(client).resolve(src(github="Argent77/A7-DlcMerger"))
    assert res.ok and res.candidate.filename == "mod.iemod"
    assert res.candidate.version == "v1.2.3"


def test_exe_assets_are_ignored_unless_allowed():
    client = StubClient({"releases/latest": release(["setup.exe"])})
    assert not GitHubResolver(client).resolve(src(github="o/r")).ok
    assert GitHubResolver(client, allow_exe=True).resolve(src(github="o/r")).ok


def test_multiple_candidate_assets_warn_and_are_deterministic():
    client = StubClient({"releases/latest": release(["b-mod.zip", "a-mod.zip"])})
    res = GitHubResolver(client).resolve(src(github="o/r"))
    assert res.candidate.filename == "a-mod.zip"          # stable, not arbitrary
    assert any("Pin it" in w for w in res.warnings)
    assert res.alternatives


def test_a_pinned_asset_wins():
    client = StubClient({"releases/latest": release(["mod.iemod", "mod-docs.zip"])})
    res = GitHubResolver(client).resolve(src(github="o/r", asset="mod-docs.zip"))
    assert res.candidate.filename == "mod-docs.zip"


def test_a_pinned_asset_that_is_absent_fails_loudly():
    client = StubClient({"releases/latest": release(["mod.zip"])})
    res = GitHubResolver(client).resolve(src(github="o/r", asset="nope.zip"))
    assert not res.ok and "not in release" in res.reason


def test_a_pinned_tag_is_requested_verbatim():
    client = StubClient({"releases/tags/v1.0.0": release(["m.zip"], tag="v1.0.0")})
    res = GitHubResolver(client).resolve(src(github="o/r", release_tag="v1.0.0"))
    assert res.ok and "releases/tags/v1.0.0" in client.calls[0]


def test_source_snapshot_fallback_is_flagged_as_probably_not_installable():
    client = StubClient({"releases/latest": release(
        [], zipball_url="https://api.github.com/repos/o/r/zipball/v1")})
    res = GitHubResolver(client).resolve(src(github="o/r"))
    assert res.ok and res.candidate.origin == "source-snapshot"
    assert any("NOT a ready-to-install" in w for w in res.warnings)


# ---------------------------------------------------------------- no guessing
def test_an_unresolvable_repo_never_falls_back_to_github_search():
    """Legacy defect L7: this installed the top search hit."""
    client = StubClient({})                      # every API call 404s
    res = GitHubResolver(client).resolve(src(key="eefixpack", github="o/missing"))
    assert not res.ok
    assert not any("search" in url for url in client.calls)


def test_a_github_profile_url_is_not_treated_as_a_repository():
    """Real manifest entry 'FowlWish' -> https://github.com/Glittergear"""
    res = GitHubResolver(StubClient()).resolve(
        src(key="FowlWish", url="https://github.com/Glittergear"))
    assert not res.ok and "profile" in res.reason


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/Argent77/A7-DlcMerger", "Argent77/A7-DlcMerger"),
    ("https://github.com/Argent77/A7-DlcMerger/releases", "Argent77/A7-DlcMerger"),
    ("https://github.com/Glittergear", None),
    ("https://gitlab.com/a/b", None),
])
def test_repo_extraction_is_exact(url, expected):
    assert repo_from_url(url) == expected


# -------------------------------------------------------------- landing pages
def test_offsite_advert_link_is_not_selected(fake_opener):
    """Legacy defect L12: the first matching link won, whatever host it was on."""
    html = (b"<html>"
            b"<a href='https://third-party.example.net/mirror/mod-v2.zip'>download now</a>"
            b"<a href='/files/real-mod.zip'>the mod</a></html>")
    client = StubClient(pages={"weaselmods": lambda: FakeResponse(
        html, headers={"Content-Type": "text/html"},
        url="https://downloads.weaselmods.net/p/")})
    res = LandingPageResolver(client).resolve(
        src(url="https://downloads.weaselmods.net/p/"))
    assert res.candidate.url == "https://downloads.weaselmods.net/files/real-mod.zip"
    assert any("off-site" in w for w in res.warnings)


def test_an_executable_advert_is_filtered_out_entirely():
    html = (b"<html><a href='https://ads.example.net/free-download.exe'>download</a>"
            b"<a href='/files/real-mod.zip'>the mod</a></html>")
    client = StubClient(pages={"weaselmods": lambda: FakeResponse(
        html, headers={"Content-Type": "text/html"},
        url="https://downloads.weaselmods.net/p/")})
    res = LandingPageResolver(client).resolve(
        src(url="https://downloads.weaselmods.net/p/"))
    assert res.candidate.url.endswith("/files/real-mod.zip")
    assert all(".exe" not in c.url for c in res.alternatives)


def test_a_page_with_only_offsite_links_requires_a_human(fake_opener):
    html = b"<html><a href='https://cdn.example.net/m.zip'>download</a></html>"
    client = StubClient(pages={"weaselmods": lambda: FakeResponse(
        html, headers={"Content-Type": "text/html"},
        url="https://downloads.weaselmods.net/p/")})
    res = LandingPageResolver(client).resolve(
        src(url="https://downloads.weaselmods.net/p/"))
    assert not res.ok and "off-site" in res.reason
    assert res.alternatives[0].url == "https://cdn.example.net/m.zip"


def test_wpdm_download_link_is_recognised():
    html = (b"<html><a href='/?wpdmdl=4321&refresh=1'>Download</a>"
            b"<a href='/login'>Log in</a></html>")
    client = StubClient(pages={"weaselmods": lambda: FakeResponse(
        html, headers={"Content-Type": "text/html"},
        url="https://downloads.weaselmods.net/p/")})
    res = LandingPageResolver(client).resolve(
        src(url="https://downloads.weaselmods.net/p/"))
    assert "wpdmdl=4321" in res.candidate.url


def test_login_links_are_never_chosen():
    html = b"<html><a href='/login/?do=download'>Log in to download</a></html>"
    client = StubClient(pages={"g3": lambda: FakeResponse(
        html, headers={"Content-Type": "text/html"},
        url="https://www.gibberlings3.net/g3/")})
    res = LandingPageResolver(client).resolve(src(url="https://www.gibberlings3.net/g3/"))
    assert not res.ok


def test_a_direct_archive_url_with_a_query_string_is_used_verbatim():
    """Legacy defect L11 appended '/' to the query, corrupting the URL."""
    url = "https://www.gibberlings3.net/files/file/1-x/m.zip?do=download&csrf=abc"
    res = LandingPageResolver(StubClient()).resolve(src(url=url))
    assert res.candidate.url == url


@pytest.mark.parametrize("given,expected_pairs", [
    ("https://www.dropbox.com/s/abc/m.zip?dl=0", {"dl": "1"}),
    ("https://www.dropbox.com/scl/fi/x/m.zip?rlkey=KEY&st=ST&dl=0",
     {"rlkey": "KEY", "st": "ST", "dl": "1"}),
    ("https://www.dropbox.com/s/abc/m.zip", {"dl": "1"}),
])
def test_dropbox_normalisation_preserves_the_rest_of_the_query(given, expected_pairs):
    import urllib.parse
    out = normalize_dropbox(given)
    assert dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(out).query)) == expected_pairs


def test_a_404_from_the_api_becomes_a_readable_manual_reason_not_a_crash():
    """A repository with no published releases is routine, not an internal error."""
    from iemod_fetch.errors import HttpStatusError
    client = StubClient({"releases/latest": HttpStatusError(
        "https://api.github.com/repos/o/r/releases/latest", 404, "Not Found")})
    res = GitHubResolver(client).resolve(src(github="o/r"))
    assert not res.ok
    assert "no published release" in res.reason


def test_a_403_explains_the_rate_limit():
    from iemod_fetch.errors import HttpStatusError
    client = StubClient({"releases/latest": HttpStatusError(
        "https://api.github.com/repos/o/r/releases/latest", 403, "Forbidden")})
    res = GitHubResolver(client).resolve(src(github="o/r"))
    assert not res.ok and "GH_TOKEN" in res.reason


# ================= regressions from the first real Windows run =================
def weasel_page(slug="shades-of-the-sword-coast", extra=b""):
    """A WeaselMods download page: a sidebar listing every other mod on the site."""
    siblings = b"".join(
        f'<a href="/download/{other}/">{other}</a>'.encode()
        for other in ("alabaster-sands", "bridges-block", "innershade", "oozes-lounge",
                      "southern-edge", "tangled-oak-isle", "the-white-queen"))
    return (b"<html><nav>" + siblings + b"</nav><main>"
            + extra + b"</main></html>")


def landing(url, body):
    return StubClient(pages={url: lambda: FakeResponse(
        body, headers={"Content-Type": "text/html"}, url=url)})


def test_a_sidebar_of_other_mods_resolves_to_nothing(fake_opener):
    """
    THE bug from the first real run: 20 WeaselMods mods all resolved to
    `/download/alabaster-sands/` - the alphabetically first nav entry - because
    a bare `/download/<slug>/` link scored 20 and nothing scored higher.
    """
    page = "https://downloads.weaselmods.net/download/shades-of-the-sword-coast/"
    res = LandingPageResolver(landing(page, weasel_page())).resolve(
        src(key="SotSC", url=page))

    assert not res.ok
    assert "alabaster-sands" not in (res.candidate.url if res.candidate else "")
    assert "scored high enough" in res.reason


def test_the_real_download_link_still_wins_on_that_same_page(fake_opener):
    page = "https://downloads.weaselmods.net/download/shades-of-the-sword-coast/"
    body = weasel_page(extra=b'<a href="/?wpdmdl=9911&refresh=1">Download</a>')
    res = LandingPageResolver(landing(page, body)).resolve(src(key="SotSC", url=page))

    assert res.ok and "wpdmdl=9911" in res.candidate.url


def test_a_sibling_that_is_a_real_archive_is_still_refused(fake_opener):
    """Another mod's zip is another mod's zip, however well it scores."""
    page = "https://host.example/mods/my-mod/"
    body = b'<a href="/mods/someone-elses-mod.zip">download</a>'
    res = LandingPageResolver(landing(page, body)).resolve(src(url=page))
    assert not res.ok


def test_a_link_carrying_this_page_slug_is_preferred(fake_opener):
    page = "https://host.example/files/my-mod/"
    body = (b'<a href="/dl/generic.zip">download</a>'
            b'<a href="/dl/my-mod-v3.zip">download</a>')
    res = LandingPageResolver(landing(page, body)).resolve(src(url=page))
    assert res.candidate.url.endswith("my-mod-v3.zip")


@pytest.mark.parametrize("given,expected", [
    ("https://forums.beamdog.com/home/leaving?allowTrusted=1&target=http%3A%2F%2Fd.example%2Fm.zip",
     "http://d.example/m.zip"),
    ("https://forum.example/redirect/?url=https%3A%2F%2Fx.example%2Fa.rar",
     "https://x.example/a.rar"),
    ("https://host.example/download/mod.zip", "https://host.example/download/mod.zip"),
    ("https://host.example/leaving", "https://host.example/leaving"),
])
def test_forum_interstitials_are_unwrapped(given, expected):
    from iemod_fetch.resolvers import unwrap_redirect
    assert unwrap_redirect(given) == expected


# ------------------------------------------------ repositories with no releases
def notfound(status=404):
    from iemod_fetch.errors import HttpStatusError
    return HttpStatusError("https://api.github.com/x", status, "Not Found")


def test_a_repo_with_no_releases_falls_back_to_its_default_branch():
    """5 real mods died here: eefixpack, TGC1e, TOA, Margarita, fight-the-heavens."""
    client = StubClient({"releases/latest": notfound(),
                         "repos/gibberlings3/EE_Fixpack": {"default_branch": "master"}})
    res = GitHubResolver(client).resolve(src(key="eefixpack",
                                             github="gibberlings3/EE_Fixpack"))
    assert res.ok
    assert res.candidate.origin == "source-snapshot"
    assert res.candidate.url.endswith("/zipball/master")
    assert any("publishes no releases" in w for w in res.warnings)


def test_the_snapshot_fallback_tells_you_to_pin_it():
    client = StubClient({"releases/latest": notfound(),
                         "repos/o/r": {"default_branch": "main"}})
    res = GitHubResolver(client).resolve(src(github="o/r"))
    assert any("release_tag" in w for w in res.warnings)


def test_a_pinned_tag_never_falls_back_to_a_branch():
    """If you asked for v1.0 you get v1.0 or nothing."""
    client = StubClient({"releases/tags/v1.0": notfound(),
                         "repos/o/r": {"default_branch": "main"}})
    res = GitHubResolver(client).resolve(src(github="o/r", release_tag="v1.0"))
    assert not res.ok


def test_a_repository_that_does_not_exist_still_fails():
    res = GitHubResolver(StubClient({})).resolve(src(github="o/missing"))
    assert not res.ok and "no published release" in res.reason
