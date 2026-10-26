import csv
import json

from engine.paper_trader import PaperTrader
from tools.export import export_table
from tools.gen_data_dictionary import generate_schema
from tools.rebuild_memory import rebuild_memory


def test_table_export_writes_valid_csv_and_json(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    trader = PaperTrader(str(data_dir))
    trader.open_position(None, "long", 100, 1, 95, 110, 5)
    monkeypatch.setenv("MORTIS_DATA_DIR", str(data_dir))

    json_path = tmp_path / "trades.json"
    csv_path = tmp_path / "trades.csv"
    assert export_table("trades", "json", json_path) == 1
    assert export_table("trades", "csv", csv_path) == 1

    assert json.loads(json_path.read_text(encoding="utf-8"))[0]["stop_loss"] == 95
    with csv_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["take_profit"] == "110.0"


def test_dictionary_generator_reads_the_live_schema_and_memory_rebuild_is_safe(
    tmp_path, monkeypatch
):
    data_dir = tmp_path / "data"
    PaperTrader(str(data_dir))
    monkeypatch.setenv("MORTIS_DATA_DIR", str(data_dir))

    schema = generate_schema()
    rebuilt = rebuild_memory(data_dir / "mortis.db")

    assert "### `trades`" in schema
    assert "`stop_loss`" in schema
    assert rebuilt["episodes_seen"] == 0
    assert rebuilt["features_standardized"] == 0
