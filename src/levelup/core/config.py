from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEVELUP_", env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{(DATA_DIR / 'levelup.db').as_posix()}"
    default_owner_id: int = 1


settings = Settings()
