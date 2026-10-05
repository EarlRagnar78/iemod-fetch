"""Project Infinity `[Metadata]` ini — identity and the mod's own ordering hints."""
import zipfile


from iemod_fetch.modmeta import (find_metadata, parse_metadata_ini,
                                 read_iemod_metadata, read_metadata_file)

SCS = """
[Metadata]
Name      = Sword Coast Stratagems
Author    = DavidW
Version   = v35.21
Type      = Tactical
Homepage  = https://www.gibberlings3.net/mods/tactics/scs/
Download  = https://github.com/Gibberlings3/SwordCoastStratagems/releases/latest  # note
Before    = eet_end, cdtweaks
After     = spell_rev,  item_rev
LabelType = Standard
"""


def test_identity_fields():
    meta = parse_metadata_ini(SCS)
    assert meta.name == "Sword Coast Stratagems"
    assert meta.author == "DavidW" and meta.version == "v35.21"
    assert meta.download.endswith("/releases/latest")   # trailing comment stripped


def test_ordering_hints_are_normalised():
    meta = parse_metadata_ini(SCS)
    assert meta.before == ["eet_end", "cdtweaks"]
    assert meta.after == ["spell_rev", "item_rev"]
    assert meta.has_order_hints


def test_urls_are_ordered_download_first():
    assert parse_metadata_ini(SCS).urls[0].startswith("https://github.com/")


def test_only_the_metadata_section_counts():
    meta = parse_metadata_ini("[Metadata]\nName = Real\n[Other]\nName = Decoy\n")
    assert meta.name == "Real"


def test_a_file_without_a_section_header_is_still_read():
    assert parse_metadata_ini("Name = Bare\nBefore = x\n").name == "Bare"


def test_a_mod_with_no_hints_says_so():
    assert not parse_metadata_ini("[Metadata]\nName = Plain\n").has_order_hints


def test_missing_values_are_none_not_empty_strings():
    meta = parse_metadata_ini("[Metadata]\nName =\n")
    assert meta.name is None and meta.before == []


def test_reading_from_a_mod_directory(tmp_path):
    mod = tmp_path / "stratagems"
    mod.mkdir()
    (mod / "stratagems.ini").write_text(SCS, encoding="utf-8")
    assert find_metadata(str(mod), "stratagems").name == "Sword Coast Stratagems"


def test_any_ini_carrying_metadata_is_found(tmp_path):
    mod = tmp_path / "mymod"
    mod.mkdir()
    (mod / "something-else.ini").write_text(SCS, encoding="utf-8")
    assert find_metadata(str(mod), "mymod").author == "DavidW"


def test_a_directory_without_an_ini_returns_none(tmp_path):
    (tmp_path / "bare").mkdir()
    assert find_metadata(str(tmp_path / "bare")) is None


def test_reading_from_inside_an_iemod(tmp_path):
    """An .iemod is a zip, so the metadata is readable before extracting."""
    arc = tmp_path / "scs.iemod"
    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("stratagems/stratagems.tp2", "VERSION ~v1~")
        zf.writestr("stratagems/stratagems.ini", SCS)
    meta = read_iemod_metadata(str(arc))
    assert meta.name == "Sword Coast Stratagems" and meta.before == ["eet_end", "cdtweaks"]


def test_a_zip_without_metadata_returns_none(tmp_path):
    arc = tmp_path / "plain.zip"
    with zipfile.ZipFile(arc, "w") as zf:
        zf.writestr("mod/mod.tp2", "x")
    assert read_iemod_metadata(str(arc)) is None


def test_a_corrupt_archive_returns_none(tmp_path):
    arc = tmp_path / "broken.iemod"
    arc.write_bytes(b"not a zip")
    assert read_iemod_metadata(str(arc)) is None


def test_an_unreadable_file_returns_none(tmp_path):
    assert read_metadata_file(str(tmp_path / "absent.ini")) is None
