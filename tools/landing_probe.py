"""
What a mod's landing page gives the tool, for diagnosing a page the resolver
gets wrong (ADR-0039). Fetched with the tool's own HttpClient - its headers,
redirects and limits - from wherever the network allows (the download-sources
workflow; a session sandbox cannot reach the mod sites).

    python tools/landing_probe.py URL [URL ...]

For each URL: the status, final URL, content type and headers that matter;
every element whose attributes mention a download (href, data-*, action,
onclick), trimmed; and what LandingPageResolver picks from it.
"""
import os
import sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from iemod_fetch.errors import ModFetchError  # noqa: E402
from iemod_fetch.manifest import ModSource  # noqa: E402
from iemod_fetch.net import HttpClient  # noqa: E402
from iemod_fetch.resolvers import _WPDM_PACKAGE, LandingPageResolver  # noqa: E402

WORDS = ("download", "wpdm", "dl=", ".zip", ".rar", ".7z", ".iemod", "package")
HEADERS = ("Content-Type", "Content-Disposition", "Content-Length", "Location", "Server")


class Elements(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found = []

    def handle_starttag(self, tag, attrs):
        if tag in ("link", "meta", "script", "style"):
            return                      # the head's assets, not a download
        text = " ".join(f'{k}="{v}"' for k, v in attrs if v is not None)
        if any(word in text.lower() for word in WORDS):
            self.found.append(f"<{tag} {text}>"[:300])


def probe(client, url):
    print(f"== {url}")
    try:
        with client.open(url) as resp:
            final = resp.geturl()
            print(f"   status {getattr(resp, 'status', '?')}, final {final}")
            for name in HEADERS:
                if resp.headers.get(name):
                    print(f"   {name}: {resp.headers.get(name)}")
            cookies = resp.headers.get_all("Set-Cookie") or []
            if cookies:
                print(f"   cookies set: {', '.join(c.split('=', 1)[0] for c in cookies)}")
            kind = (resp.headers.get("Content-Type") or "").lower()
            body = resp.read(2 * 1024 * 1024) if "html" in kind else b""
    except (ModFetchError, OSError) as exc:
        print(f"   error: {exc}")
        return
    if body:
        parser = Elements()
        parser.feed(body.decode("utf-8", errors="replace"))
        print(f"   {len(body):,} bytes of HTML; {len(parser.found)} element(s) about a download:")
        for element in parser.found[:60]:
            print(f"     {element}")
        post = _WPDM_PACKAGE.search(body.decode("utf-8", errors="replace"))
        if post:
            # what the resolver gives a WordPress Download Manager package page,
            # built as it builds it: from the page's final URL. Fetching it
            # counts as one download on the site.
            direct = f"{final.split('?')[0].split('#')[0]}?wpdmdl={post.group(1)}"
            print(f"   WPDM package {post.group(1)}; trying {direct}")
            try:
                with client.open(direct) as got:
                    print(f"     status {getattr(got, 'status', '?')}, final {got.geturl()}")
                    for name in HEADERS:
                        if got.headers.get(name):
                            print(f"     {name}: {got.headers.get(name)}")
                    print(f"     first bytes: {got.read(8)!r}")
            except (ModFetchError, OSError) as exc:
                print(f"     error: {exc}")
    picked = LandingPageResolver(client).resolve(ModSource(key="probe", name="probe", url=url))
    if picked.ok:
        print(f"   resolver picks: {picked.candidate.url} ({picked.candidate.origin})")
    else:
        print(f"   resolver: {picked.reason}")


def main(argv=None) -> int:
    urls = sys.argv[1:] if argv is None else argv
    client = HttpClient(retries=2, timeout=30)
    for url in urls:
        probe(client, url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
