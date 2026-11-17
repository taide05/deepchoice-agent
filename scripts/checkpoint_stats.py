"""Read-only inventory of the LangGraph checkpoint database.

`outputs/checkpoints.db` grows with every research run (2.45 GB at the time the
resume design was written) and has no retention policy. This script answers the
questions a retention decision needs: how big is the file, how many threads does
it hold, and which threads own the most checkpoints.

It is deliberately read-only. Deleting LangGraph rows means deleting the
thread's rows from the version-specific tables (`checkpoints` and `writes` for
langgraph-checkpoint-sqlite 3.x) and must be an explicit, backed-up admin
action; no destructive mode is offered here.

Design record: internal_docs/fix_plans/CHECKPOINT_RESUME_DESIGN_2026-11-17.md
(decision D3 and milestone M0). Recommended retention: keep the most recent 30
days or the most recent 200 tasks, whichever is larger; archive the rest.

Observed on 2026-11-17: 2,342.5 MB, 1,541 threads, 16,904 checkpoint rows and
90,627 write rows. The on-disk schema matches langgraph-checkpoint-sqlite 3.x
(`checkpoints` + `writes`); resume compatibility is gated by the per-task
`run_state.json` `graph_schema_version`, not by the database tables.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# Retention defaults from the resume design record (D3 / M0). Reported by the
# script so an operator sees the policy the numbers are meant to be read against.
RETENTION_DAYS = 30
RETENTION_TASKS = 200

# On-disk tables used by langgraph-checkpoint-sqlite 3.x (verified by opening the
# installed saver and reading sqlite_master). A database without them is not the
# checkpoint store this tool inventories.
EXPECTED_TABLES = ("checkpoints", "writes")


def open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the checkpoint database without write capability.

    SQLite URI paths must use forward slashes on Windows, and `mode=ro` keeps the
    open from creating journal/WAL files beside the production database.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"checkpoint database not found: {db_path}")
    uri = "file:" + db_path.resolve().as_posix() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=10)


def _table_rows(conn: sqlite3.Connection, table: str) -> int | None:
    try:
        row = conn.execute(f'select count(*) from "{table}"').fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row else None


def collect_stats(conn: sqlite3.Connection, top: int = 20) -> dict:
    """Summarize one checkpoint database. Pure read; never mutates."""
    tables = [row[0] for row in conn.execute(
        "select name from sqlite_master where type='table' order by name")]
    table_counts = {table: _table_rows(conn, table) for table in tables}
    missing = [table for table in EXPECTED_TABLES if table not in tables]
    unexpected = [table for table in tables if table not in EXPECTED_TABLES]

    thread_count = 0
    top_threads: list[dict] = []
    if "checkpoints" in tables:
        row = conn.execute(
            "select count(distinct thread_id) from checkpoints").fetchone()
        thread_count = int(row[0]) if row else 0
        rows = conn.execute(
            "select thread_id, count(*) as checkpoint_count "
            "from checkpoints group by thread_id "
            "order by checkpoint_count desc, thread_id limit ?",
            (max(1, int(top)),),
        ).fetchall()
        top_threads = [
            {"thread_id": row[0], "checkpoints": int(row[1])} for row in rows
        ]

    return {
        "tables": table_counts,
        "missing_expected_tables": missing,
        "unexpected_tables": unexpected,
        "thread_count": thread_count,
        "top_threads": top_threads,
        "retention_policy": {
            "keep_days": RETENTION_DAYS,
            "keep_tasks": RETENTION_TASKS,
            "note": "recommended policy; pruning is an explicit backed-up admin action",
        },
    }


def build_report(db_path: Path, stats: dict) -> dict:
    return {
        "db": str(db_path),
        "db_bytes": db_path.stat().st_size,
        "db_megabytes": round(db_path.stat().st_size / (1024 * 1024), 1),
        **stats,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only LangGraph checkpoint database inventory")
    parser.add_argument("--db", type=Path, default=Path("outputs/checkpoints.db"),
                        help="path to checkpoints.db (default: outputs/checkpoints.db)")
    parser.add_argument("--top", type=int, default=20,
                        help="how many largest threads to list (default: 20)")
    args = parser.parse_args(argv)

    try:
        conn = open_readonly(args.db)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        stats = collect_stats(conn, top=args.top)
    finally:
        conn.close()

    print(json.dumps(build_report(args.db, stats), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
