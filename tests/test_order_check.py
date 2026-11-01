"""
The check after a drop on the order page (GUI-AUDIT M5b item 31): only the
rules the moved unit is in are looked at again - and that is always the full
check's answer, whatever the order, the rules and the moves (that property is
in test_properties.py, which skips itself without Hypothesis).
"""
from iemod_fetch.ordering import broken_pairs


def test_a_unit_after_one_a_rule_puts_before_it_breaks_that_pair():
    before = {"b": {"a"}, "c": {"a", "b"}}
    assert broken_pairs(["a", "b", "c"], before) == set()
    assert broken_pairs(["b", "a", "c"], before) == {("b", "a")}
    assert broken_pairs(["c", "b"], before) == {("c", "b")}        # "a" not in it


def test_the_benchmark_finds_no_disagreement_and_says_so(tmp_path):
    import json
    from tools import order_check_benchmark
    out = tmp_path / "out.json"
    assert order_check_benchmark.main(["--size", "60", "--moves", "40",
                                       "--json", str(out)]) == 0
    result = json.loads(out.read_text())["synthetic"]
    assert result["units"] == 60 and result["disagreements"] == 0
    assert set(result["after a move (ms)"]) == {"p50", "p95"}
