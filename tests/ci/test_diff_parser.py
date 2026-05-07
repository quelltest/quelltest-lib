"""Tests for quell/ci/diff_parser.py"""
from pathlib import Path
import pytest

from quell.ci.diff_parser import _parse_unified_diff, ChangedLines


SAMPLE_DIFF = """\
diff --git a/src/payments.py b/src/payments.py
index abc123..def456 100644
--- a/src/payments.py
+++ b/src/payments.py
@@ -47,3 +47,5 @@
 def process():
-    return False
+    return True
+    # added line
diff --git a/src/utils.py b/src/utils.py
index 111..222 100644
--- a/src/utils.py
+++ b/src/utils.py
@@ -10,2 +10,3 @@
-def old():
+def new():
+    pass
"""

MULTI_HUNK_DIFF = """\
--- a/src/calc.py
+++ b/src/calc.py
@@ -5,2 +5,3 @@
-    x = 1
+    x = 2
+    y = 3
@@ -20,1 +21,2 @@
-    return x
+    return x + y
"""

NON_PYTHON_DIFF = """\
--- a/styles.css
+++ b/styles.css
@@ -1,1 +1,2 @@
-.color: red;
+.color: blue;
"""


ROOT = Path("/project")


def test_parse_basic_diff_extracts_files():
    result = _parse_unified_diff(SAMPLE_DIFF, ROOT)
    paths = [r.file_path for r in result]
    assert ROOT / "src/payments.py" in paths
    assert ROOT / "src/utils.py" in paths


def test_parse_extracts_line_ranges():
    result = _parse_unified_diff(SAMPLE_DIFF, ROOT)
    payments = next(r for r in result if r.file_path.name == "payments.py")
    # hunk: +47,5 → lines 47..51
    assert (47, 51) in payments.line_ranges


def test_parse_multi_hunk_same_file():
    result = _parse_unified_diff(MULTI_HUNK_DIFF, ROOT)
    assert len(result) == 1
    calc = result[0]
    assert (5, 7) in calc.line_ranges    # +5,3
    assert (21, 22) in calc.line_ranges  # +21,2


def test_non_python_files_excluded():
    result = _parse_unified_diff(NON_PYTHON_DIFF, ROOT)
    assert result == []


def test_empty_diff_returns_empty():
    result = _parse_unified_diff("", ROOT)
    assert result == []


def test_changed_lines_contains_line():
    cl = ChangedLines(file_path=Path("x.py"), line_ranges=[(10, 20), (50, 55)])
    assert cl.contains_line(10)
    assert cl.contains_line(15)
    assert cl.contains_line(20)
    assert cl.contains_line(50)
    assert not cl.contains_line(9)
    assert not cl.contains_line(21)
    assert not cl.contains_line(56)


def test_single_line_hunk():
    diff = """\
--- a/src/x.py
+++ b/src/x.py
@@ -5 +5 @@
-old
+new
"""
    result = _parse_unified_diff(diff, ROOT)
    assert len(result) == 1
    # count=1 (default when omitted) → range (5, 5)
    assert (5, 5) in result[0].line_ranges


def test_zero_count_hunk_excluded():
    """A hunk with count=0 means the range is a deletion — no added lines."""
    diff = """\
--- a/src/x.py
+++ b/src/x.py
@@ -5,3 +5,0 @@
-line1
-line2
-line3
"""
    result = _parse_unified_diff(diff, ROOT)
    # count=0 → should produce no range for the new file
    if result:
        assert result[0].line_ranges == []
