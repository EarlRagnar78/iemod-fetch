"""Machine-readable and human-readable run reports."""
import enum
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import List, Optional


class Status(enum.Enum):
    OK = "ok"                 # downloaded, verified, installed
    SKIPPED = "skipped"       # already present and verified
    PLANNED = "planned"       # --dry-run
    MANUAL = "manual"         # needs a human: no source, or off-site only
    CONFLICT = "conflict"     # destination exists, --force not given
    FAILED = "failed"         # download / extraction / verification error


TERMINAL_BAD = (Status.FAILED, Status.CONFLICT)


@dataclass
class Record:
    folder: str
    status: Status
    detail: str = ""
    source_key: Optional[str] = None
    url: Optional[str] = None
    sha256: Optional[str] = None
    version: Optional[str] = None
    tp2_file: Optional[str] = None
    advisories: List[str] = field(default_factory=list)
    origin: Optional[str] = None
    discovered_github: Optional[str] = None
    bytes: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_json(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        return data


_COLOURS = {Status.OK: "32", Status.SKIPPED: "34", Status.PLANNED: "36",
            Status.MANUAL: "33", Status.CONFLICT: "33", Status.FAILED: "31"}
_GLYPHS = {Status.OK: "+", Status.SKIPPED: "-", Status.PLANNED: ".",
           Status.MANUAL: "!", Status.CONFLICT: "!", Status.FAILED: "x"}


def _paint(text: str, status: Status, stream) -> str:
    if not stream.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"\033[1;{_COLOURS[status]}m{text}\033[0m"


def line_for(record: Record, stream=sys.stdout) -> str:
    glyph = _paint(f"[{_GLYPHS[record.status]}]", record.status, stream)
    lines = [f"{glyph} {record.folder}: {record.detail}"]
    # Health warnings are printed with the mod, not buried in the JSON report:
    # you need them while you are watching the run, not afterwards.
    for note in record.advisories:
        lines.append(f"    {_paint('^', Status.MANUAL, stream)} {note}")
    return "\n".join(lines)


@dataclass
class RunReport:
    started_at: float = field(default_factory=time.time)
    records: List[Record] = field(default_factory=list)
    unresolved: List[dict] = field(default_factory=list)
    findings: List[dict] = field(default_factory=list)   # order / compatibility
    suggestions: List[dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def counts(self) -> dict:
        out = {status.value: 0 for status in Status}
        for record in self.records:
            out[record.status.value] += 1
        return out

    @property
    def failed(self) -> List[Record]:
        return [r for r in self.records if r.status in TERMINAL_BAD]

    @property
    def blocking_findings(self) -> List[dict]:
        """Errors, minus any withheld as stale or explicitly suppressed."""
        return [f for f in self.findings
                if f.get("severity") == "error"
                and not f.get("stale_risk") and not f.get("suppressed")]

    def exit_code(self, allow_manual: bool = False) -> int:
        if self.failed:
            return 1
        manual = [r for r in self.records if r.status is Status.MANUAL] or self.unresolved
        if manual and not allow_manual:
            return 1
        return 0

    def to_json(self) -> dict:
        return {
            "tool": "iemod-fetch",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.started_at)),
            "duration_seconds": round(time.time() - self.started_at, 2),
            "counts": self.counts(),
            "records": [r.to_json() for r in self.records],
            "unresolved": self.unresolved,
            "findings": self.findings,
            "suggestions": self.suggestions,
            "warnings": self.warnings,
        }

    def write_json(self, path: str) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.to_json(), fh, indent=2)
        os.replace(tmp, path)


def render_summary(report: RunReport, target_dir: str, stream=sys.stdout) -> None:
    counts = report.counts()
    print(file=stream)
    print("=" * 70, file=stream)
    print(" SUMMARY  " + "  ".join(
        f"{name}={counts[name]}" for name in
        ("ok", "skipped", "planned", "manual", "conflict", "failed")
        if counts[name]), file=stream)
    print("=" * 70, file=stream)

    for record in report.failed:
        print(f"  FAILED  {record.folder}: {record.detail}", file=stream)

    manual = [r for r in report.records if r.status is Status.MANUAL]
    if manual or report.unresolved:
        print(file=stream)
        print(" MANUAL ACTION REQUIRED", file=stream)
        print(" Download these by hand and place the extracted mod folder under:",
              file=stream)
        print(f"   {target_dir}", file=stream)
        for record in manual:
            print(f"\n  * {record.folder}", file=stream)
            print(f"      reason : {record.detail}", file=stream)
            if record.url:
                print(f"      url    : {record.url}", file=stream)
        for entry in report.unresolved:
            print(f"\n  * {entry['folder']}", file=stream)
            print(f"      reason : {entry['detail']}", file=stream)
            for hint in entry.get("suggestions", []):
                print(f"      hint   : maybe manifest entry '{hint['candidate_key']}' "
                      f"({hint['rationale']})", file=stream)
    if report.findings:
        live = [f for f in report.findings
                if not f.get("stale_risk") and not f.get("suppressed")]
        held = [f for f in report.findings
                if f.get("stale_risk") or f.get("suppressed")]
        errors = [f for f in live if f["severity"] == "error"]
        warnings = [f for f in live if f["severity"] != "error"]
        print(file=stream)
        print(f" INSTALL ORDER & COMPATIBILITY  "
              f"({len(errors)} error, {len(warnings)} warning"
              f"{f', {len(held)} not counted' if held else ''})", file=stream)
        print(" Checked against your WeiDU log(s). Nothing was changed.", file=stream)
        for finding in errors + warnings:
            mark = "!!" if finding["severity"] == "error" else " -"
            print(f"   {mark} {finding['summary']}", file=stream)
            if finding.get("detail"):
                print(f"      {finding['detail']}", file=stream)

        if held:
            print(file=stream)
            print(" NOT COUNTED - the rule may no longer apply", file=stream)
            for finding in held:
                print(f"   ?  {finding['summary']}", file=stream)
                note = finding.get("suppressed") or finding.get("stale_risk")
                print(f"      {note}", file=stream)

    advised = [r for r in report.records if r.advisories]
    if advised:
        print(file=stream)
        print(" MOD HEALTH WARNINGS", file=stream)
        for record in advised:
            print(f"   {record.folder}", file=stream)
            for note in record.advisories:
                print(f"      - {note}", file=stream)

    discovered = [r for r in report.records if r.discovered_github]
    if discovered:
        print(file=stream)
        print(" DISCOVERED SOURCES - promote these into your manifest", file=stream)
        print(" These were resolved by searching your trusted owners, not by a", file=stream)
        print(" catalogue entry. Each one passed the strict .tp2 check, but adding", file=stream)
        print(" it to mod_downloads.json makes the next run deterministic:", file=stream)
        for record in discovered:
            print(f'   "tp2": "{record.folder}", "github": "{record.discovered_github}"',
                  file=stream)

    if report.warnings:
        print(f"\n {len(report.warnings)} warning(s); see the JSON report for detail.",
              file=stream)
