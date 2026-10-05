"""INI configuration: precedence, sizes, and failure modes."""
import os

import pytest

from iemod_fetch.cli import _parse_with_config, build_parser
from iemod_fetch.config import load_config, parse_size
from iemod_fetch.errors import ConfigError


# ------------------------------------------------------------------- sizes
@pytest.mark.parametrize("given,expected", [
    ("536870912", 536870912),
    (536870912, 536870912),
    ("512MiB", 512 * 1024 ** 2),
    ("2GiB", 2 * 1024 ** 3),
    ("1.5GB", 1_500_000_000),
    ("2G", 2_000_000_000),
    ("  4 GiB ", 4 * 1024 ** 3),
])
def test_sizes_accept_bytes_and_units(given, expected):
    assert parse_size(given) == expected


@pytest.mark.parametrize("bad", ["", "lots", "-5", "0", "12 parsecs", "MiB"])
def test_bad_sizes_name_the_option(bad):
    with pytest.raises(ConfigError, match="max_bytes"):
        parse_size(bad, "max_bytes")


# ------------------------------------------------------------------ loading
def write(tmp_path, text, name="iemod-fetch.ini"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_a_missing_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)
    assert load_config().values == {}


def test_an_explicitly_named_missing_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="no such file"):
        load_config(str(tmp_path / "nope.ini"))


def test_values_are_typed(tmp_path):
    path = write(tmp_path, "[iemod-fetch]\nmax_bytes = 2GiB\nworkers = 8\n"
                           "allow_http = true\ntarget = Mods\n")
    values = load_config(path).values
    assert values == {"max_bytes": 2 * 1024 ** 3, "workers": 8,
                      "allow_http": True, "target": "Mods"}


def test_repeatable_options_accept_lines_or_commas(tmp_path):
    path = write(tmp_path, "[iemod-fetch]\nweidu_log =\n    WeiDU.log\n"
                           "    WeiDU-BGEE.log:BGEE\ntrusted_owner = A, B\n")
    values = load_config(path).values
    assert values["weidu_log"] == ["WeiDU.log", "WeiDU-BGEE.log:BGEE"]
    assert values["trusted_owner"] == ["A", "B"]


def test_dashes_and_underscores_are_both_accepted(tmp_path):
    path = write(tmp_path, "[iemod-fetch]\nmax-bytes = 1GiB\n")
    assert load_config(path).values["max_bytes"] == 1024 ** 3


def test_an_unknown_option_warns_but_does_not_stop_the_run(tmp_path):
    path = write(tmp_path, "[iemod-fetch]\nworkers = 2\nnonsense = 1\n")
    config = load_config(path)
    assert config.values == {"workers": 2}
    assert any("nonsense" in w for w in config.warnings)


def test_a_missing_section_warns(tmp_path):
    path = write(tmp_path, "[other]\nworkers = 2\n")
    config = load_config(path)
    assert config.values == {} and config.warnings


def test_malformed_ini_is_a_configuration_error(tmp_path):
    path = write(tmp_path, "this is not ini at all\n= = =\n")
    with pytest.raises(ConfigError, match="not a valid INI"):
        load_config(path)


def test_a_bad_integer_names_the_option(tmp_path):
    path = write(tmp_path, "[iemod-fetch]\nworkers = eight\n")
    with pytest.raises(ConfigError, match="workers"):
        load_config(path)


# --------------------------------------------------------------- precedence
def test_the_file_supplies_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, "[iemod-fetch]\nmax_bytes = 2GiB\nworkers = 8\ntarget = FromFile\n")
    args, config = _parse_with_config(build_parser(), [])
    assert args.max_bytes == 2 * 1024 ** 3
    assert args.workers == 8 and args.target == "FromFile"
    assert config.path.endswith("iemod-fetch.ini")


def test_an_explicit_flag_always_wins(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, "[iemod-fetch]\nworkers = 8\ntarget = FromFile\n")
    args, _ = _parse_with_config(build_parser(), ["-j", "2", "-t", "FromCLI"])
    assert args.workers == 2 and args.target == "FromCLI"


def test_the_cli_replaces_a_repeatable_option_rather_than_appending(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, "[iemod-fetch]\nweidu_log =\n    FromFile.log\n")
    args, _ = _parse_with_config(build_parser(), ["-w", "FromCLI.log"])
    assert args.weidu_log == ["FromCLI.log"]


def test_the_file_is_used_when_the_option_is_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, "[iemod-fetch]\nweidu_log =\n    FromFile.log\n")
    args, _ = _parse_with_config(build_parser(), [])
    assert args.weidu_log == ["FromFile.log"]


def test_built_in_defaults_survive_an_empty_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path, "[iemod-fetch]\n")
    args, _ = _parse_with_config(build_parser(), [])
    assert args.workers == 4 and args.max_bytes == 2 * 1024 ** 3


def test_the_shipped_example_file_parses():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(root, "iemod-fetch.ini.example"))
    assert config.values["max_bytes"] == 2 * 1024 ** 3
    assert config.warnings == []
