"""
premeta against the real GitHub (ADR-0037): the case-insensitive fallback.

The unit tests drive premeta with fake clients; this script asks GitHub
itself, through the tool's own HttpClient, for mods whose metadata ini only a
listing finds (their spelling differs from the tp2's in case), one found on
raw.githubusercontent.com directly, and one with no ini at all. It runs in the
nightly workflow with the workflow's token; a quota or network failure is
reported as inconclusive, not as a pass.

    python tools/premeta_live_check.py           # exit 0 pass, 1 fail, 2 inconclusive
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from iemod_fetch import premeta  # noqa: E402
from iemod_fetch.auth import resolve_credential  # noqa: E402
from iemod_fetch.errors import ModFetchError  # noqa: E402
from iemod_fetch.net import HttpClient  # noqa: E402

# (what is wanted, the ini's path in the repository or None, whether only a
# listing can find it). Checked by `git ls-tree` on 2026-10-22.
CASES = [
    # the tp2 is DeitiesOffaerun.tp2, the ini Deitiesoffaerun.ini
    (premeta.Wanted("DeitiesOfFaerun", "DeitiesOfFaerun/DeitiesOffaerun.tp2",
                    "Raduziel/Deities-Of-Faerun"), "DeitiesOfFaerun/Deitiesoffaerun.ini", True),
    # a WeiDU log spelling the path in capitals: the folder is `RoT`
    (premeta.Wanted("ROT", "ROT/SETUP-ROT.TP2", "Spellhold-Studios/Region-of-Terror"),
     "RoT/rot.ini", True),
    # ascension.ini holds the mod's own settings and, after them, [Metadata]
    (premeta.Wanted("ASCENSION", "ASCENSION/ASCENSION.TP2", "InfinityMods/Ascension"),
     "ascension/ascension.ini", True),
    # lower-case spelling, found without the API
    (premeta.Wanted("RoT", "RoT/setup-RoT.tp2", "Spellhold-Studios/Region-of-Terror"),
     "RoT/rot.ini", False),
    # no metadata ini: only a listing may say so
    (premeta.Wanted("ToA", "ToA/setup-toa.TP2", "Gitjas/ToA"), None, True),
]
# A file each repository must still have: a gone or private repository lists
# as 404, which premeta reads as "no ini" - the check must not pass on that.
PRESENT = {"raduziel/deities-of-faerun": "DeitiesOfFaerun/DeitiesOffaerun.tp2",
           "spellhold-studios/region-of-terror": "RoT/setup-RoT.tp2",
           "infinitymods/ascension": "ascension/Ascension.tp2",
           "gitjas/toa": "ToA/setup-toa.TP2"}


class Counting:
    """The real client, counting the contents-API listings asked for."""

    def __init__(self, client):
        self.client = client
        self.listings = 0

    def get_json(self, url):
        self.listings += 1
        return self.client.get_json(url)

    def read_bytes(self, url, limit=None):
        return self.client.read_bytes(url, limit=limit)


def main() -> int:
    credential = resolve_credential(use_gh=False, use_git_credential=False)
    print(f"credential: {credential.describe()}")
    client = HttpClient(token=credential.token, retries=2, timeout=30)
    failures, inconclusive = [], []
    with tempfile.TemporaryDirectory() as data_dir:
        for wanted, path, listed in CASES:
            cache = premeta.MetadataCache(data_dir)
            counting = Counting(client)
            found, missing, problems = premeta.fetch(counting, cache, [wanted], now=time.time())
            entry = cache.entries.get(premeta.cache_key(wanted)) or {}
            got = entry.get("path")
            line = (f"{wanted.repo}: {wanted.tp2_file} -> {got} "
                    f"({counting.listings} listing(s))")
            if entry.get("problem"):
                # one repository's own error (a 451, a file over the cap):
                # premeta behaved, but the case no longer holds
                failures.append(f"{line}: {entry['problem']}")
                print(f"FAIL {line}: {entry['problem']}")
                continue
            if problems:
                inconclusive.append(f"{line}: {'; '.join(problems)}")
                print(f"?    {line}: {'; '.join(problems)}")
                continue
            ok = got == path and (found == 1) == (path is not None) and \
                (counting.listings > 0) == listed
            if path is not None:
                ok = ok and cache.get(wanted) is not None   # it parses, with an order
            else:
                try:
                    present = premeta._raw(client, wanted.repo.lower(),
                                           PRESENT[wanted.repo.lower()]) is not None
                except ModFetchError as exc:
                    if premeta._network_down(exc):
                        inconclusive.append(f"{line}: {exc}")
                        print(f"?    {line}: {exc}")
                        continue
                    present = False
                    line += f"; {exc}"
                if not present:
                    ok = False
                    line += "; the repository or its tp2 is gone"
            print(f"{'ok  ' if ok else 'FAIL'} {line}")
            if not ok:
                failures.append(f"{line}; expected {path}, listing {'yes' if listed else 'no'}")
    if failures:
        print("\n".join(["", "failed:"] + failures))
        return 1
    if inconclusive:
        print("\n".join(["", "inconclusive (network or quota):"] + inconclusive))
        return 2
    print(f"\nall {len(CASES)} cases as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
