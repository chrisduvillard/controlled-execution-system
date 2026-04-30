"""Tests for MigrationSensor real implementation."""

from __future__ import annotations

import pytest

from ces.harness.sensors.migration import MigrationSensor


@pytest.fixture
def sensor():
    return MigrationSensor()


class TestMigrationSensorNoScope:
    """MigrationSensor with no migration files in scope."""

    @pytest.mark.asyncio
    async def test_empty_context_passes(self, sensor):
        result = await sensor.run({})
        assert result.passed is True
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_no_migration_files_passes(self, sensor):
        result = await sensor.run({"affected_files": ["src/main.py"]})
        assert result.passed is True
        assert "No migration files" in result.details

    @pytest.mark.asyncio
    async def test_missing_migration_file_is_skipped(self, sensor, tmp_path):
        """A migration file in affected_files but absent on disk is silently skipped."""
        result = await sensor.run(
            {
                "affected_files": ["alembic/versions/missing.py"],
                "project_root": str(tmp_path),
            }
        )
        # No content to scan -> no findings -> sensor passes.
        assert result.passed is True


class TestMigrationSensorDowngrade:
    """MigrationSensor downgrade method checks."""

    @pytest.mark.asyncio
    async def test_migration_with_downgrade_passes(self, sensor, tmp_path):
        mig_dir = tmp_path / "alembic" / "versions"
        mig_dir.mkdir(parents=True)
        (mig_dir / "001_initial.py").write_text(
            "def upgrade():\n    pass\n\ndef downgrade():\n    op.drop_table('users')\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["alembic/versions/001_initial.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_migration_missing_downgrade_fails(self, sensor, tmp_path):
        mig_dir = tmp_path / "alembic" / "versions"
        mig_dir.mkdir(parents=True)
        (mig_dir / "002_add_col.py").write_text(
            "def upgrade():\n    op.add_column('users', 'email')\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["alembic/versions/002_add_col.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "missing downgrade" in result.details

    @pytest.mark.asyncio
    async def test_migration_empty_downgrade_flagged(self, sensor, tmp_path):
        mig_dir = tmp_path / "alembic" / "versions"
        mig_dir.mkdir(parents=True)
        (mig_dir / "003_empty.py").write_text(
            "def upgrade():\n    op.add_column('x', 'y')\n\ndef downgrade():\n    pass\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["alembic/versions/003_empty.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "empty" in result.details.lower()

    @pytest.mark.asyncio
    async def test_migration_downgrade_with_only_docstring_flagged_as_empty(self, sensor, tmp_path):
        """A downgrade body containing only a docstring is treated as empty (line 152 continue).

        Exercises the Expr+Constant branch of _is_empty_body: the docstring
        statement is `ast.Expr(ast.Constant("..."))`, which the empty-body
        detector should skip just like a `pass`.
        """
        mig_dir = tmp_path / "alembic" / "versions"
        mig_dir.mkdir(parents=True)
        (mig_dir / "004_docstring_only.py").write_text(
            'def upgrade():\n    op.add_column("x", "y")\n\ndef downgrade():\n    """no-op"""\n',
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["alembic/versions/004_docstring_only.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "empty" in result.details.lower()


class TestMigrationSensorDestructiveOps:
    """MigrationSensor destructive operation detection."""

    @pytest.mark.asyncio
    async def test_drop_table_in_upgrade_flagged(self, sensor, tmp_path):
        mig_dir = tmp_path / "alembic" / "versions"
        mig_dir.mkdir(parents=True)
        (mig_dir / "004_drop.py").write_text(
            "def upgrade():\n    op.drop_table('old_table')\n\ndef downgrade():\n    op.create_table('old_table')\n",
            encoding="utf-8",
        )
        result = await sensor.run(
            {
                "affected_files": ["alembic/versions/004_drop.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "destructive" in result.details.lower()

    @pytest.mark.asyncio
    async def test_unparseable_file_skipped(self, sensor, tmp_path):
        mig_dir = tmp_path / "alembic" / "versions"
        mig_dir.mkdir(parents=True)
        (mig_dir / "005_bad.py").write_text("this is not valid python {{{}}", encoding="utf-8")
        result = await sensor.run(
            {
                "affected_files": ["alembic/versions/005_bad.py"],
                "project_root": str(tmp_path),
            }
        )
        assert result.passed is False
        assert "unparseable" in result.details
