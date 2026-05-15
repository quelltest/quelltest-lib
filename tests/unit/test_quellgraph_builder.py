"""Tests for QuellGraphBuilder — incremental SQLite graph builder."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from quell.graph.builder import BuildReport, QuellGraphBuilder


@pytest.fixture()
def db(tmp_path: Path) -> QuellGraphBuilder:
    builder = QuellGraphBuilder(tmp_path / ".quellgraph" / "graph.db")
    yield builder
    builder.close()


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """Write a minimal synthetic project for graph testing."""
    src = tmp_path / "src"
    src.mkdir()

    # payments.py — imports sqlalchemy (postgres tag)
    (src / "payments.py").write_text(
        textwrap.dedent("""\
        from sqlalchemy.orm import Session

        def process_payment(amount: float, db: Session) -> bool:
            '''Process a payment.

            Args:
                amount: payment amount
                db: database session

            Returns:
                True on success

            Raises:
                ValueError: if amount <= 0
            '''
            if amount <= 0:
                raise ValueError("amount must be > 0")
            return True

        def _build_audit_log(txn_id, amount, user):
            return {"id": txn_id}
        """),
        encoding="utf-8",
    )

    # utils.py — pure, no infra
    (src / "utils.py").write_text(
        textwrap.dedent("""\
        def validate_email(email: str) -> bool:
            '''Check email format.'''
            return "@" in email
        """),
        encoding="utf-8",
    )

    return src


class TestBuildReport:
    def test_build_returns_report(self, db: QuellGraphBuilder, project: Path) -> None:
        report = db.build(project)
        assert isinstance(report, BuildReport)
        assert report.total_files == 2
        assert report.reparsed == 2  # first run — everything is new
        assert report.functions >= 3
        assert report.classes >= 0

    def test_incremental_build_skips_unchanged_files(
        self, db: QuellGraphBuilder, project: Path
    ) -> None:
        db.build(project)
        report2 = db.build(project)  # nothing changed
        assert report2.reparsed == 0

    def test_incremental_build_reparses_changed_file(
        self, db: QuellGraphBuilder, project: Path
    ) -> None:
        db.build(project)
        # Touch payments.py — change a comment
        p = project / "payments.py"
        p.write_text(p.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        report2 = db.build(project)
        assert report2.reparsed == 1


class TestInfraTagPropagation:
    def test_sqlalchemy_import_tags_module_postgres(
        self, db: QuellGraphBuilder, project: Path
    ) -> None:
        db.build(project)
        import sqlite3
        conn = sqlite3.connect(str(db._db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT infra_tags FROM functions WHERE name='process_payment'"
        ).fetchone()
        conn.close()
        assert row is not None
        import json
        tags = json.loads(row["infra_tags"] or "[]")
        assert "postgres" in tags

    def test_pure_function_has_no_infra_tags(
        self, db: QuellGraphBuilder, project: Path
    ) -> None:
        db.build(project)
        import sqlite3, json
        conn = sqlite3.connect(str(db._db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT infra_tags, is_pure FROM functions WHERE name='validate_email'"
        ).fetchone()
        conn.close()
        assert row is not None
        tags = json.loads(row["infra_tags"] or "[]")
        assert tags == []
        assert row["is_pure"] == 1


class TestAnnotationCoverage:
    def test_fully_typed_function_has_high_coverage(
        self, db: QuellGraphBuilder, project: Path
    ) -> None:
        db.build(project)
        import sqlite3
        conn = sqlite3.connect(str(db._db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT annotation_coverage FROM functions WHERE name='process_payment'"
        ).fetchone()
        conn.close()
        assert row is not None
        # process_payment has 2 typed params (amount: float, db: Session) + no return annotation
        # typed_slots=2, total_slots=3 → ~0.67
        assert row["annotation_coverage"] >= 0.5

    def test_unannotated_function_has_zero_coverage(
        self, db: QuellGraphBuilder, project: Path
    ) -> None:
        db.build(project)
        import sqlite3
        conn = sqlite3.connect(str(db._db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT annotation_coverage FROM functions WHERE name='_build_audit_log'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["annotation_coverage"] == 0.0
