"""CLI for paired DeepChoice runtime database maintenance."""

from __future__ import annotations

import argparse
from pathlib import Path

from deepchoice.operations.runtime_databases import (
    RuntimeDatabaseOperationError,
    create_paired_backup,
    exercise_restore,
    restore_paired_backup,
    verify_paired_backup,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup")
    backup.add_argument("--product-db", required=True, type=Path)
    backup.add_argument("--checkpoint-db", required=True, type=Path)
    backup.add_argument("--destination", required=True, type=Path)
    backup.add_argument("--maintenance-confirmed", action="store_true")

    verify = commands.add_parser("verify")
    verify.add_argument("--backup-dir", required=True, type=Path)

    restore = commands.add_parser("restore")
    restore.add_argument("--backup-dir", required=True, type=Path)
    restore.add_argument("--product-db", required=True, type=Path)
    restore.add_argument("--checkpoint-db", required=True, type=Path)
    restore.add_argument("--maintenance-confirmed", action="store_true")
    restore.add_argument("--replace", action="store_true")
    restore.add_argument("--apply", action="store_true")

    drill = commands.add_parser("exercise")
    drill.add_argument("--backup-dir", required=True, type=Path)
    drill.add_argument("--drill-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "backup":
            result = create_paired_backup(
                args.product_db,
                args.checkpoint_db,
                args.destination,
                maintenance_confirmed=args.maintenance_confirmed,
            )
            print(f"backup created: {result}")
        elif args.command == "verify":
            verify_paired_backup(args.backup_dir)
            print("backup verified")
        elif args.command == "exercise":
            result = exercise_restore(args.backup_dir, args.drill_dir)
            print(f"restore drill passed: {result.product.parent}")
        elif not args.apply:
            verify_paired_backup(args.backup_dir)
            print("dry run passed; add --apply to restore")
        else:
            result = restore_paired_backup(
                args.backup_dir,
                args.product_db,
                args.checkpoint_db,
                maintenance_confirmed=args.maintenance_confirmed,
                replace=args.replace,
            )
            print(f"restore completed: {result.product.parent}")
        return 0
    except RuntimeDatabaseOperationError as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
