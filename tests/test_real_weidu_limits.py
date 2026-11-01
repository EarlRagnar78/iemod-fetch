"""
The engine-limit measurement, checked against the REAL WeiDU (ADR-0034).

limits.py reads a game folder by WeiDU's own rules: the last kit number in
KITLIST.2DA (get_next_kit_number), and a spell slot as taken when ADD_SPELL
would skip it. Here WeiDU itself installs ADD_KIT and ADD_SPELL into a
synthetic BG2:EE - a real chitin.key and BIFF, the tables in override/ - and
what it assigns must be what the measurement predicted: kit N+1 after N
measured, refused past 256; the first free spell slot, the SPWI file in the
BIFF counted as taken.

Opt-in: IEMOD_WEIDU=/path/to/weidu. CI downloads WeiDU v251 (pinned sha256).
"""
import os
import re
import struct
import subprocess

import pytest

from iemod_fetch import api
from test_limits import a_game

WEIDU = os.environ.get("IEMOD_WEIDU", "")
if os.environ.get("IEMOD_REQUIRE_REAL") and not os.path.isfile(WEIDU):
    raise RuntimeError("IEMOD_REQUIRE_REAL is set but IEMOD_WEIDU is not a file")
pytestmark = pytest.mark.skipif(not (WEIDU and os.path.isfile(WEIDU)),
                                reason="real WeiDU not given (IEMOD_WEIDU)")

KIT_TP2 = """BACKUP ~m/backup~
AUTHOR ~iemod-fetch test~
BEGIN ~kit~
ADD_KIT ~NEWKIT~
  ~NEWKIT 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1~
  ~NEWKIT 1 1 1 1~
  ~NEWKIT 3 3 3 3 3 3~
  ~NEWKIT 0 0 0 0 0 0~
  ~NEWKIT 0 0 0 0 0 0~
  ~NEWKIT 0 0 0 0 0 0~
  ~NEWKIT 1 1 1 1 1 1 1 1 1~
  ~NEWKIT 0 1 0 0 0 0~
  ~m/CLABNEW.2DA~
  ~~
  ~0x00000000 2~
  ~Fi0~
  ~* * * * * * * * * * * * * * * * * * * *~
  SAY ~new kit~ SAY ~New Kit~ SAY ~help~
PRINT ~iemod-kit %NEWKIT%~
"""
SPELL_TP2 = """BACKUP ~m/backup~
AUTHOR ~iemod-fetch test~
BEGIN ~spells~
ADD_SPELL ~m/x.spl~ 2 1 ~WIZARD_NEW_A~
ADD_SPELL ~m/x.spl~ 2 1 ~WIZARD_NEW_B~
ADD_SPELL ~m/x.spl~ 2 1 ~WIZARD_ONE~
PRINT ~iemod-spells %WIZARD_NEW_A% %WIZARD_NEW_B% %WIZARD_ONE%~
"""


def bg2ee(root, kits_used=None):
    """a_game's chitin.key and BIFF, made a BG2:EE WeiDU will install into."""
    game = a_game(root)
    os.makedirs(os.path.join(game, "lang", "en_US"))
    tlk = b"TLK V1  " + struct.pack("<HII", 0, 0, 18)
    for path in ("dialog.tlk", os.path.join("lang", "en_US", "dialog.tlk")):
        with open(os.path.join(game, path), "wb") as fh:
            fh.write(tlk)
    override = os.path.join(game, "override")
    files = {"oh6000.are": "", "KIT.IDS": "IDS V1.0\n0x4000 TRUECLASS\n",
             "WEAPPROF.2DA": "2DA V1.0\n0\n     ID NAME_REF FIGHTER\nA 89 1 1\nB 90 1 1\n"
                             "C 91 1 1\nD 92 1 1\n"}
    for table in ("CLASWEAP", "ABCLASRQ", "ABDCDSRQ", "ABDCSCRQ", "ABCLSMOD", "DUALCLAS",
                  "ALIGNMNT", "LUABBR"):
        files[table + ".2DA"] = "2DA V1.0\n0\n     A B\nX 0 0\n"
    if kits_used is not None:
        rows = "".join(f"{i}  KIT{i} 1 2 3 CLAB{i} 1 0x4000 2\n" for i in range(1, kits_used + 1))
        files["KITLIST.2DA"] = ("2DA V1.0\n*\n     ROWNAME LOWER MIXED HELP ABILITIES "
                                "PROFICIENCY UNUSABLE CLASS\n0  RESERVE 0 0 0 * 0 0x00000000 0\n"
                                + rows)
    for name, text in files.items():
        with open(os.path.join(override, name), "w") as fh:
            fh.write(text)
    os.makedirs(os.path.join(game, "m"))
    return game


def install(game, tp2):
    with open(os.path.join(game, "m", "setup-m.tp2"), "w") as fh:
        fh.write(tp2)
    result = subprocess.run([WEIDU, "--no-exit-pause", "--yes", "m/setup-m.tp2",
                             "--force-install", "0", "--language", "0"],
                            cwd=game, capture_output=True, text=True, timeout=120, check=False)
    return result.stdout


@pytest.mark.parametrize("used", [254, 255, 256])
def test_weidu_gives_the_next_kit_number_the_measurement_predicts(tmp_path, used):
    game = bg2ee(tmp_path / "g", kits_used=used)
    with open(os.path.join(game, "m", "CLABNEW.2DA"), "w") as fh:
        fh.write("2DA V1.0\n****\n  1\nABILITY1 ****\n")
    measured, _installed = api._measure_game(game)
    assert measured.kits == used
    out = install(game, KIT_TP2)
    if used < 256:
        assert f"iemod-kit {used + 1}" in out and "SUCCESSFULLY INSTALLED" in out, out
        assert api._measure_game(game)[0].kits == used + 1
    else:
        assert "more than 256 kits" in out and "NOT INSTALLED" in out, out
        assert api._measure_game(game)[0].kits == used


def test_weidu_takes_the_spell_slots_the_measurement_counts_as_free(tmp_path):
    """Taken: 2101 and 2102 (SPELL.IDS in the BIFF), SPWI103 (override),
    SPWI105 (the BIFF). ADD_SPELL must pick 2104 then 2106, and reuse 2101."""
    game = bg2ee(tmp_path / "g")
    open(os.path.join(game, "override", "SPWI103.SPL"), "wb").close()
    with open(os.path.join(game, "m", "x.spl"), "wb") as fh:
        fh.write(b"SPL V1  " + b"\0" * 200)
    assert api._measure_game(game)[0].spell_slots["w1"] == 4
    out = install(game, SPELL_TP2)
    assert re.search(r"iemod-spells 2104 2106 2101", out), out
    assert api._measure_game(game)[0].spell_slots["w1"] == 6
