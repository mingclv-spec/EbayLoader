"""Configuration management for EbayLoader."""

import os
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_CONFIG_PATHS = [
    "./ebay_config.yaml",
    "~/.ebayloader/config.yaml",
]

REQUIRED_CONFIG_KEYS = [
    "ebay.api.app_id",
    "ebay.api.cert_id",
    "ebay.api.dev_id",
    "ebay.seller.merchant_location_key",
]

ENV_MAP = {
    "EBAY_APP_ID": "ebay.api.app_id",
    "EBAY_CERT_ID": "ebay.api.cert_id",
    "EBAY_DEV_ID": "ebay.api.dev_id",
    "EBAY_REDIRECT_URI": "ebay.api.redirect_uri",
    "EBAY_MERCHANT_LOCATION_KEY": "ebay.seller.merchant_location_key",
}


class Config:
    """Loads and validates EbayLoader configuration."""

    def __init__(self, config_path: Optional[str] = None):
        self.raw: dict = {}
        if config_path:
            self._load_file(config_path)
        else:
            for p in DEFAULT_CONFIG_PATHS:
                resolved = Path(p).expanduser()
                if resolved.exists():
                    self._load_file(str(resolved))
                    break
        self._apply_env_overrides()
        self.validate()

    def _load_file(self, path: str):
        with open(path) as f:
            self.raw = yaml.safe_load(f) or {}

    def _resolve(self, dot_key: str, default=None):
        parts = dot_key.split(".")
        obj = self.raw
        for p in parts:
            if isinstance(obj, dict):
                obj = obj.get(p)
            else:
                return default
        return obj if obj is not None else default

    def _apply_env_overrides(self):
        for env_key, dot_key in ENV_MAP.items():
            val = os.environ.get(env_key)
            if val:
                parts = dot_key.split(".")
                cursor = self.raw
                for p in parts[:-1]:
                    cursor = cursor.setdefault(p, {})
                cursor[parts[-1]] = val

    def validate(self):
        missing = []
        for key in REQUIRED_CONFIG_KEYS:
            if self._resolve(key) is None:
                missing.append(key)
        if missing:
            print(f"⚠️  Missing required config: {', '.join(missing)}")
            print("   Set via config file or env vars (EBAY_APP_ID, etc.)")
            return False
        return True

    @property
    def app_id(self) -> str:
        return self._resolve("ebay.api.app_id") or ""

    @property
    def cert_id(self) -> str:
        return self._resolve("ebay.api.cert_id") or ""

    @property
    def dev_id(self) -> str:
        return self._resolve("ebay.api.dev_id") or ""

    @property
    def redirect_uri(self) -> str:
        return self._resolve("ebay.api.redirect_uri", "https://localhost/signin")

    @property
    def merchant_location_key(self) -> str:
        return self._resolve("ebay.seller.merchant_location_key", "")

    @property
    def environment(self) -> str:
        return self._resolve("ebay.api.environment", "production")  # sandbox | production

    @property
    def default_currency(self) -> str:
        return self._resolve("ebay.seller.currency", "AUD")

    @property
    def default_country(self) -> str:
        return self._resolve("ebay.seller.country", "AU")

    @property
    def default_condition(self) -> str:
        return self._resolve("ebay.seller.default_condition", "New")

    @property
    def default_listing_duration(self) -> str:
        return self._resolve("ebay.seller.listing_duration", "GTC")

    @property
    def token_path(self) -> Path:
        return Path(self._resolve("ebay.api.token_path", "~/.ebayloader/token.json")).expanduser()

    @property
    def sandbox(self) -> bool:
        return self.environment == "sandbox"

    def api_base(self) -> str:
        if self.sandbox:
            return "https://api.sandbox.ebay.com"
        return "https://api.ebay.com"
