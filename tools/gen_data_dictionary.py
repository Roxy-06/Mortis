from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "DATA_DICTIONARY.md"
START = "<!-- BEGIN GENERATED SCHEMA -->"
END = "<!-- END GENERATED SCHEMA -->"
WRITERS = {
    "account": "engine.paper_trader",
    "daily_pnl": "engine.paper_trader",
    "trades": "engine.paper_trader",
    "ledger": "engine.paper_trader",
    "trading_controls": "engine.paper_trader",
    "training_samples": "engine.paper_trader / research pipeline",
    "schema_migrations": "engine.paper_trader",
    "decisions": "engine.paper_trader",
    "trade_events": "engine.paper_trader",
    "memory_episodes": "engine.paper_trader",
    "memory_feature_stats": "engine.paper_trader",
    "system_state": "engine.paper_trader",
}
EXPECTED_SCHEMA_VERSION = 2


def _db_path() -> Path:
    return Path(
        os.getenv("MORTIS_DATA_DIR", str(ROOT / "data"))
    ) / "mortis.db"


def _meaning(column: str) -> str:
    name = column.replace("_", " ")
    if column.endswith("_ms") or column.endswith("_at"):
        return f"{name} (UTC Unix timestamp in milliseconds where applicable)"
    if column.endswith("_usd"):
        return f"{name} (US dollars)"
    if column.endswith("_pct"):
        return f"{name} (percentage)"
    if column.endswith("_bps"):
        return f"{name} (basis points)"
    if column.endswith("_r"):
        return f"{name} (R multiple)"
    if column.endswith("_json"):
        return f"{name} (serialized JSON)"
    return name


def _example(conn: sqlite3.Connection, table: str, column: str) -> str:
    value = conn.execute(
        f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL LIMIT 1'
    ).fetchone()
    if value is None:
        return "—"
    text = str(value[0]).replace("|", "\\|").replace("\n", " ")
    return text[:64] + ("…" if len(text) > 64 else "")


def generate_schema() -> str:
    database = _db_path()
    if not database.is_file():
        raise FileNotFoundError(f"Mortis database not found: {database}")
    lines = []
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as conn:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version < EXPECTED_SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema v{version} is older than supported v{EXPECTED_SCHEMA_VERSION}; "
                "start the upgraded backend before regenerating the dictionary."
            )
        tables = [
            row[0]
            for row in conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
        ]
        for table in tables:
            lines.extend([f"### `{table}`", "", "| Column | SQLite type | Nullable | Meaning / units | Example | Writer |", "|---|---|---|---|---|---|"])
            for column in conn.execute(f'PRAGMA table_info("{table}")'):
                name, data_type, not_null, default, primary_key = (
                    column[1], column[2] or "ANY", column[3], column[4], column[5]
                )
                nullable = "no" if not_null or primary_key else "yes"
                meaning = _meaning(str(name))
                writer = WRITERS.get(table, "module using this table")
                lines.append(
                    f"| `{name}` | `{data_type}` | {nullable} | {meaning} | "
                    f"`{_example(conn, table, str(name))}` | `{writer}` |"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    schema = generate_schema()
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DOC_PATH.exists():
        document = DOC_PATH.read_text(encoding="utf-8")
    else:
        document = (
            "# Mortis data dictionary\n\n"
            "Schema details are generated from the configured live SQLite database. "
            "Meaning and units are inferred from names; see module documentation for "
            "domain semantics.\n\n"
            f"{START}\n{END}\n"
        )
    if START not in document or END not in document:
        raise ValueError(
            f"{DOC_PATH} must contain {START} and {END} markers."
        )
    before, rest = document.split(START, 1)
    _, after = rest.split(END, 1)
    DOC_PATH.write_text(
        f"{before}{START}\n{schema}{END}{after}",
        encoding="utf-8",
    )
    print(f"Updated generated SQLite schema in {DOC_PATH}")


if __name__ == "__main__":
    main()
