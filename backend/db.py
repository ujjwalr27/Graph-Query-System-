"""
Database module – loads JSONL/CSV dataset into SQLite and provides helpers.
Optimized: schema and sample data are cached after first load.
"""

import os
import json
import sqlite3
import glob
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "dodgeai.db")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

_connection: sqlite3.Connection | None = None

# ── Cached schema and sample data (built once at startup) ──
_schema_cache: dict[str, list[dict]] | None = None
_schema_text_cache: str | None = None
_sample_data_cache: dict[str, list[dict]] | None = None


def get_connection() -> sqlite3.Connection:
    """Return a shared SQLite connection (created on first call)."""
    global _connection
    if _connection is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _connection = sqlite3.connect(DB_PATH, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        # Enable WAL mode for better read concurrency
        _connection.execute("PRAGMA journal_mode=WAL")
        _connection.execute("PRAGMA synchronous=NORMAL")
    return _connection


def _sanitize_name(raw: str) -> str:
    """Convert a raw name to a clean SQLite-safe name."""
    name = raw.strip()
    name = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    return name.lower().strip("_")


def load_data_into_db() -> list[str]:
    """
    Scan DATA_DIR for data files and load into SQLite.
    Supports:
      - Flat CSV/Excel files in DATA_DIR
      - Subdirectories containing .jsonl files (each subdir = one table)
      - Nested dataset dirs (e.g., sap-o2c-data/) with entity subdirectories
    Returns list of table names created.
    """
    conn = get_connection()
    tables_created = []

    # Strategy 1: Look for subdirectories that contain .jsonl files (primary)
    jsonl_tables = _load_jsonl_dirs(conn, DATA_DIR)
    tables_created.extend(jsonl_tables)

    # Strategy 2: Load flat CSV/Excel files in DATA_DIR
    csv_tables = _load_flat_files(conn, DATA_DIR)
    tables_created.extend(csv_tables)

    if not tables_created:
        logger.warning("No data files found in %s", DATA_DIR)
        return tables_created

    conn.commit()

    # Pre-cache schema and sample data after loading
    _build_caches()

    return tables_created


def _load_jsonl_dirs(conn: sqlite3.Connection, base_dir: str) -> list[str]:
    """
    Recursively find directories containing .jsonl files.
    Each directory becomes a table (directory name = table name).
    """
    tables = []
    base_path = Path(base_dir)

    # Find all .jsonl files recursively
    jsonl_files = list(base_path.rglob("*.jsonl"))
    if not jsonl_files:
        return tables

    # Group by parent directory
    dir_groups: dict[str, list[Path]] = {}
    for f in jsonl_files:
        parent = str(f.parent)
        dir_groups.setdefault(parent, []).append(f)

    for dir_path, files in sorted(dir_groups.items()):
        # Use the directory name as the table name
        dir_name = Path(dir_path).name
        table_name = _sanitize_name(dir_name)

        logger.info("Loading JSONL dir '%s' -> table '%s' (%d files)", dir_name, table_name, len(files))

        all_records = []
        for filepath in sorted(files):
            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            all_records.append(json.loads(line))
            except Exception as e:
                logger.error("Failed to read %s: %s", filepath, e)
                continue

        if not all_records:
            logger.warning("  -> No records found in %s", dir_path)
            continue

        df = pd.DataFrame(all_records)
        # Sanitize column names
        df.columns = [_sanitize_name(c) for c in df.columns]

        # SQLite can't store dicts/lists — serialize them to JSON strings
        for col in df.columns:
            if df[col].apply(lambda x: isinstance(x, (dict, list))).any():
                df[col] = df[col].apply(
                    lambda x: json.dumps(x) if isinstance(x, (dict, list)) else x
                )

        df.to_sql(table_name, conn, if_exists="replace", index=False)
        tables.append(table_name)
        logger.info("  -> %d rows, %d columns", len(df), len(df.columns))

    return tables


def _load_flat_files(conn: sqlite3.Connection, base_dir: str) -> list[str]:
    """Load flat CSV/Excel files directly in base_dir."""
    tables = []
    patterns = [
        os.path.join(base_dir, "*.csv"),
        os.path.join(base_dir, "*.xlsx"),
        os.path.join(base_dir, "*.xls"),
    ]
    files = []
    for p in patterns:
        files.extend(glob.glob(p))

    for filepath in sorted(files):
        table_name = _sanitize_name(os.path.splitext(os.path.basename(filepath))[0])
        logger.info("Loading %s -> table '%s'", os.path.basename(filepath), table_name)

        try:
            if filepath.endswith((".xlsx", ".xls")):
                df = pd.read_excel(filepath)
            else:
                df = pd.read_csv(filepath)
        except Exception as e:
            logger.error("Failed to load %s: %s", filepath, e)
            continue

        df.columns = [_sanitize_name(c) for c in df.columns]
        df.to_sql(table_name, conn, if_exists="replace", index=False)
        tables.append(table_name)
        logger.info("  -> %d rows, %d columns", len(df), len(df.columns))

    return tables


def _build_caches():
    """Build schema and sample data caches once after data is loaded."""
    global _schema_cache, _schema_text_cache, _sample_data_cache

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]

    # Cache schema
    schema = {}
    for table in tables:
        cursor.execute(f"PRAGMA table_info('{table}')")
        columns = [{"name": row[1], "type": row[2]} for row in cursor.fetchall()]
        schema[table] = columns
    _schema_cache = schema

    # Cache schema text
    lines = []
    for table, columns in schema.items():
        col_defs = ", ".join(f"{c['name']} ({c['type']})" for c in columns)
        lines.append(f"Table: {table}\n  Columns: {col_defs}")
    _schema_text_cache = "\n\n".join(lines)

    # Cache sample data for all tables
    samples = {}
    for table in tables:
        try:
            cursor.execute(f"SELECT * FROM '{table}' LIMIT 3")
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            samples[table] = [dict(zip(columns, row)) for row in rows]
        except Exception:
            samples[table] = []
    _sample_data_cache = samples


def get_schema() -> dict[str, list[dict]]:
    """Return the cached database schema."""
    if _schema_cache is not None:
        return _schema_cache
    _build_caches()
    return _schema_cache


def get_schema_text() -> str:
    """Return cached formatted schema text for LLM prompts."""
    if _schema_text_cache is not None:
        return _schema_text_cache
    _build_caches()
    return _schema_text_cache


def get_sample_data(table: str, limit: int = 3) -> list[dict]:
    """Return cached sample rows from a table."""
    if _sample_data_cache is not None and table in _sample_data_cache:
        return _sample_data_cache[table][:limit]
    # Fallback: direct query
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM '{table}' LIMIT {limit}")
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def execute_sql(sql: str) -> list[dict]:
    """Execute a read-only SQL query and return results as list of dicts."""
    conn = get_connection()
    cursor = conn.cursor()

    # Safety: only allow SELECT / WITH
    stripped = sql.strip().upper()
    if not stripped.startswith("SELECT") and not stripped.startswith("WITH"):
        raise ValueError("Only SELECT / WITH queries are allowed.")

    # Add LIMIT if not present to prevent massive result sets
    if "LIMIT" not in stripped:
        sql = sql.rstrip().rstrip(";") + " LIMIT 200"

    cursor.execute(sql)
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    return [dict(zip(columns, row)) for row in rows]
