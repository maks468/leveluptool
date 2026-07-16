from functools import lru_cache

import yaml

from levelup.core.config import CONFIG_DIR

SCORING_DIR = CONFIG_DIR / "scoring"


@lru_cache
def load_rubric(rubric_type: str) -> dict:
    """rubric_type: 'primary' | 'secondary'. Cached per process -- restart
    the process (or clear the cache) after editing a rubric YAML."""
    path = SCORING_DIR / f"{rubric_type}_rubric.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def load_city_tiers() -> dict:
    with open(SCORING_DIR / "city_tiers.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def clear_rubric_cache() -> None:
    load_rubric.cache_clear()
    load_city_tiers.cache_clear()
