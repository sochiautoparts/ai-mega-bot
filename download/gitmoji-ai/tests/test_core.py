"""Tests for GitMoji AI"""

import pytest
from gitmoji_ai.ai_engine import analyze_diff, _fallback_commit_messages, GITMOJI_MAP
from gitmoji_ai.changelog import parse_commit_subject, group_commits_by_type


class TestDiffAnalysis:
    """Test git diff analysis"""

    def test_empty_diff(self):
        result = analyze_diff("")
        assert result.files_changed == 0
        assert result.lines_added == 0
        assert result.lines_removed == 0

    def test_single_file_diff(self):
        diff = """diff --git a/hello.py b/hello.py
new file mode 100644
index 0000000..e69de29
--- /dev/null
+++ b/hello.py
@@ -0,0 +1,3 @@
+def hello():
+    print("Hello, World!")
+    return True
"""
        result = analyze_diff(diff)
        assert result.files_changed == 1
        assert result.lines_added == 3
        assert result.is_new_feature is True

    def test_bug_fix_diff(self):
        diff = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -10,5 +10,5 @@
-def calculate(x):
+def calculate(x, y):
-    return x * 2
+    return x + y  # fix: correct calculation
"""
        result = analyze_diff(diff)
        assert result.is_bug_fix is True

    def test_docs_diff(self):
        diff = """diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1,3 +1,5 @@
 # My Project
+
+Documentation update here.
"""
        result = analyze_diff(diff)
        assert result.is_docs is True

    def test_test_diff(self):
        diff = """diff --git a/test_app.py b/test_app.py
new file mode 100644
--- /dev/null
+++ b/test_app.py
@@ -0,0 +1,5 @@
+def test_hello():
+    assert True
"""
        result = analyze_diff(diff)
        assert result.is_test is True


class TestCommitParsing:
    """Test conventional commit parsing"""

    def test_parse_feat(self):
        entry = parse_commit_subject("feat(auth): add login functionality")
        assert entry.type == "feat"
        assert entry.scope == "auth"
        assert "login" in entry.description

    def test_parse_fix(self):
        entry = parse_commit_subject("fix: resolve crash on startup")
        assert entry.type == "fix"
        assert entry.scope == ""

    def test_parse_no_type(self):
        entry = parse_commit_subject("update something")
        assert entry.type == "chore"

    def test_parse_complex_scope(self):
        entry = parse_commit_subject("feat(api/v2): add new endpoint")
        assert entry.type == "feat"


class TestFallbackCommits:
    """Test fallback commit generation (without AI)"""

    def test_feature_commit(self):
        diff = """diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,3 @@
+# New feature
+def new_feature():
+    pass
"""
        suggestions = _fallback_commit_messages(diff, "conventional")
        assert len(suggestions) >= 1
        assert suggestions[0].type == "feat"

    def test_emoji_style(self):
        suggestions = _fallback_commit_messages("new file mode\n+feature", "emoji")
        assert any(e in suggestions[0].message for e in GITMOJI_MAP.values())

    def test_empty_diff_fallback(self):
        suggestions = _fallback_commit_messages("", "conventional")
        assert len(suggestions) >= 1


class TestChangelogGrouping:
    """Test changelog grouping by type"""

    def test_group_mixed_commits(self):
        commits = [
            {"subject": "feat: add feature", "hash": "abc1234", "author": "Dev", "date": "2024-01-01", "body": ""},
            {"subject": "fix: fix bug", "hash": "def5678", "author": "Dev", "date": "2024-01-01", "body": ""},
            {"subject": "docs: update readme", "hash": "ghi9012", "author": "Dev", "date": "2024-01-01", "body": ""},
        ]
        grouped = group_commits_by_type(commits)
        assert "Features" in grouped
        assert "Bug Fixes" in grouped
        assert "Documentation" in grouped

    def test_empty_commits(self):
        grouped = group_commits_by_type([])
        assert len(grouped) == 0


class TestGitmojiMap:
    """Test GitMoji emoji mapping"""

    def test_all_conventional_types_have_emoji(self):
        from gitmoji_ai.ai_engine import CONVENTIONAL_TYPES
        for t in CONVENTIONAL_TYPES:
            assert t in GITMOJI_MAP, f"Missing emoji for type: {t}"

    def test_emoji_are_unicode(self):
        for key, emoji in GITMOJI_MAP.items():
            assert len(emoji) >= 1, f"Empty emoji for {key}"
