from pathlib import Path

from multi_coin_grid_pro.observability.event_logger import EventLogger
from multi_coin_grid_pro.persistence.entry_price_store import EntryPriceStore


def test_production_default_artifacts_are_redirected_to_pytest_tmp_path():
    repository_root = Path(__file__).resolve().parents[3]
    production_data = (repository_root / "data").resolve()
    production_logs = (repository_root / "logs").resolve()

    store = EntryPriceStore("data/entry_prices.db")
    event_logger = EventLogger(enabled=True, output_dir="logs/events")
    try:
        assert not Path(store.db_path).resolve().is_relative_to(production_data)
        assert not event_logger.output_dir.resolve().is_relative_to(production_logs)
        assert Path(store.db_path).name == "entry_prices.db"
        assert event_logger.output_dir.name == "events"
    finally:
        store.close()
        event_logger.close()
