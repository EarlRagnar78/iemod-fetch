"""
packaging/mod_installer.py (ADR-0046): mod_installer built for the wizard's
bundle - for which system, from what, and with what the build needs. The
build itself runs in the release workflows and ci.yml's real-weidu job.
"""
import importlib.util
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = importlib.util.spec_from_file_location(
    "mod_installer_build", os.path.join(ROOT, "packaging", "mod_installer.py"))
assert SPEC and SPEC.loader
recipe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recipe)


@pytest.mark.parametrize("system,machine,expected", [
    ("Linux", "x86_64", "x86_64-unknown-linux-musl"),
    ("Linux", "aarch64", "aarch64-unknown-linux-musl"),
    ("Windows", "AMD64", "x86_64-pc-windows-msvc"),
    ("Darwin", "arm64", "aarch64-apple-darwin"),
    ("Darwin", "x86_64", "x86_64-apple-darwin")])
def test_each_system_gets_its_own_target_static_on_linux(system, machine, expected):
    assert recipe.target(system, machine) == expected


def test_a_system_with_no_build_says_so():
    with pytest.raises(SystemExit, match="no mod_installer build for Linux riscv64"):
        recipe.target("Linux", "riscv64")


def test_what_the_build_needs_and_cannot_install_is_named(monkeypatch):
    monkeypatch.setattr(recipe.shutil, "which", lambda _tool: None)
    with pytest.raises(SystemExit) as stop:
        recipe.requirements("x86_64-unknown-linux-musl")
    assert "git" in str(stop.value) and "rustup" in str(stop.value)
    assert "musl-tools" in str(stop.value)


def test_the_toolchain_and_target_are_installed_with_rustup(monkeypatch):
    ran = []
    monkeypatch.setattr(recipe.shutil, "which", lambda tool: "/usr/bin/" + tool)
    monkeypatch.setattr(recipe, "run", lambda args, cwd=None: ran.append(args))
    recipe.requirements("x86_64-pc-windows-msvc")
    assert ran == [["rustup", "toolchain", "install", recipe.RUST, "--profile", "minimal",
                    "--target", "x86_64-pc-windows-msvc"]]


def test_the_commit_built_is_the_one_ci_tests():
    """ci.yml's real-weidu job tests the bundle's mod_installer: one commit
    and one version, or a bump forgot one."""
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as fh:
        ci = fh.read()
    assert re.search(r"MOD_INSTALLER_REV:\s*(\w+)", ci)[1] == recipe.REV
    assert re.search(r'MOD_INSTALLER_VERSION:\s*"?([\d.]+)', ci)[1] == recipe.VERSION


def test_windows_links_the_c_runtime_in_and_others_build_as_they_are(monkeypatch):
    monkeypatch.setenv("RUSTFLAGS", "-D warnings")
    assert recipe.build_env("x86_64-pc-windows-msvc")["RUSTFLAGS"] == \
        "-D warnings -C target-feature=+crt-static"
    assert recipe.build_env("x86_64-unknown-linux-musl") is None


def test_a_program_that_would_load_the_vc_runtime_is_seen(tmp_path):
    """Measured: upstream's v12.1.1 .exe, default MSVC build, names
    VCRUNTIME140.dll among its imports; one built with crt-static does not."""
    dynamic, static = tmp_path / "a.exe", tmp_path / "b.exe"
    dynamic.write_bytes(b"MZ...KERNEL32.dll\x00VCRUNTIME140.dll\x00api-ms-win-crt")
    static.write_bytes(b"MZ...KERNEL32.dll\x00")
    assert recipe.needs_vc_runtime(str(dynamic))
    assert not recipe.needs_vc_runtime(str(static))
