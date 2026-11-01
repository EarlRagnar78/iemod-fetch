"""
BIO share codes: import and export the format, nothing else (M2).

Born2BSalty's Infinity Orchestrator (BIO, GPL-3.0) shares a mod list as one
line of text:

    BIO-MODLIST-V1:<base64url, no padding, of the zlib-deflated JSON payload>

and the payload, `format_version` 1, carries the WeiDU logs per game slot
(`weidu_logs.bgee` / `.bg2ee` / `.iwdee`), `game_install` (EET, BGEE, BG2EE,
IWDEE), `install_mode`, and BIO's own extras: download overrides, pinned
refs, mod configuration files, name, author, description, fork history. This
module reads and writes that format. It was written from the format, read at
BIO 33800cc; no BIO code is copied (GUI-AUDIT, "explicitly not planned").

Nothing is lost either way. A code decodes to its whole payload, and the
payload encodes back to the same code; the WeiDU logs in it become a
selection (ADR-0030), and a selection exported on top of an imported payload
keeps every field this tool does not use.
"""
import base64
import binascii
import json
import zlib
from dataclasses import dataclass

from .errors import ConfigError
from .selection import Selection, parse_selection, selection_from_logs, selection_to_json
from .weidu import parse_weidu_log

PREFIX = "BIO-MODLIST-V1:"
FORMAT_VERSION = 1
MAX_CODE_CHARS = 8 * 1024 * 1024          # the text pasted in
MAX_PAYLOAD_BYTES = 32 * 1024 * 1024      # after inflating: a zip bomb stops here

# game_install -> the payload slots it fills, in install order, and the game
# each slot's log installs onto in a selection.
SLOTS: dict[str, tuple[tuple[str, str], ...]] = {
    "EET": (("bgee", "BGEE"), ("bg2ee", "EET")),
    "BGEE": (("bgee", "BGEE"),),
    "BG2EE": (("bg2ee", "BG2EE"),),
    "IWDEE": (("iwdee", "IWDEE"),),
}
# BIO wrote an IWDEE list in the first slot (`bgee`) before it had `iwdee`.
_FIRST_SLOT_FALLBACK = {"iwdee": "bgee"}


@dataclass
class BioModlist:
    payload: dict

    @property
    def game_install(self) -> str:
        return str(self.payload.get("game_install", ""))

    @property
    def name(self) -> str | None:
        value = self.payload.get("name")
        return value if isinstance(value, str) else None

    def logs(self) -> list[tuple[str, str]]:
        """(game, WeiDU.log text) per filled slot, in install order."""
        texts = self.payload.get("weidu_logs") or {}
        out = []
        for slot, game in SLOTS.get(self.game_install, ()):
            text = texts.get(slot)
            if not (isinstance(text, str) and text.strip()) and slot in _FIRST_SLOT_FALLBACK:
                text = texts.get(_FIRST_SLOT_FALLBACK[slot])
            if isinstance(text, str) and text.strip():
                out.append((game, text))
        return out

    def to_selection(self) -> Selection:
        logs = [(game, parse_weidu_log(text, source=f"BIO {game} log"))
                for game, text in self.logs()]
        if not any(parsed.mods for _game, parsed in logs):
            raise ConfigError("BIO share code: it holds no WeiDU entries to import")
        for _game, parsed in logs:
            if parsed.warnings:
                raise ConfigError(f"BIO share code: {parsed.warnings[0]}")
        # A code is a stranger's text: every tp2 path goes through selection.json's
        # own checks, so `~../../evil.tp2~` is refused before WeiDU could run it.
        return parse_selection(selection_to_json(selection_from_logs(logs)),
                               source="BIO share code")


def _b64url_decode(text: str) -> bytes:
    compact = "".join(text.split())
    if any(c in compact for c in "+/="):
        raise ConfigError("BIO share code: not base64url (it has +, / or =)")
    try:
        return base64.urlsafe_b64decode(compact + "=" * (-len(compact) % 4))
    except (binascii.Error, ValueError):
        raise ConfigError("BIO share code: its base64url text is damaged") from None


def _inflate(data: bytes) -> bytes:
    inflater = zlib.decompressobj()
    try:
        out = inflater.decompress(data, MAX_PAYLOAD_BYTES)
    except zlib.error:
        raise ConfigError("BIO share code: its compressed data is damaged") from None
    if inflater.unconsumed_tail:
        raise ConfigError(f"BIO share code: the payload is over "
                          f"{MAX_PAYLOAD_BYTES // (1024 * 1024)} MiB; refused")
    if not inflater.eof:
        raise ConfigError("BIO share code: it is cut short")
    return out


def decode_share_code(code: str) -> BioModlist:
    """The payload of a `BIO-MODLIST-V1:` code; ConfigError says what is wrong."""
    text = code.strip()
    if len(text) > MAX_CODE_CHARS:
        raise ConfigError("BIO share code: too long; refused")
    if not text.startswith(PREFIX):
        raise ConfigError(f"BIO share code: it must start with {PREFIX}")
    raw = _inflate(_b64url_decode(text[len(PREFIX):]))
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ConfigError(f"BIO share code: the payload is not JSON ({exc})") from None
    if not isinstance(payload, dict):
        raise ConfigError("BIO share code: the payload is not an object")
    if payload.get("format_version") != FORMAT_VERSION:
        raise ConfigError(f"BIO share code: format_version "
                          f"{payload.get('format_version')!r} is not supported; "
                          f"this version reads {FORMAT_VERSION}")
    if payload.get("game_install") not in SLOTS:
        raise ConfigError(f"BIO share code: game_install {payload.get('game_install')!r} "
                          f"is not one of {sorted(SLOTS)}")
    return BioModlist(payload)


def encode_share_code(modlist: BioModlist) -> str:
    """The code BIO reads: compact JSON in its own key order, deflated, base64url."""
    text = json.dumps(modlist.payload, ensure_ascii=False, separators=(",", ":"))
    packed = zlib.compress(text.encode("utf-8"))
    return PREFIX + base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")


def _game_install(games: list[str]) -> str:
    wanted = set(games)
    for install, slots in SLOTS.items():
        if wanted == {game for _slot, game in slots}:
            return install
    if wanted == {"EET"}:
        return "EET"
    raise ConfigError(f"a BIO share code holds an EET, BGEE, BG2EE or IWDEE list; "
                      f"this selection is for {sorted(wanted)}")


def modlist_from_selection(selection: Selection, base: BioModlist | None = None,
                           tool_version: str = "") -> BioModlist:
    """
    A BIO payload for `selection`. Given `base` (an imported code), every field
    but the WeiDU logs and game_install is kept as it was.
    """
    logs = {log.game: log.text for log in selection.weidu_logs()}
    install = _game_install(list(logs))
    payload = dict(base.payload) if base else {
        "format_version": FORMAT_VERSION,
        "bio_version": "",
        "game_install": install,
        "install_mode": "install_exactly_from_weidu_logs",
        "weidu_logs": {},
    }
    if tool_version and not base:
        payload["exported_by"] = f"iemod-fetch {tool_version}"
    payload["game_install"] = install
    payload["weidu_logs"] = {slot: logs[game] for slot, game in SLOTS[install]
                             if game in logs}
    return BioModlist(payload)
