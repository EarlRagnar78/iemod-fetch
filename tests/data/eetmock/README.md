# Mock EET install

A realistic two-phase EET setup for `tests/test_eet_mock.py`, built from the
mods' **real** install-time constraints.

`Mods/` holds excerpts: for each component used, only its `BEGIN` line and the
flag lines WeiDU enforces (`DESIGNATED`, `REQUIRE_*`, `FORBID_COMPONENT`, a body
`ABORT`), verbatim from the upstream repository at the commit named in each
file's header. The generator re-parsed every excerpt and refused to write it
unless it read exactly as the full tp2 does. `eet/tbl/compatibility.tbl` and the
merge-check block at the end of `eet/EET.tp2` are EET's own, unchanged. None of
this is installable; each mod's own licence applies to its lines.

The two logs are what an operator might hand over, mistakes included:

| Mistake | Where it comes from |
|---|---|
| Tweaks Anthology installed on BG:EE | EET's `compatibility.tbl` has no `CDTWEAKS`, so EET refuses the merge |
| EET_end listed first | the catalogue and EET_end's own REQUIRE put it last |
| EEFixPack in the EET phase | EEFixPack: `REQUIRE_PREDICATE !GAME_IS ~eet~` |
| SCS #5900 before Ascension | Ascension: `FORBID_COMPONENT ~setup-stratagems.tp2~ ~5900~` (Ascension first) |
| Tweaks #2370 and SCS #4100 together | SCS FORBIDs it one-sidedly: WeiDU accepts SCS first; `rules/` holds BWS-NG's verbatim rule that classes them incompatible |
| Tweaks #4010 on EET | its `GAME_IS` lists BG2/BG2EE/BGT, not EET |
