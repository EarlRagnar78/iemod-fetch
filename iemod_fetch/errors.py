"""
Typed errors. Nothing in this package raises or swallows bare Exception.

Each class has a `code`: a stable, machine-readable name that the JSON report
carries (`error_code`) so a front end can decide what to show without parsing
an English message (ADR-0030). The codes are pinned by tests/test_error_codes.py;
renaming one is a breaking change.
"""


class ModFetchError(Exception):
    """Base class for every error this package raises."""
    code = "error"


class ConfigError(ModFetchError):
    """Invalid CLI options, manifest schema, or alias file."""
    code = "config"


class Cancelled(ModFetchError):
    """The run was asked to stop (a UI's cancel button, or Ctrl-C)."""
    code = "cancelled"


class UnsafeName(ConfigError):
    """A manifest/WeiDU name cannot be used as a filesystem component."""
    code = "unsafe_name"


class ManifestError(ConfigError):
    """The manifest is structurally invalid."""
    code = "manifest"


class NetworkError(ModFetchError):
    """Transport-level failure after retries were exhausted."""
    code = "network"


class HttpStatusError(NetworkError):
    """A deterministic HTTP status (4xx) that retrying cannot fix."""
    code = "http_status"

    def __init__(self, url, status, reason=""):
        super().__init__(f"{url}: HTTP {status} {reason}".rstrip())
        self.url, self.status, self.reason = url, status, reason


class InsecureURL(ModFetchError):
    """URL scheme or host is not permitted by policy."""
    code = "insecure_url"


class NotAnArchive(ModFetchError):
    """The server returned something that is not an archive (HTML, JSON, ...)."""
    code = "not_an_archive"

    def __init__(self, url, sniff, final_url=None, note=""):
        super().__init__(f"{url} did not return an archive; got: {sniff!r}{note}")
        self.url = url
        self.sniff = sniff
        # where the redirects ended, when it is another URL
        self.final_url = final_url


class ChecksumMismatch(ModFetchError):
    code = "checksum_mismatch"

    def __init__(self, url, expected, actual):
        super().__init__(f"{url}: sha256 expected {expected}, got {actual}")
        self.expected, self.actual = expected, actual


class TooLarge(ModFetchError):
    """Response exceeded the configured byte ceiling."""
    code = "too_large"


class UnsafeArchive(ModFetchError):
    """Archive member would escape the extraction root, or is a decompression bomb."""
    code = "unsafe_archive"


class ExtractionError(ModFetchError):
    """Archive could not be extracted (unsupported format or missing external tool)."""
    code = "extraction"


class Unresolved(ModFetchError):
    """No download URL could be established without guessing."""
    code = "unresolved"


class InstallConflict(ModFetchError):
    """Destination exists and --force was not given."""
    code = "install_conflict"


class VerificationFailed(ModFetchError):
    """Extracted tree does not contain the .tp2 the mod is supposed to provide."""
    code = "verification_failed"


class NotThisMod(VerificationFailed):
    """The archive holds no .tp2, or another mod's: the artefact, not the install, is wrong."""
