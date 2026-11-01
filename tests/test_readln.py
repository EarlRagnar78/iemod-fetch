"""
The questions a mod will ask, read before installing (GUI-AUDIT M8 item 48,
ADR-0049). Measured on 105 mods of the reference build (tools/readln_census.py,
docs/TESTING.md): these cases are the shapes found there.
"""
from iemod_fetch.readln import scan

TP2 = """BACKUP ~mymod/backup~
AUTHOR ~me~
VERSION ~v2~
LANGUAGE ~English~ ~english~ ~mymod/tra/english/setup.tra~
LANGUAGE ~Italiano~ ~italian~ ~mymod/tra/italian/setup.tra~
"""
TRA_EN = "@1 = ~Which portraits do you want? 1. Original 2. New~\n@2 = ~Enter a percentage:~\n"
TRA_IT = "@1 = ~Quali ritratti vuoi? 1. Originali 2. Nuovi~\n@2 = ~Inserisci una percentuale:~\n"


def files(tp2_body: str, **extra) -> dict[str, str]:
    out = {"mymod/setup-mymod.tp2": TP2 + tp2_body,
           "mymod/tra/english/setup.tra": TRA_EN, "mymod/tra/italian/setup.tra": TRA_IT}
    # mymod__lib__x_tpa -> mymod/lib/x.tpa
    out.update({k.replace("__", "/")[::-1].replace("_", ".", 1)[::-1]: v
                for k, v in extra.items()})
    return out


def test_a_question_in_a_component_is_keyed_by_its_tra_string():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10 DESIGNATED 100
  PRINT @1
  ACTION_READLN portraits
BEGIN @11 DESIGNATED 200
  COPY_EXISTING ~sw1h01.itm~ ~override~
"""))
    [prompt] = found.of(100)
    assert prompt.ref == "@1" and prompt.key == "@1"
    assert prompt.text.startswith("Which portraits do you want?")
    assert prompt.variable == "portraits" and prompt.line == 9
    assert not prompt.conditional and not prompt.repeats
    assert found.of(200) == []


def test_the_text_is_the_chosen_languages_the_key_is_not():
    body = "\nBEGIN @10\n  PRINT @2\n  ACTION_READLN chance\n"
    english = scan("mymod/setup-mymod.tp2", files(body), language_index=0).of(0)[0]
    italian = scan("mymod/setup-mymod.tp2", files(body), language_index=1).of(0)[0]
    assert english.text == "Enter a percentage:"
    assert italian.text == "Inserisci una percentuale:"
    assert english.key == italian.key == "@2"


def test_questions_in_a_launched_function_and_an_included_file_are_the_components():
    found = scan("mymod/setup-mymod.tp2", files("""
ALWAYS
  INCLUDE ~%MOD_FOLDER%/lib/functions.tph~
END
BEGIN @10
  LAF ask_portraits END
BEGIN @11
  ACTION_INCLUDE ~%MOD_FOLDER%/lib/chance.tpa~
""", mymod__lib__functions_tph="""
DEFINE_ACTION_FUNCTION ask_portraits BEGIN
  PRINT @1
  ACTION_READLN portraits
END
""", mymod__lib__chance_tpa="PRINT @2\nACTION_READLN chance\n"))
    assert [(p.ref, p.via) for p in found.of(0)] == [("@1", "function ask_portraits")]
    assert [(p.ref, p.via, p.file) for p in found.of(1)] == [
        ("@2", "include %MOD_FOLDER%/lib/chance.tpa", "mymod/lib/chance.tpa")]
    assert found.unread == []


def test_a_file_named_after_the_component_number_is_the_one_read():
    """Tweaks Anthology: `cdtweaks/lib/comp_%COMPONENT_NUMBER%_prompts.tpa`,
    in its ALWAYS block - WeiDU runs ALWAYS before each component."""
    found = scan("mymod/setup-mymod.tp2", files("""
ALWAYS
  ACTION_IF FILE_EXISTS ~mymod/lib/comp_%COMPONENT_NUMBER%_prompts.tpa~ BEGIN
    INCLUDE ~mymod/lib/comp_%COMPONENT_NUMBER%_prompts.tpa~
  END
END
BEGIN @10 DESIGNATED 3183
BEGIN @11 DESIGNATED 3184
""", mymod__lib__comp_3183_prompts_tpa="PRINT @1\nACTION_READLN portraits\n"))
    [prompt] = found.of(3183)
    assert prompt.via == "always" and prompt.conditional
    assert found.of(3184) == []
    assert found.unread == []          # 3184 has none: FILE_EXISTS guards it


def test_a_question_asked_until_valid_and_one_asked_only_sometimes():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  OUTER_SET valid = 0
  OUTER_WHILE (valid = 0) BEGIN
    PRINT @2
    ACTION_READLN chance
    ACTION_IF IS_AN_INT chance BEGIN OUTER_SET valid = 1 END
  END
  ACTION_IF NOT FILE_EXISTS ~mymod/prefs.txt~ BEGIN
    PRINT @1
    ACTION_READLN portraits
  END
"""))
    asked = found.of(0)
    assert [(p.ref, p.repeats, p.conditional) for p in asked] == [
        ("@2", True, False), ("@1", False, True)]


def test_a_path_built_at_install_time_is_said_unread_not_guessed():
    """SCS includes its SFO library through %sfo_loc%, set while installing."""
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  OUTER_SPRINT sfo_loc ~lib~
  INCLUDE ~%MOD_FOLDER%/%sfo_loc%/tools.tpa~
"""))
    assert found.of(0) == []
    assert found.unread == ["include %MOD_FOLDER%/%sfo_loc%/tools.tpa (a path built from variables)"]


def test_a_constant_set_before_the_components_builds_a_path():
    """EEUITweaks: `OUTER_SPRINT PKGNAME ~EEUITweaks~`, then
    `INCLUDE ~%PKGNAME%/include/...~`."""
    found = scan("mymod/setup-mymod.tp2", files("""
OUTER_SPRINT PKGNAME ~mymod~
BEGIN @10
  INCLUDE ~%PKGNAME%/include/update.tpa~
""", mymod__include__update_tpa="PRINT @1\nACTION_READLN portraits\n"))
    assert [p.ref for p in found.of(0)] == ["@1"]


def test_a_file_written_inside_the_tp2_is_read():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  ACTION_INCLUDE ~./inlined/ask.tpa~
<<<<<<<< ./inlined/ask.tpa
PRINT @2
ACTION_READLN chance
>>>>>>>>
"""))
    assert [p.ref for p in found.of(0)] == ["@2"]


def test_a_question_printed_as_text_has_no_ref_and_keys_by_its_text():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  PRINT ~Press a key to continue~
  ACTION_READLN dummy
"""))
    [prompt] = found.of(0)
    assert prompt.ref == "" and prompt.key == "Press a key to continue"


def test_a_function_calling_itself_does_not_loop():
    found = scan("mymod/setup-mymod.tp2", files("""
DEFINE_ACTION_FUNCTION again BEGIN
  PRINT @1
  ACTION_READLN portraits
  LAF again END
END
BEGIN @10
  LAF again END
"""))
    assert [p.ref for p in found.of(0)] == ["@1"]


def test_weidus_own_functions_are_not_reported():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  LAF HANDLE_CHARSETS INT_VAR infer_charsets = 1 END
"""))
    assert found.of(0) == [] and found.unread == []


def test_a_tp2_not_given_is_said_so():
    found = scan("mymod/setup-mymod.tp2", {})
    assert found.components == {} and found.unread == ["mymod/setup-mymod.tp2 (not given)"]


# ---------------------------------------------------------- review of #101
def test_a_laf_end_does_not_close_the_block_it_sits_in():
    """`LAF name ... END` ends with an END of its own: a function body, an IF,
    a loop and ALWAYS all go on after it (4,714 of 7,601 function spans in the
    corpus were cut at their first LAF before)."""
    found = scan("mymod/setup-mymod.tp2", files("""
ALWAYS
  LAF HANDLE_CHARSETS INT_VAR infer_charsets = 1 END
  INCLUDE ~mymod/lib/lib.tph~
END
BEGIN @10
  LAF ask END
BEGIN @11
  ACTION_IF GAME_IS ~eet~ BEGIN
    LAF HANDLE_AUDIO END
    PRINT @2
    ACTION_READLN chance
  END
BEGIN @12
  OUTER_WHILE (x = 0) BEGIN
    LAF HANDLE_AUDIO END
    PRINT @2
    ACTION_READLN chance
  END
""", mymod__lib__lib_tph="""
DEFINE_ACTION_FUNCTION ask BEGIN
  LAF HANDLE_AUDIO END
  PRINT @1
  ACTION_READLN portraits
END
"""))
    assert [(p.ref, p.via) for p in found.of(0)] == [("@1", "function ask")]
    assert [(p.conditional, p.repeats) for p in found.of(1)] == [(True, False)]
    assert [(p.conditional, p.repeats) for p in found.of(2)] == [(False, True)]


def test_a_match_default_branch_is_conditional_and_a_try_leaks_nothing():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  ACTION_MATCH ~%x%~ WITH ~a~ BEGIN OUTER_SET y = 1 END
  DEFAULT
    PRINT @1
    ACTION_READLN portraits
  END
  COPY_EXISTING ~a.itm~ ~override~
    PATCH_TRY READ_LONG 0 z WITH DEFAULT END
  INNER_ACTION BEGIN
    PRINT @2
    ACTION_READLN chance
  END
"""))
    assert [(p.ref, p.conditional) for p in found.of(0)] == [("@1", True), ("@2", False)]


def test_bash_for_repeats():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  ACTION_BASH_FOR ~override~ ~.*\\.itm~ BEGIN
    PRINT @2
    ACTION_READLN chance
  END
"""))
    assert found.of(0)[0].repeats


def test_the_line_is_the_files_after_a_block_comment():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  /* a comment
     on three
     lines */
  PRINT @1
  ACTION_READLN portraits
"""))
    assert found.of(0)[0].line == 12


def test_a_readln_after_fail_is_never_asked():
    """TDDz: `FAIL ~...press Enter~` then `ACTION_READLN pause` - FAIL stops."""
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  ACTION_IF NOT FILE_EXISTS ~x.bam~ BEGIN
    FAIL ~Missing x.bam, press Enter~
    ACTION_READLN pause
  END
"""))
    assert found.of(0) == []


def test_a_question_printed_from_a_variable_is_unknown_and_keyed_by_its_place():
    """LCA: `PRINT ~%xa_prompt%~` - the text is set elsewhere. Two such
    questions must not share a key, or one answer would answer both."""
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  OUTER_SPRINT p @1
  PRINT ~%p%~
  ACTION_READLN a
BEGIN @11
  OUTER_SPRINT p @2
  PRINT ~%p%~
  ACTION_READLN b
"""))
    first, second = found.of(0)[0], found.of(1)[0]
    assert not first.keyed and first.text == "" and first.ref == ""
    assert first.key != second.key and first.key and second.key


def test_an_include_whose_whole_path_is_a_variable_is_unread():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  INCLUDE %lib_path%
"""))
    assert found.unread == ["include %lib_path% (a path built from variables)"]


def test_a_function_defined_in_a_tpc_file_is_followed():
    """SCS keeps functions in .tpc files (sfo2e/sfo_init.tpc)."""
    found = scan("mymod/setup-mymod.tp2", files("""
ALWAYS INCLUDE ~mymod/lib/init.tpc~ END
BEGIN @10
  LAF ask END
""", mymod__lib__init_tpc="""
DEFINE_ACTION_FUNCTION ask BEGIN PRINT @1 ACTION_READLN portraits END
"""))
    assert [p.ref for p in found.of(0)] == ["@1"]


# ---------------------------------------------------------- second review of #101
def test_keywords_are_case_sensitive_a_variable_named_fail_or_end_is_not_one():
    """`OUTER_SET fail = 0` (SCS) and `SET end = 5` (Aura) are variables."""
    found = scan("mymod/setup-mymod.tp2", files("""
DEFINE_PATCH_FUNCTION f BEGIN
  SET end = 5
  PATCH_PRINT @1
  PATCH_READLN a
END
BEGIN @10
  OUTER_SET fail = 0
  PRINT @2
  ACTION_READLN x
  COPY_EXISTING ~a.itm~ ~override~ LPF f END
"""))
    assert [p.ref for p in found.of(0)] == ["@2", "@1"]


def test_a_fail_in_a_try_body_leaves_its_handlers_alive():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  ACTION_TRY
    FAIL ~boom~
  WITH DEFAULT
    PRINT @1
    ACTION_READLN x
  END
"""))
    [prompt] = found.of(0)
    assert prompt.ref == "@1" and prompt.conditional


def test_an_else_default_value_does_not_make_the_next_block_conditional():
    """`READ_LONG 0 x ELSE 0`: a default value, not an IF's ELSE."""
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  COPY_EXISTING ~a.itm~ ~override~
    READ_LONG 0 x ELSE 0
    INNER_ACTION BEGIN
      PRINT @1
      ACTION_READLN a
    END
"""))
    assert [p.conditional for p in found.of(0)] == [False]


def test_a_readln_after_abort_is_never_asked():
    found = scan("mymod/setup-mymod.tp2", files("""
BEGIN @10
  ABORT ~not on this game~
  PRINT @1
  ACTION_READLN a
"""))
    assert found.of(0) == []


def test_an_unknown_question_is_keyed_by_its_component_too():
    """LCA: one function asks what its caller passes; two components calling
    it get different keys (one component calling it twice would not - which
    is why an unknown question is never answered from a stored answer)."""
    found = scan("mymod/setup-mymod.tp2", files("""
DEFINE_ACTION_FUNCTION ask STR_VAR prompt = ~~ BEGIN
  PRINT ~%prompt%~
  ACTION_READLN answer
END
BEGIN @10
  LAF ask STR_VAR prompt = @1 END
BEGIN @11
  LAF ask STR_VAR prompt = @2 END
"""))
    first, second = found.of(0)[0], found.of(1)[0]
    assert not first.keyed and first.key != second.key
