"""Typed errors. Nothing in this package raises or swallows bare Exception."""


class ModFetchError(Exception):
    """Base class for every error this package raises."""


class ConfigError(ModFetchError):
    """Invalid CLI options, manifest schema, or alias file."""


class UnsafeName(ConfigError):
    """A manifest/WeiDU name cannot be used as a filesystem component."""


class ManifestError(ConfigError):
    """The manifest is structurally invalid."""


class NetworkError(ModFetchError):
    """Transport-level failure after retries were exhausted."""


class HttpStatusError(NetworkError):
    """A deterministic HTTP status (4xx) that retrying cannot fix."""

    def __init__(self, url, status, reason=""):
        super().__init__(f"{url}: HTTP {status} {reason}".rstrip())
        self.url, self.status, self.reason = url, status, reason


class InsecureURL(ModFetchError):
    """URL scheme or host is not permitted by policy."""


class NotAnArchive(ModFetchError):
    """The server returned something that is not an archive (HTML, JSON, ...)."""

    def __init__(self, url, sniff):
        super().__init__(f"{url} did not return an archive; got: {sniff!r}")
        self.url = url
        self.sniff = sniff


class ChecksumMismatch(ModFetchError):
    def __init__(self, url, expected, actual):
        super().__init__(f"{url}: sha256 expected {expected}, got {actual}")
        self.expected, self.actual = expected, actual


class TooLarge(ModFetchError):
    """Response exceeded the configured byte ceiling."""


class UnsafeArchive(ModFetchError):
    """Archive member would escape the extraction root, or is a decompression bomb."""


class ExtractionError(ModFetchError):
    """Archive could not be extracted (unsupported format or missing external tool)."""


class Unresolved(ModFetchError):
    """No download URL could be established without guessing."""


class InstallConflict(ModFetchError):
    """Destination exists and --force was not given."""


class VerificationFailed(ModFetchError):
    """Extracted tree does not contain the .tp2 the mod is supposed to provide."""
