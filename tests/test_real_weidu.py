"""
The mock EET install, run by the REAL WeiDU (ADR-0026).

No game data is needed for what is checked here: WeiDU decides GAME_IS from
marker files (WeiDU src/tppe.ml: `oh1000.are` is BG:EE, `oh6000.are` BG2:EE,
`eet.flag` EET - which EET's core writes to override/, EET.tp2 line 2797), and
REQUIRE_COMPONENT / FORBID_COMPONENT from its own WeiDU.log. So two synthetic
game folders - an empty chitin.key, an empty dialog.tlk and the marker - are
enough for the real WeiDU binary to enforce every flag the simulator models.

Each mock mod is installed from its verbatim excerpt, keeping the flag lines
WeiDU can evaluate on one line (multi-line predicates were cut by the excerpt;
string references become literal text, since the excerpts ship no .tra). The
EET core gets EET's own two lines that write `override/EET.flag`.

The claim: on the same logs, real WeiDU refuses exactly what `simulate_install`
says it refuses, and installs the resolved plan to the last component.

Opt-in: IEMOD_WEIDU=/path/to/weidu. CI downloads WeiDU v251 (pinned sha256).
"""
import io
import os
import re
import shutil
import struct
import subprocess

import pytest

from iemod_fetch import cli
from iemod_fetch.constraints import load_constraints
from iemod_fetch.ordering import EET_LOG, PRE_EET_LOG
from iemod_fetch.simulate import simulate_install
from iemod_fetch.tp2 import tp2_identity

WEIDU = os.environ.get("IEMOD_WEIDU", "")
if os.environ.get("IEMOD_REQUIRE_REAL") and not os.path.isfile(WEIDU):
    raise RuntimeError("IEMOD_REQUIRE_REAL is set but IEMOD_WEIDU is not a file")
pytestmark = pytest.mark.skipif(not (WEIDU and os.path.isfile(WEIDU)),
                                reason="real WeiDU not given (IEMOD_WEIDU)")

HERE = os.path.dirname(__file__)
MOCK = os.path.join(HERE, "data", "eetmock")
MODS = os.path.join(MOCK, "Mods")
KRION = os.path.join(HERE, "data", "krion")
MANIFEST = os.path.join(HERE, "data", "mod_downloads.json")

MARKER = {"BGEE": "oh1000.are", "BG2EE": "oh6000.are"}
LINE = re.compile(r"^~([^~]+)~\s+#(\d+)\s+#(\d+)")
_FLAG = re.compile(r"^\s*(REQUIRE_PREDICATE|REQUIRE_COMPONENT|FORBID_COMPONENT|"
                   r"SUBCOMPONENT|GROUP|DESIGNATED|LABEL)\b")
_UNEVALUABLE = re.compile(r"FILE_EXISTS|STR_EQ|STRING_COMPARE|%\w+%")
# EET.tp2 lines 2797 and the blank file it copies (lines 103-104), verbatim.
EET_FLAG_BODY = ("<<<<<<<< .../blank.txt\n>>>>>>>>\n"
                 "COPY ~.../blank.txt~ ~override/EET.flag~\n")


def make_game(root, game):
    os.makedirs(os.path.join(root, "override"))
    os.makedirs(os.path.join(root, "lang", "en_US"))
    with open(os.path.join(root, "chitin.key"), "wb") as fh:
        fh.write(b"KEY V1  " + struct.pack("<IIII", 0, 0, 24, 24))
    tlk = b"TLK V1  " + struct.pack("<HII", 0, 0, 18)
    for path in ("dialog.tlk", os.path.join("lang", "en_US", "dialog.tlk")):
        with open(os.path.join(root, path), "wb") as fh:
            fh.write(tlk)
    open(os.path.join(root, "override", MARKER[game]), "wb").close()


def _balanced(line):
    return line.count("(") == line.count(")")


def installable(text, eet_core=False):
    """An excerpt as a tp2 the real WeiDU runs: its evaluable flag lines."""
    out = ["BACKUP ~iemodtest/backup~", "AUTHOR ~iemod-fetch test~"]
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if line.lstrip().startswith("//"):
            continue
        if re.match(r"^\s*BEGIN\b", line):
            if eet_core and len(out) > 2:
                out.append(EET_FLAG_BODY)
            out.append(line)
        elif re.match(r"^\s*ACTION_IF\s*\(NOT GAME_IS", line):
            out.extend(lines[i - 1:i + 2])           # ACTION_IF ... ABORT ... END
            i += 2
        elif _FLAG.match(line) and _balanced(line) and not _UNEVALUABLE.search(line):
            out.append(line)
    if eet_core:
        out.append(EET_FLAG_BODY)
    body = "\n".join(out) + "\n"
    return re.sub(r"(?<![~\w])@(-?\d+)", r"~@\1~", body)


def stage_mods(game_dir):
    for folder in os.listdir(MODS):
        src = os.path.join(MODS, folder)
        for dirpath, _dirs, files in os.walk(src):
            for name in files:
                if not name.lower().endswith(".tp2"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, name), MODS)
                dest = os.path.join(game_dir, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(os.path.join(dirpath, name), encoding="utf-8") as fh:
                    text = fh.read()
                eet_core = rel.replace("\\", "/").lower() == "eet/eet.tp2"
                with open(dest, "w", encoding="utf-8") as fh:
                    fh.write(installable(text, eet_core=eet_core))


def log_steps(path):
    steps = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            match = LINE.match(line)
            if match:
                steps.append((match.group(1).replace("\\", "/"), int(match.group(3))))
    return steps


def run_weidu(game_dir, tp2, component):
    proc = subprocess.run(
        [WEIDU, "--game", ".", "--no-exit-pause", "--noautoupdate", "--language", "0",
         "--skip-at-view", "--force-install", str(component), tp2],
        cwd=game_dir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=60, check=False)
    return proc.stdout.decode("utf-8", "replace")


def install(tmp_path, logs):
    """Install each log, in order, with real WeiDU; return (installed, refused)."""
    installed, refused = {}, set()
    for role, game in ((PRE_EET_LOG, "BGEE"), (EET_LOG, "BG2EE")):
        game_dir = str(tmp_path / game)
        make_game(game_dir, game)
        stage_mods(game_dir)
        for tp2, component in log_steps(logs[role]):
            run_weidu(game_dir, tp2, component)
        done = log_steps(os.path.join(game_dir, "WeiDU.log")) \
            if os.path.exists(os.path.join(game_dir, "WeiDU.log")) else []
        installed[role] = [(tp2_identity(t), c) for t, c in done]
        wanted = [(tp2_identity(t), c) for t, c in log_steps(logs[role])]
        refused |= {(role, mod, c) for mod, c in wanted
                    if (mod, c) not in installed[role]}
    return installed, refused


def _key(tp2):
    return tp2_identity(tp2)


def simulated(logs):
    steps = {role: [(_key(t), c) for t, c in log_steps(path)]
             for role, path in logs.items()}
    folders = {(_key(t), t.split("/")[0], t.split("/")[-1])
               for path in logs.values() for t, _c in log_steps(path)}
    constraints = load_constraints(MODS, sorted(folders))
    result = simulate_install(steps, constraints.by_mod)   # merge check: not real here
    return {(r.log, r.mod, r.component) for r in result.refused}


def test_real_weidu_refuses_what_the_simulator_says(tmp_path):
    logs = {PRE_EET_LOG: os.path.join(MOCK, "WeiDU-BGEE.log"),
            EET_LOG: os.path.join(MOCK, "WeiDU.log")}
    _installed, refused = install(tmp_path, logs)
    assert refused, "the mock logs carry mistakes; WeiDU must refuse some"
    assert refused == simulated(logs)


def test_real_weidu_installs_the_resolved_plan_completely(tmp_path):
    plan = tmp_path / "plan"
    code = cli.main(["--check-only", "-m", MANIFEST,
                     "-w", os.path.join(MOCK, "WeiDU.log") + ":EET",
                     "-w", os.path.join(MOCK, "WeiDU-BGEE.log") + ":BGEE",
                     "-t", MODS, "--order-catalogue", KRION, "--plan-order", str(plan),
                     "--rules", os.path.join(MOCK, "rules"), "--resolve-conflicts",
                     "--simulate"], stream=io.StringIO())
    assert code in (0, 1)
    logs = {PRE_EET_LOG: str(plan / PRE_EET_LOG), EET_LOG: str(plan / EET_LOG)}
    installed, refused = install(tmp_path / "games", logs)
    assert refused == set()
    for role, path in logs.items():
        assert installed[role] == [(_key(t), c) for t, c in log_steps(path)]
    shutil.rmtree(tmp_path / "games", ignore_errors=True)


def test_real_weidu_installs_a_plan_reordered_by_kind(tmp_path):
    """
    GUI-AUDIT item 29: the test catalogue does not place ub or ascension;
    with a QUEST MODS BG2 category and lcc-docs calling both a BG2 quest,
    their kind moves ub ahead of stratagems and cdtweaks (item 27) - and the
    real WeiDU still installs that plan to the last component.
    """
    import json
    krion = tmp_path / "krion"
    shutil.copytree(KRION, krion)
    categories = json.loads((krion / "categories.json").read_text(encoding="utf-8"))
    names = list(categories["categories"])
    names.insert(names.index("ENGINE") + 1, "QUEST MODS BG2")
    categories["categories"] = {n: categories["categories"].get(n, {}) for n in names}
    (krion / "categories.json").write_text(json.dumps(categories), encoding="utf-8")
    lcc = tmp_path / "lcc-docs" / "db" / "mods.json"
    lcc.parent.mkdir(parents=True)
    lcc.write_text(json.dumps([
        {"tp2": mod, "name": mod, "categories": ["Quête"], "games": ["BG2EE"], "urls": []}
        for mod in ("ub", "ascension")]), encoding="utf-8")

    def plan(folder, *extra):
        out = io.StringIO()
        cli.main(["--check-only", "-m", MANIFEST,
                  "-w", os.path.join(MOCK, "WeiDU.log") + ":EET",
                  "-w", os.path.join(MOCK, "WeiDU-BGEE.log") + ":BGEE",
                  "-t", MODS, "--order-catalogue", str(krion), "--plan-order", str(folder),
                  "--rules", os.path.join(MOCK, "rules"), "--resolve-conflicts",
                  "--no-update-data", "--no-default-data", *extra], stream=out)
        return out.getvalue(), [_key(t) for t, _c in log_steps(str(folder / EET_LOG))]

    _out, plain = plan(tmp_path / "plain")
    summary, by_kind = plan(tmp_path / "plan", "--catalogue", str(lcc))
    assert "placed by kind (2)" in summary
    assert by_kind != plain and by_kind.index("ub") < by_kind.index("stratagems")
    logs = {PRE_EET_LOG: str(tmp_path / "plan" / PRE_EET_LOG),
            EET_LOG: str(tmp_path / "plan" / EET_LOG)}
    installed, refused = install(tmp_path / "games", logs)
    assert refused == set()
    for role, path in logs.items():
        assert installed[role] == [(_key(t), c) for t, c in log_steps(path)]


MOD_INSTALLER = os.environ.get("IEMOD_MOD_INSTALLER", "")
if os.environ.get("IEMOD_REQUIRE_REAL") and not os.path.isfile(MOD_INSTALLER):
    raise RuntimeError("IEMOD_REQUIRE_REAL is set but IEMOD_MOD_INSTALLER is not a file")


@pytest.mark.skipif(not (MOD_INSTALLER and os.path.isfile(MOD_INSTALLER)),
                    reason="real mod_installer not given (IEMOD_MOD_INSTALLER)")
@pytest.mark.skipif(os.name == "nt", reason="POSIX shell script")
def test_the_generated_installer_runs_with_real_mod_installer_and_weidu(tmp_path):
    """The whole chain: install-eet.sh -> mod_installer -> WeiDU -> both games."""
    plan = tmp_path / "plan"
    cli.main(["--check-only", "-m", MANIFEST,
              "-w", os.path.join(MOCK, "WeiDU.log") + ":EET",
              "-w", os.path.join(MOCK, "WeiDU-BGEE.log") + ":BGEE",
              "-t", MODS, "--order-catalogue", KRION, "--plan-order", str(plan),
              "--rules", os.path.join(MOCK, "rules"), "--resolve-conflicts",
              "--emit-installer"], stream=io.StringIO())
    mods = tmp_path / "mods"
    mods.mkdir()
    stage_mods(str(mods))
    for game in ("BGEE", "BG2EE"):
        make_game(str(tmp_path / game), game)
    env = dict(os.environ, BGEE_DIR=str(tmp_path / "BGEE"),
               BG2EE_DIR=str(tmp_path / "BG2EE"), MODS_DIR=str(mods), WEIDU=WEIDU,
               MOD_INSTALLER=MOD_INSTALLER, ALLOW_MIXED_CASE="1")
    proc = subprocess.run(["sh", str(plan / "install-eet.sh")], env=env,
                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=600, check=False)
    assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace")[-3000:]
    for role, game in ((PRE_EET_LOG, "BGEE"), (EET_LOG, "BG2EE")):
        got = [(_key(t), c) for t, c in log_steps(str(tmp_path / game / "WeiDU.log"))]
        assert got == [(_key(t), c) for t, c in log_steps(str(plan / role))]
    assert os.path.exists(tmp_path / "BG2EE" / "override" / "EET.flag")
