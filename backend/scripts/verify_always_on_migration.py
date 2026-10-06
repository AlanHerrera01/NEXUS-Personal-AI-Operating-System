"""Compare what 0007_always_on declares against what the models declare.

Migration/model drift is the kind of defect that survives the whole test suite --
nothing in a unit test notices that the index the dispatcher depends on is absent
from the schema -- and then surfaces as a sequential scan, or worse as a missing
column, on the first real deployment. So the migration is checked against
``Base.metadata`` here by intercepting the ``op`` calls and diffing the two.

Run: python -m scripts.verify_always_on_migration
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import sqlalchemy as sa  # noqa: E402
from alembic import op  # noqa: E402

MIGRATION_PATH = BACKEND / "alembic" / "versions" / "0007_always_on.py"
TABLES = ("scheduled_jobs", "trigger_events", "job_executions", "proactive_rules")


class RecordedOp:
    """Stands in for alembic's op, recording calls instead of executing them."""

    def __init__(self) -> None:
        self.tables: dict[str, list] = {}
        self.indexes: list[tuple[str, str, tuple]] = []

    def create_table(self, name, *columns, **kwargs):
        self.tables[name] = [*columns, *kwargs.get("sa.Column", ())]

    def create_index(self, name, table, columns, **kwargs):
        self.indexes.append((name, table, tuple(columns)))

    # Nothing below is part of this migration's contract; recorded as no-ops so
    # importing the module does not explode if it grows a dependency.
    def drop_index(self, *a, **k): ...
    def drop_table(self, *a, **k): ...


def load_migration() -> RecordedOp:
    spec = importlib.util.spec_from_file_location("m0007", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    recorder = RecordedOp()
    original = module.op
    module.op = recorder
    try:
        module.upgrade()
    finally:
        module.op = original
    return recorder


def table_from_columns(name: str, column_specs: list) -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(name, metadata, *column_specs)


def main() -> int:
    from app.infrastructure.persistence.database import Base

    # Importing the models package registers every table on Base.metadata.
    import app.infrastructure.persistence.models  # noqa: F401

    recorder = load_migration()
    problems: list[str] = []

    for table_name in TABLES:
        if table_name not in recorder.tables:
            problems.append(f"{table_name}: migration does not create it")
            continue
        if table_name not in Base.metadata.tables:
            problems.append(f"{table_name}: model does not declare it")
            continue

        migrated = table_from_columns(table_name, recorder.tables[table_name])
        modelled = Base.metadata.tables[table_name]

        mig_cols = {c.name for c in migrated.columns}
        mod_cols = {c.name for c in modelled.columns}
        for missing in sorted(mod_cols - mig_cols):
            problems.append(f"{table_name}: column in model but not migration: {missing}")
        for extra in sorted(mig_cols - mod_cols):
            problems.append(f"{table_name}: column in migration but not model: {extra}")

        mig_idx = {(c[0], c[2]) for c in recorder.indexes if c[1] == table_name}
        mod_idx = {(i.name, tuple(c.name for c in i.columns)) for i in modelled.indexes}
        for missing in sorted(mod_idx - mig_idx):
            problems.append(f"{table_name}: index in model but not migration: {missing}")
        for extra in sorted(mig_idx - mod_idx):
            problems.append(f"{table_name}: index in migration but not model: {extra}")

        # Nullability drift is the subclass that actually breaks inserts.
        for name in sorted(mig_cols & mod_cols):
            mig_col = migrated.columns[name]
            mod_col = modelled.columns[name]
            if mig_col.nullable != mod_col.nullable:
                problems.append(
                    f"{table_name}.{name}: nullable migration={mig_col.nullable} "
                    f"model={mod_col.nullable}"
                )

        mig_unique = {
            tuple(c.name for c in cons.columns)
            for cons in migrated.constraints
            if cons.__class__.__name__ == "UniqueConstraint"
        }
        mod_unique = {
            tuple(c.name for c in cons.columns)
            for cons in modelled.constraints
            if cons.__class__.__name__ == "UniqueConstraint"
        }
        if mig_unique != mod_unique:
            problems.append(
                f"{table_name}: unique constraints migration={sorted(mig_unique)} "
                f"model={sorted(mod_unique)}"
            )

        mig_fk = {fk.target_fullname for fk in migrated.foreign_keys}
        mod_fk = {fk.target_fullname for fk in modelled.foreign_keys}
        if mig_fk != mod_fk:
            problems.append(
                f"{table_name}: foreign keys migration={sorted(mig_fk)} "
                f"model={sorted(mod_fk)}"
            )

    if problems:
        print("MIGRATION DRIFT DETECTED")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("0007_always_on matches the models for: " + ", ".join(TABLES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())