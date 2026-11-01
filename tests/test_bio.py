"""
BIO share codes: import and export (M2, GUI-AUDIT item 12).

The acceptance test of the milestone: a BIO share code goes through import and
export without losing anything. `tests/data/bio/eet-mock.bio` was encoded by
BIO itself (33800cc, its own `encode_share_payload_text`) from the mock EET
install; the codes this tool writes were decoded by BIO the same way
(docs/TESTING.md).
"""
import base64
import json
import os
import zlib

import pytest

from iemod_fetch import api
from iemod_fetch.bio import (PREFIX, BioModlist, decode_share_code,
                             encode_share_code, modlist_from_selection)
from iemod_fetch.errors import ConfigError

HERE = os.path.dirname(__file__)
BIO_CODE = os.path.join(HERE, "data", "bio", "eet-mock.bio")
MOCK = os.path.join(HERE, "data", "eetmock")


def code_of(payload) -> str:
    raw = zlib.compress(json.dumps(payload).encode())
    return PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def bio_made():
    with open(BIO_CODE, encoding="utf-8") as fh:
        return fh.read().strip()


# ------------------------------------------------------ the acceptance test
def inflated(code: str) -> bytes:
    text = "".join(code[len(PREFIX):].split())
    return zlib.decompress(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))


def test_a_code_bio_made_round_trips_to_the_same_payload_bytes():
    """The JSON inside is re-written byte for byte. The compressed bytes match
    too where Python's zlib is the classic one (Linux, macOS, Python 3.9 on
    Windows); Python 3.14 on Windows ships zlib-ng, whose deflate stream
    differs but inflates to the same bytes - and BIO reads either."""
    code = bio_made()
    again = encode_share_code(decode_share_code(code))
    assert inflated(again) == inflated(code)


def test_import_then_export_keeps_every_field():
    imported = decode_share_code(bio_made())
    again = decode_share_code(api.bio_code_of(imported.to_selection(), imported))
    assert again.payload.keys() == imported.payload.keys()
    for key in imported.payload:
        if key != "weidu_logs":
            assert again.payload[key] == imported.payload[key], key
    # the logs are rewritten from the selection: the same components, in order
    for slot in ("bgee", "bg2ee"):
        assert component_lines(again.payload["weidu_logs"][slot]) == \
            component_lines(imported.payload["weidu_logs"][slot])


def component_lines(text):
    return [line.replace("\\", "/").strip() for line in text.splitlines()
            if line.startswith("~")]


def test_the_bio_code_becomes_the_selection_its_logs_say():
    selection = decode_share_code(bio_made()).to_selection()
    assert [install.game for install in selection.installs] == ["BGEE", "EET"]
    eet = selection.installs[1].components
    core = next(c for c in eet if c.tp2.lower() == "eet/eet.tp2")
    # BIO's recorded prompt answers stay on the line, for BIO to read back
    assert core.label.endswith("// @wlb-inputs: C:\\My Games\\BG2")


def test_the_bio_extras_are_read_not_dropped():
    imported = decode_share_code(bio_made())
    assert imported.name == "Mock EET" and imported.game_install == "EET"
    assert imported.payload["mod_configs"]["files"][0]["relative_path"] == "stratagems/scsii.ini"
    assert imported.payload["allow_auto_install"] is False


# ------------------------------------------------------------ the format
def test_a_selection_exports_as_bio_reads_it():
    selection = api.selection_of_logs([os.path.join(MOCK, "WeiDU-BGEE.log") + ":BGEE",
                                       os.path.join(MOCK, "WeiDU.log") + ":EET"])
    modlist = modlist_from_selection(selection, tool_version="9.9.9")
    assert modlist.payload["format_version"] == 1
    assert modlist.payload["game_install"] == "EET"
    assert set(modlist.payload["weidu_logs"]) == {"bgee", "bg2ee"}
    assert modlist.payload["exported_by"] == "iemod-fetch 9.9.9"
    code = encode_share_code(modlist)
    assert code.startswith(PREFIX) and "=" not in code
    assert decode_share_code(code).payload == modlist.payload


@pytest.mark.parametrize("games,install,slots", [
    (["BGEE"], "BGEE", {"bgee"}), (["BG2EE"], "BG2EE", {"bg2ee"}),
    (["IWDEE"], "IWDEE", {"iwdee"}), (["EET"], "EET", {"bg2ee"}),
])
def test_each_game_bio_knows_goes_into_its_slot(games, install, slots):
    from iemod_fetch.selection import Choice, Install, Selection
    selection = Selection([Install(g, [Choice("m/setup-m.tp2", 0)]) for g in games])
    payload = modlist_from_selection(selection).payload
    assert payload["game_install"] == install and set(payload["weidu_logs"]) == slots


def test_a_game_bio_does_not_install_is_refused():
    from iemod_fetch.selection import Choice, Install, Selection
    with pytest.raises(ConfigError, match="EET, BGEE, BG2EE or IWDEE"):
        modlist_from_selection(Selection([Install("PST", [Choice("m/setup-m.tp2", 0)])]))


def test_an_old_iwdee_code_with_its_log_in_the_first_slot_is_read():
    log = "~M/SETUP-M.TP2~ #0 #0 // Thing: v1\n"
    modlist = BioModlist({"format_version": 1, "game_install": "IWDEE",
                          "install_mode": "x", "weidu_logs": {"bgee": log}})
    assert [i.game for i in modlist.to_selection().installs] == ["IWDEE"]


def test_whitespace_from_a_chat_paste_is_ignored():
    code = code_of({"format_version": 1, "game_install": "BGEE", "install_mode": "x",
                    "weidu_logs": {"bgee": "~M/SETUP-M.TP2~ #0 #0 // A\n"}})
    broken = code[:40] + "\n  " + code[40:] + "\n"
    assert decode_share_code(broken).payload == decode_share_code(code).payload


# --------------------------------------------------- what is refused, and why
@pytest.mark.parametrize("code,message", [
    ("BWS:abc", "must start with BIO-MODLIST-V1:"),
    (PREFIX + "abc+/", "not base64url"),
    (PREFIX + "a", "damaged"),
    (PREFIX + base64.urlsafe_b64encode(b"not zlib").decode().rstrip("="), "damaged"),
    (PREFIX + base64.urlsafe_b64encode(zlib.compress(b"[1]")).decode().rstrip("="),
     "not an object"),
    (code_of({"format_version": 2, "game_install": "EET"}), "format_version 2"),
    (code_of({"format_version": 1, "game_install": "PST"}), "game_install 'PST'"),
])
def test_a_bad_code_is_refused_with_why(code, message):
    with pytest.raises(ConfigError, match=message):
        decode_share_code(code)


def test_a_truncated_code_is_refused():
    code = bio_made()
    with pytest.raises(ConfigError):
        decode_share_code(code[: len(code) // 2])


def test_a_decompression_bomb_stops_at_the_limit(monkeypatch):
    from iemod_fetch import bio
    monkeypatch.setattr(bio, "MAX_PAYLOAD_BYTES", 1024)
    bomb = code_of({"format_version": 1, "game_install": "EET", "pad": "x" * 100_000})
    with pytest.raises(ConfigError, match="over"):
        decode_share_code(bomb)


@pytest.mark.parametrize("path", ["../../evil.tp2", "a/../../b/setup-b.tp2"])
def test_a_tp2_path_leaving_its_folder_is_refused(path):
    """A shared code is untrusted: WeiDU would run a tp2 outside the mods."""
    modlist = BioModlist({"format_version": 1, "game_install": "BGEE", "install_mode": "x",
                          "weidu_logs": {"bgee": f"~ok/setup-ok.tp2~ #0 #0 // y\n"
                                                 f"~{path}~ #0 #0 // x\n"}})
    with pytest.raises(ConfigError, match="unsafe"):
        modlist.to_selection()


def test_an_empty_list_is_refused_on_import():
    modlist = BioModlist({"format_version": 1, "game_install": "EET",
                          "install_mode": "x", "weidu_logs": {"bgee": "", "bg2ee": ""}})
    with pytest.raises(ConfigError, match="no WeiDU entries"):
        modlist.to_selection()


# ------------------------------------------------------------ the command line
def test_bio_code_in_and_out_through_a_run(tmp_path):
    out = tmp_path / "again.bio"
    selection = tmp_path / "selection.json"
    outcome = api.run(api.Settings(bio_code=BIO_CODE, emit_bio_code=str(out),
                                   emit_selection=str(selection), check_only=True,
                                   quiet=True, manifest=os.path.join(HERE, "data",
                                                                     "mod_downloads.json"),
                                   no_update_data=True, no_default_data=True))
    assert outcome.exit_code in (0, 1)
    assert decode_share_code(out.read_text()).name == "Mock EET"
    assert json.loads(selection.read_text())["installs"][1]["game"] == "EET"


def test_bio_code_and_weidu_log_together_are_refused():
    with pytest.raises(ConfigError, match="give one of them"):
        api.run(api.Settings(bio_code=BIO_CODE, weidu_log=["x.log"], check_only=True,
                             no_update_data=True))
