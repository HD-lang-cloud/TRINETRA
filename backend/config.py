import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file at the project root
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    """Base configuration with shared defaults."""
    SECRET_KEY = os.getenv("SECRET_KEY", "trinetra-default-secret-key-change-in-production")
    DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "database" / "trinetra.db")))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")
    TESTING = False
    DEBUG = False


class DevelopmentConfig(Config):
    """Development configuration with debug mode enabled."""
    DEBUG = True


class TestingConfig(Config):
    """Testing configuration with in-memory or dedicated test database."""
    TESTING = True
    DEBUG = True
    DATABASE_PATH = BASE_DIR / "database" / "test_trinetra.db"


class ProductionConfig(Config):
    """Production configuration with hardened security settings."""
    DEBUG = False
    TESTING = False


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig
}


def get_config(config_name=None):
    """Retrieve configuration object by name or fallback to FLASK_ENV / default."""
    if not config_name:
        config_name = os.getenv("FLASK_ENV", "development").lower()
    return config_by_name.get(config_name, DevelopmentConfig)
