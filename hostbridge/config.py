import configparser
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURRENCIES = {"EUR": 2, "USD": 2, "GBP": 2, "JPY": 0, "KWD": 3}
MAX_MINOR = 999_999_999_999
MAX_ENTRIES = 128


def runtime_dir():
    return Path(os.environ.get("HOST_DATA_DIR", os.environ.get("DATA_DIR", str(ROOT / ".runtime"))))


def load_products():
    config = configparser.ConfigParser()
    config.read(ROOT / "config" / "products.ini")
    return {name: dict(config[name]) for name in config.sections()}


def region_options():
    config = configparser.ConfigParser()
    config.read(ROOT / "config" / "region.ini")
    return config
