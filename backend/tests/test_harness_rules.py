# backend/tests/test_harness_rules.py
from ocd_core.harness import rules


def test_mode_aliases():
    assert rules.normalize_mode("auto") == "bypass"
    assert rules.normalize_mode("ask") == "default"
    assert rules.normalize_mode("acceptEdits") == "acceptEdits"
    assert rules.normalize_mode("nonsense") == "strict"  # unknown fails closed


def test_deny_beats_allow():
    rs = rules.RuleSet(allow=["bash(*)"], deny=["bash(rm *)"])
    assert rs.decision("bash", {"command": "rm -rf x"}) == "deny"
    assert rs.decision("bash", {"command": "ls"}) == "allow"


def test_ask_rule():
    rs = rules.RuleSet(ask=["web_fetch"])
    assert rs.decision("web_fetch", {"url": "http://x"}) == "ask"


def test_matcher_glob_on_bash_command():
    rs = rules.RuleSet(allow=["bash(git *)"])
    assert rs.decision("bash", {"command": "git status"}) == "allow"
    assert rs.decision("bash", {"command": "npm i"}) is None  # no rule matched


def test_bare_tool_matches_all_invocations():
    rs = rules.RuleSet(allow=["read_file"])
    assert rs.decision("read_file", {"path": "a"}) == "allow"


def test_gate_default_mode_edit_prompts_without_rule():
    # In default mode a file edit with no matching rule -> prompt (ask).
    assert rules.gate("edit_file", {"path": "a"}, "default", rules.RuleSet()) == "ask"


def test_gate_accept_edits_auto_approves_file_edit():
    assert rules.gate("edit_file", {"path": "a"}, "acceptEdits", rules.RuleSet()) == "allow"


def test_gate_plan_mode_blocks_write():
    assert rules.gate("write_file", {"path": "a"}, "plan", rules.RuleSet()) == "deny"


def test_gate_plan_mode_allows_read():
    assert rules.gate("read_file", {"path": "a"}, "plan", rules.RuleSet()) == "allow"


def test_gate_bypass_allows_everything():
    assert rules.gate("bash", {"command": "rm -rf /"}, "bypass", rules.RuleSet()) == "allow"


def test_gate_rule_overrides_mode():
    rs = rules.RuleSet(deny=["bash(rm *)"])
    assert rules.gate("bash", {"command": "rm x"}, "bypass", rs) == "deny"
