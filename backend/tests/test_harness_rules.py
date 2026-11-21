# backend/tests/test_harness_rules.py
import json

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
    # non-catastrophic command: rm -rf / is now a hard deny even in bypass (Task 14b breaker)
    assert rules.gate("bash", {"command": "npm install"}, "bypass", rules.RuleSet()) == "allow"


def test_gate_rule_overrides_mode():
    rs = rules.RuleSet(deny=["bash(rm *)"])
    assert rules.gate("bash", {"command": "rm x"}, "bypass", rs) == "deny"


def test_load_claude_rules(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(git *)", "Read"], "deny": ["Bash(rm *)"]}
    }))
    rs = rules.load_claude_ruleset(tmp_path)
    # Claude tool names map to ours; bare Read -> read_file
    assert rules.gate("bash", {"command": "git status"}, "default", rs) == "allow"
    assert rules.gate("bash", {"command": "rm x"}, "bypass", rs) == "deny"


def test_load_claude_rules_absent(tmp_path):
    rs = rules.load_claude_ruleset(tmp_path)
    assert rs.allow == [] and rs.deny == [] and rs.ask == []


def test_load_claude_rules_malformed(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{not json")
    rs = rules.load_claude_ruleset(tmp_path)  # must not raise
    assert isinstance(rs, rules.RuleSet)


def test_accept_edits_auto_allows_readonly_git():
    rs = rules.RuleSet()
    assert rules.gate("bash", {"command": "git status"}, "acceptEdits", rs) == "allow"
    assert rules.gate("bash", {"command": "git diff HEAD"}, "acceptEdits", rs) == "allow"


def test_accept_edits_asks_for_git_write():
    rs = rules.RuleSet()
    assert rules.gate("bash", {"command": "git push --force origin main"}, "acceptEdits", rs) == "ask"
    assert rules.gate("bash", {"command": "git reset --hard"}, "acceptEdits", rs) == "ask"
    assert rules.gate("bash", {"command": "git commit -m x"}, "acceptEdits", rs) == "ask"


def test_accept_edits_still_allows_safe_file_bash():
    assert rules.gate("bash", {"command": "mkdir foo"}, "acceptEdits", rules.RuleSet()) == "allow"


def test_catastrophic_rm_denied_even_in_bypass():
    for c in ["rm -rf /", "rm -rf /*", "sudo rm -rf /", "rm -fr ~", "rm -rf $HOME"]:
        assert rules.gate("bash", {"command": c}, "bypass", rules.RuleSet()) == "deny", c


def test_relative_rm_is_not_catastrophic():
    # a workspace-relative rm is not a hard-deny (acceptEdits doesn't auto-allow rm, so it asks)
    assert rules.gate("bash", {"command": "rm -rf build"}, "acceptEdits", rules.RuleSet()) != "deny"


def test_fork_bomb_and_disk_wipe_denied():
    assert rules.gate("bash", {"command": ":(){ :|:& };:"}, "bypass", rules.RuleSet()) == "deny"
    assert rules.gate("bash", {"command": "mkfs.ext4 /dev/sda1"}, "bypass", rules.RuleSet()) == "deny"
