"""
Database connection factory for the football analytics project.

Reads DATABASE_URL from the environment (or .env file). Defaults to a local
SQLite file so there's zero setup to get started.

SQLite  → sqlite:///football_analytics.db
Postgres → postgresql://user:pass@localhost/football_analytics

The SQLAlchemy engine handles the dialect difference; the schema in
schema/schema.sql uses only standard SQL that works in both (with minor
exceptions noted below).

SQLite compatibility notes:
  - SERIAL → INTEGER PRIMARY KEY (handled by SQLAlchemy Column definitions)
  - NUMERIC(p,s) → REAL (SQLite has no fixed precision, stores as float)
  - Views are supported in SQLite
  - No schema namespaces in SQLite; ignore any "CREATE SCHEMA" statements

To migrate SQLite → Postgres later:
  Option A (simple, for a research DB):
    1. Set DATABASE_URL to postgres connection string
    2. Re-run all seed scripts (they check skip_existing)
  Option B (if you need to preserve data not re-derivable from CSVs):
    1. pip install pgloader
    2. pgloader sqlite:///football_analytics.db postgresql://user:pass@localhost/football_analytics
"""

import os
import pathlib

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Load .env from project root (one level up from scripts/)
_env_file = pathlib.Path(__file__).parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file)

# Default: SQLite file in project root
_DEFAULT_URL = "sqlite:///" + str(pathlib.Path(__file__).parent.parent / "football_analytics.db")
DATABASE_URL = os.environ.get("DATABASE_URL", _DEFAULT_URL)

_engine = None
_Session = None


def get_engine():
    global _engine
    if _engine is None:
        connect_args = {}
        if DATABASE_URL.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=False)
    return _engine


def get_session():
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine())
    return _Session()


def init_db():
    """Create all tables from schema.sql (SQLite-compatible subset)."""
    schema_path = pathlib.Path(__file__).parent.parent / "schema" / "schema.sql"
    if not schema_path.exists():
        raise FileNotFoundError(f"schema.sql not found at {schema_path}")

    engine = get_engine()
    sql = schema_path.read_text()

    # SQLite doesn't support all PostgreSQL syntax — strip the incompatible parts
    if DATABASE_URL.startswith("sqlite"):
        sql = _sqlite_compat(sql)

    # Execute statement by statement (SQLAlchemy text() doesn't handle multi-statement)
    with engine.begin() as conn:
        for stmt in _split_statements(sql):
            if stmt.strip():
                try:
                    conn.execute(text(stmt))
                except Exception as e:
                    # Some statements (like views that depend on not-yet-created tables) may
                    # fail on first run — log but continue; re-run to pick them up.
                    print(f"  [init_db] skipped: {e!s:.120}")


def _sqlite_compat(sql: str) -> str:
    """Strip PostgreSQL-specific syntax that SQLite doesn't understand."""
    import re
    # Remove REFERENCES constraints inline (SQLite ignores FK constraints by default anyway)
    # Remove CREATE INDEX ON expressions with functions
    # SERIAL → INTEGER (SQLAlchemy handles the autoincrement)
    sql = re.sub(r"\bSERIAL\b", "INTEGER", sql)
    # Remove unsupported column-level REFERENCES (keep table-level FKs if you prefer)
    sql = re.sub(r"\s+REFERENCES\s+\w+\([^)]+\)", "", sql)
    # Remove DEFAULT NOW() — SQLite uses CURRENT_TIMESTAMP
    sql = sql.replace("DEFAULT NOW()", "DEFAULT CURRENT_TIMESTAMP")
    # Remove schema-qualified names if any
    sql = re.sub(r"\bpublic\.", "", sql)
    return sql


def _split_statements(sql: str) -> list[str]:
    """Split a SQL file into individual statements on semicolons, skipping comments."""
    import re
    # Remove -- line comments
    sql = re.sub(r"--[^\n]*", "", sql)
    # Remove /* */ block comments
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return [s.strip() for s in sql.split(";") if s.strip()]


class Base(DeclarativeBase):
    pass


if __name__ == "__main__":
    print(f"Database URL: {DATABASE_URL}")
    init_db()
    print("Schema initialized.")
    with get_engine().connect() as conn:
        result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")
                              if DATABASE_URL.startswith("sqlite")
                              else text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
        tables = [r[0] for r in result]
    print(f"Tables created ({len(tables)}): {', '.join(sorted(tables))}")
