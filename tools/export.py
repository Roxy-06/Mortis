from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
from pathlib import Path


def _database_path() -> Path:
    return Path(
        os.getenv(
            "MORTIS_DATA_DIR",
            str(Path(__file__).resolve().parents[1] / "data"),
        )
    ) / "mortis.db"


def export_table(table: str, output_format: str, output_path: Path) -> int:
    database = _database_path()
    if not database.is_file():
        raise FileNotFoundError(f"Paper-trading database does not exist: {database}")
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if table not in tables:
            raise ValueError(f"Unknown database table: {table}")
        cursor = conn.execute(f'SELECT * FROM "{table}"')
        columns = [column[0] for column in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "json":
        output_path.write_text(
            json.dumps(rows, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    else:
        with output_path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a Mortis SQLite table.")
    parser.add_argument("--table", required=True)
    parser.add_argument("--format", choices=("csv", "json"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        count = export_table(args.table, args.format, args.out)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.error(str(error))
    print(f"Exported {count} rows from {args.table} to {args.out}")


if __name__ == "__main__":
    main()
