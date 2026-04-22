from __future__ import annotations

import os
import ssl
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

from .exceptions import ConfigError


@dataclass
class Config:
    base_url: str
    api_token: str
    verify_ssl: bool = False
    ca_cert: Optional[str] = None
    ws_max_retries: int = 3

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if not self.base_url:
            raise ConfigError("PENTAGI_BASE_URL must not be empty")
        if not self.base_url.startswith(("http://", "https://")):
            raise ConfigError("PENTAGI_BASE_URL must start with http:// or https://")
        if not self.api_token:
            raise ConfigError("PENTAGI_API_TOKEN must not be empty")
        if self.ca_cert and not os.path.isfile(self.ca_cert):
            raise ConfigError(f"PENTAGI_CA_CERT file not found: {self.ca_cert}")
        if self.ws_max_retries < 0:
            raise ConfigError("PENTAGI_WS_MAX_RETRIES must be >= 0")

    @classmethod
    def from_env(cls, dotenv_path: str = ".env") -> "Config":
        load_dotenv(dotenv_path, override=False)

        base_url = os.environ.get("PENTAGI_BASE_URL", "")
        api_token = os.environ.get("PENTAGI_API_TOKEN", "")

        if not base_url:
            raise ConfigError("PENTAGI_BASE_URL is required (set in .env or environment)")
        if not api_token:
            raise ConfigError("PENTAGI_API_TOKEN is required (set in .env or environment)")

        verify_ssl_raw = os.environ.get("PENTAGI_VERIFY_SSL", "false").lower()
        verify_ssl = verify_ssl_raw in ("1", "true", "yes")

        ca_cert = os.environ.get("PENTAGI_CA_CERT") or None

        try:
            ws_max_retries = int(os.environ.get("PENTAGI_WS_MAX_RETRIES", "3"))
        except ValueError:
            raise ConfigError("PENTAGI_WS_MAX_RETRIES must be an integer")

        return cls(
            base_url=base_url,
            api_token=api_token,
            verify_ssl=verify_ssl,
            ca_cert=ca_cert,
            ws_max_retries=ws_max_retries,
        )

    @property
    def rest_base(self) -> str:
        return f"{self.base_url}/api/v1"

    @property
    def ws_url(self) -> str:
        url = self.base_url
        if url.startswith("https://"):
            url = "wss://" + url[len("https://"):]
        elif url.startswith("http://"):
            url = "ws://" + url[len("http://"):]
        return url + "/api/v1/graphql"

    @property
    def requests_verify(self):
        if not self.verify_ssl:
            return False
        if self.ca_cert:
            return self.ca_cert
        return True

    @property
    def ws_sslopt(self) -> dict:
        if not self.verify_ssl:
            return {"cert_reqs": ssl.CERT_NONE}
        if self.ca_cert:
            return {"ca_certs": self.ca_cert}
        return {}
