"""
Game folders, verified before a plan is installed onto them (ADR-0026).

Which game a folder holds is decided exactly as WeiDU's GAME_IS decides it
(WeiDU src/tppe.ml, PE_GameIs): by whether a marker resource exists, looked up
in override/ first and then in chitin.key -

    BGEE   oh1000.are, and not oh6000.are, and not eet.flag
    BG2EE  oh6000.are, and not eet.flag
    EET    eet.flag  (written to override/ by the EET core, EET.tp2:2797)

EET's own requirements come from its readme (readme-EET.html): the core needs
"a clean BG2:EE installation"; the BG:EE side needs Siege of Dragonspear, which
EET verifies through `movies/sodcin05.wbm`, and which GOG and Steam ship as a
DLC archive that DlcMerger must merge before any other mod. DlcMerger looks for
`sod-dlc.zip` in the game folder, `dlc/` and `workshop/` (as `.mod`) - and in
the user's documents folder, which is not looked at here.

Not checked, and said so: the patch level (EET asks for v2.6.6.0), and whether
the game data is intact.
"""
import os
import struct
from dataclasses import dataclass, field

_MAX_KEY_BYTES = 64 * 1024 * 1024
_MAX_RESOURCE_BYTES = 16 * 1024 * 1024
_TYPES = {"spl": 0x3EE, "ids": 0x3F0, "are": 0x3F2, "2da": 0x3F4}
MARKERS = {"bgee": "oh1000.are", "bg2ee": "oh6000.are", "eet": "eet.flag"}
SOD_MOVIE = os.path.join("movies", "sodcin05.wbm")
SOD_ARCHIVES = (("sod-dlc.zip",), ("dlc", "sod-dlc.zip"), ("workshop", "sod-dlc.mod"))


def _find(root: str, *parts: str) -> str | None:
    """A path under `root`, each part matched case-insensitively (Linux)."""
    current = root
    for part in parts:
        direct = os.path.join(current, part)
        if os.path.exists(direct):
            current = direct
            continue
        try:
            match = next((e for e in os.listdir(current) if e.lower() == part.lower()),
                         None)
        except OSError:
            return None
        if match is None:
            return None
        current = os.path.join(current, match)
    return current


def key_resources(game_dir: str) -> set[tuple[str, int]]:
    """(resref, type) of every resource chitin.key lists; empty if unreadable."""
    path = _find(game_dir, "chitin.key")
    if path is None or os.path.getsize(path) > _MAX_KEY_BYTES:
        return set()
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 24 or data[:8] != b"KEY V1  ":
        return set()
    _bifs, count, _bif_offset, offset = struct.unpack_from("<IIII", data, 8)
    out: set[tuple[str, int]] = set()
    for i in range(count):
        start = offset + 14 * i
        if start + 14 > len(data):
            break
        name = data[start:start + 8].split(b"\0", 1)[0].decode("latin-1").lower()
        (kind,) = struct.unpack_from("<H", data, start + 8)
        out.add((name, kind))
    return out


def _key(game_dir: str) -> bytes | None:
    path = _find(game_dir, "chitin.key")
    if path is None or os.path.getsize(path) > _MAX_KEY_BYTES:
        return None
    with open(path, "rb") as fh:
        data = fh.read()
    return data if len(data) >= 24 and data[:8] == b"KEY V1  " else None


def read_resource(game_dir: str, resource: str) -> bytes | None:
    """
    A resource as the game sees it: override/ first, else the BIFF that
    chitin.key points to - the lookup WeiDU's load_resource makes. None when
    it is in neither, or its BIFF is compressed (BIFC, classic games only) or
    unreadable: nothing is guessed.
    """
    override = _find(game_dir, "override", resource)
    if override is not None and os.path.isfile(override):
        if os.path.getsize(override) > _MAX_RESOURCE_BYTES:
            return None
        with open(override, "rb") as fh:
            return _plain(fh.read())
    name, _dot, ext = resource.lower().rpartition(".")
    data = _key(game_dir)
    if data is None or ext not in _TYPES:
        return None
    bifs, count, bif_offset, offset = struct.unpack_from("<IIII", data, 8)
    for i in range(count):
        start = offset + 14 * i
        if start + 14 > len(data):
            return None
        if data[start:start + 8].split(b"\0", 1)[0].decode("latin-1").lower() != name:
            continue
        kind, locator = struct.unpack_from("<HI", data, start + 8)
        if kind != _TYPES[ext]:
            continue
        return _plain(_from_bif(game_dir, data, bifs, bif_offset, locator))
    return None


def _plain(data: bytes | None) -> bytes | None:
    """None for an XOR-encrypted 2DA/IDS (classic games: it starts FF FF):
    WeiDU decrypts those; read as text, one would look nearly empty."""
    return None if data is None or data[:2] == b"\xff\xff" else data


def _from_bif(game_dir: str, key: bytes, bifs: int, bif_offset: int,
              locator: int) -> bytes | None:
    index, file_index = locator >> 20, locator & 0x3FFF
    entry = bif_offset + 12 * index
    if index >= bifs or entry + 12 > len(key):
        return None
    _length, name_offset, name_length, _where = struct.unpack_from("<IIHH", key, entry)
    relative = key[name_offset:name_offset + name_length].split(b"\0", 1)[0]
    parts = relative.decode("latin-1").replace("\\", "/").split("/")
    # A BIFF lives under the game folder: no parent, drive, stream or root part.
    if any(p == ".." or ":" in p for p in parts):
        return None
    parts = [p for p in parts if p not in ("", ".")]
    path = _find(game_dir, *parts) if parts else None
    if path is None or not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        header = fh.read(20)
        if len(header) < 20 or header[:8] != b"BIFFV1  ":
            return None
        files, _tilesets, table = struct.unpack_from("<III", header, 8)
        if table + 16 * files > os.fstat(fh.fileno()).st_size:     # a damaged BIFF
            return None
        fh.seek(table)
        entries = fh.read(16 * files)
        for i in range(len(entries) // 16):
            res_locator, res_offset, size, _kind = struct.unpack_from("<IIIH", entries, 16 * i)
            if res_locator & 0x3FFF == file_index:
                if size > _MAX_RESOURCE_BYTES:
                    return None
                fh.seek(res_offset)
                blob = fh.read(size)
                return blob if len(blob) == size else None
    return None


def spell_files(game_dir: str) -> set[str]:
    """Every SPL resref the game has, in override/ or chitin.key, lower case."""
    names = {name for name, kind in key_resources(game_dir) if kind == _TYPES["spl"]}
    override = _find(game_dir, "override")
    if override is not None and os.path.isdir(override):
        names.update(entry[:-4].lower() for entry in os.listdir(override)
                     if entry.lower().endswith(".spl"))
    return names


def _exists(game_dir: str, resource: str, keys: set[tuple[str, int]]) -> bool:
    if _find(game_dir, "override", resource):
        return True
    name, _dot, ext = resource.lower().rpartition(".")
    return ext in _TYPES and (name, _TYPES[ext]) in keys


def identify(game_dir: str) -> str | None:
    """BGEE, BG2EE, EET, or None - WeiDU's GAME_IS rules, nothing else."""
    if not os.path.isdir(game_dir) or _find(game_dir, "chitin.key") is None:
        return None
    keys = key_resources(game_dir)
    has = {game: _exists(game_dir, marker, keys) for game, marker in MARKERS.items()}
    if has["eet"]:
        return "EET"
    if has["bg2ee"]:
        return "BG2EE"
    if has["bgee"]:
        return "BGEE"
    return None


def installed_components(game_dir: str) -> int:
    path = _find(game_dir, "WeiDU.log")
    if path is None:
        return 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        return sum(1 for line in fh if line.startswith("~"))


def sod_state(bgee_dir: str) -> str:
    """'merged' (EET's own check passes), 'dlc' (an archive to merge), 'none'."""
    if _find(bgee_dir, *SOD_MOVIE.split(os.sep)):
        return "merged"
    if any(_find(bgee_dir, *parts) for parts in SOD_ARCHIVES):
        return "dlc"
    return "none"


@dataclass
class GameReport:
    bgee: str
    bg2ee: str
    games: tuple[str | None, str | None] = (None, None)
    sod: str = "none"
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [("GAME FOLDERS (identified as WeiDU's GAME_IS does; EET's readme "
                 "for what it needs)"),
                 (f"  BGEE_DIR  {self.bgee}: {self.games[0] or 'not a known game'}"
                 f", Siege of Dragonspear {self.sod}"),
                 f"  BG2EE_DIR {self.bg2ee}: {self.games[1] or 'not a known game'}"]
        lines += [f"  PROBLEM  {p}" for p in self.problems]
        lines += [f"  not checked: {n}" for n in self.notes]
        if not self.problems:
            lines.append("  both folders are what an EET install needs")
        return "\n".join(lines)


def verify_eet(bgee_dir: str, bg2ee_dir: str, plan_mods: set[str]) -> GameReport:
    """The two folders an EET plan installs onto, against EET's requirements."""
    report = GameReport(bgee_dir, bg2ee_dir,
                        games=(identify(bgee_dir), identify(bg2ee_dir)))
    for label, folder, wanted, found in (("BGEE_DIR", bgee_dir, "BGEE", report.games[0]),
                                         ("BG2EE_DIR", bg2ee_dir, "BG2EE",
                                          report.games[1])):
        if not os.path.isdir(folder):
            report.problems.append(f"{label} {folder} does not exist")
        elif _find(folder, "chitin.key") is None:
            report.problems.append(f"{label} {folder} has no chitin.key: not a game folder")
        elif found == "EET":
            report.problems.append(f"{label} {folder} is already EET (override/EET.flag): "
                                   f"EET installs onto a clean BG2:EE")
        elif found != wanted:
            report.problems.append(f"{label} {folder} is {found or 'no known game'}, "
                                   f"not {wanted}")
    if os.path.realpath(bgee_dir) == os.path.realpath(bg2ee_dir):
        report.problems.append("BGEE_DIR and BG2EE_DIR are the same folder: EET needs "
                               "two separate games")
    if report.games[1] == "BG2EE" and installed_components(bg2ee_dir):
        report.problems.append(f"BG2EE_DIR already has {installed_components(bg2ee_dir)} "
                               f"component(s) in its WeiDU.log: EET's core requires a "
                               f"clean BG2:EE (EET readme)")
    if report.games[0] == "BGEE":
        report.sod = sod_state(bgee_dir)
        if report.sod == "dlc" and "dlcmerger" not in plan_mods:
            report.problems.append("Siege of Dragonspear is a DLC archive here (GOG/Steam): "
                                   "DlcMerger #1 must be the first mod of the BGEE plan")
        elif report.sod == "none":
            report.problems.append(f"no Siege of Dragonspear in {bgee_dir} "
                                   f"({SOD_MOVIE} missing, no sod-dlc archive): EET "
                                   f"needs BG:EE with SoD")
    report.notes.append("the patch level (EET asks for v2.6.6.0 of both games)")
    report.notes.append("whether the game data itself is intact")
    return report


def check_folders(game: str, bgee_dir: str | None,
                  bg2ee_dir: str | None) -> GameReport:
    """
    The folders a game needs, before anything is chosen (the wizard's first
    phase): EET needs a BG:EE and a clean BG2:EE (verify_eet), BGEE and BG2EE
    one folder of that game. A Siege of Dragonspear still in its DLC archive is
    a note here - DlcMerger is then needed first, which the plan checks later.
    """
    game = game.upper()
    if game == "EET" and not (bgee_dir and bg2ee_dir):
        report = GameReport(bgee_dir or "", bg2ee_dir or "")
        report.problems += [f"{label}: no folder chosen" for label, folder in
                            (("BGEE_DIR", bgee_dir), ("BG2EE_DIR", bg2ee_dir)) if not folder]
        return report
    if game == "EET":
        report = verify_eet(bgee_dir or "", bg2ee_dir or "", plan_mods={"dlcmerger"})
        if report.sod == "dlc":
            report.notes.insert(0, "Siege of Dragonspear is a DLC archive here (GOG/"
                                   "Steam): DlcMerger #1 will be needed first")
        return report
    if game not in ("BGEE", "BG2EE"):
        report = GameReport(bgee_dir or "", bg2ee_dir or "")
        report.problems.append(f"unknown game {game!r}: EET, BGEE or BG2EE")
        return report
    label, folder = ("BGEE_DIR", bgee_dir) if game == "BGEE" else ("BG2EE_DIR", bg2ee_dir)
    found = identify(folder) if folder and os.path.isdir(folder) else None
    report = GameReport(bgee_dir or "", bg2ee_dir or "",
                        games=(found, None) if game == "BGEE" else (None, found))
    if not folder:
        report.problems.append(f"{label}: no folder chosen")
    elif not os.path.isdir(folder):
        report.problems.append(f"{label} {folder} does not exist")
    elif _find(folder, "chitin.key") is None:
        report.problems.append(f"{label} {folder} has no chitin.key: not a game folder")
    elif found == "EET":
        report.problems.append(f"{label} {folder} is EET (override/EET.flag), not {game}")
    elif found != game:
        report.problems.append(f"{label} {folder} is {found or 'no known game'}, not {game}")
    if game == "BGEE" and found == "BGEE":
        report.sod = sod_state(folder or "")
    report.notes.append("the patch level, and whether the game data itself is intact")
    return report
