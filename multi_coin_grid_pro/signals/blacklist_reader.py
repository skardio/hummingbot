# blacklist_reader.py — read blacklisted trading pairs from a config YAML file.
# Uses yaml.safe_load only. Missing file → empty set, no exception.
from pathlib import Path
from typing import Set

import yaml


class BlacklistReader:
    """Return the set of blacklisted trading pairs from a grid-bot config YAML.

    The YAML must have a top-level ``blacklist`` key containing a list of
    trading pair strings (e.g. ``- BTC-USD``).  If the file does not exist
    or the key is absent, an empty set is returned.
    """

    def __init__(self, yaml_path: str) -> None:
        self._yaml_path = yaml_path

    def get_blacklisted_pairs(self) -> Set[str]:
        """Load and return blacklisted pairs. Never raises."""
        path = Path(self._yaml_path)
        if not path.exists():
            return set()
        try:
            with open(path) as fh:
                data = yaml.safe_load(fh)
            if not isinstance(data, dict):
                return set()
            pairs = data.get("blacklist", [])
            if not isinstance(pairs, list):
                return set()
            return {str(p) for p in pairs if p}
        except Exception:
            return set()
