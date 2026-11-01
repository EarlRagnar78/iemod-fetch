"""
Stable error codes (ADR-0030, milestone M1).

A UI decides what to show - "retry", "check your token", "this archive is not
the mod" - from a code, not by parsing an English message that may be
reworded. The codes are part of the public JSON contract: this test pins them,
so changing one is a visible, deliberate act.
"""
import inspect

from iemod_fetch import errors
from iemod_fetch.report import Record, Status

PINNED = {
    "ModFetchError": "error",
    "ConfigError": "config",
    "Cancelled": "cancelled",
    "UnsafeName": "unsafe_name",
    "ManifestError": "manifest",
    "NetworkError": "network",
    "HttpStatusError": "http_status",
    "InsecureURL": "insecure_url",
    "NotAnArchive": "not_an_archive",
    "ChecksumMismatch": "checksum_mismatch",
    "TooLarge": "too_large",
    "UnsafeArchive": "unsafe_archive",
    "ExtractionError": "extraction",
    "Unresolved": "unresolved",
    "InstallConflict": "install_conflict",
    "VerificationFailed": "verification_failed",
    "NotThisMod": "verification_failed",     # a kind of it; the contract keeps one code
}


def _classes():
    return {name: cls for name, cls in inspect.getmembers(errors, inspect.isclass)
            if issubclass(cls, errors.ModFetchError)}


def test_every_error_has_its_own_pinned_code():
    classes = _classes()
    assert set(classes) == set(PINNED), "a new error needs a code here"
    assert {name: cls.code for name, cls in classes.items()} == PINNED


def test_an_instance_carries_its_class_code():
    exc = errors.ChecksumMismatch("https://x/a.zip", "aa", "bb")
    assert exc.code == "checksum_mismatch"


def test_a_failed_record_reports_the_code_in_json():
    record = Record("mod", Status.FAILED, "sha256 mismatch",
                    error_code=errors.ChecksumMismatch.code)
    assert record.to_json()["error_code"] == "checksum_mismatch"
    assert Record("mod", Status.OK).to_json()["error_code"] is None


def test_the_runner_records_why_a_mod_failed_as_a_code(tmp_path):
    """The run report says checksum_mismatch, not just an English sentence."""
    from test_events import Client, _plan, _runner

    class Tampered(Client):
        def download(self, url, dest_path, **_kw):
            raise errors.ChecksumMismatch(url, "aa" * 32, "bb" * 32)

    report = _runner(tmp_path, Tampered()).run(_plan())
    assert [(r.status, r.error_code) for r in report.records] == [
        (Status.FAILED, "checksum_mismatch")]
