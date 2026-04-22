import os
import ssl
import tempfile

import pytest

from pentagi_client.config import Config
from pentagi_client.exceptions import ConfigError


def test_from_env_valid(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PENTAGI_BASE_URL=https://localhost:8443\n"
        "PENTAGI_API_TOKEN=tok123\n"
    )
    monkeypatch.delenv("PENTAGI_BASE_URL", raising=False)
    monkeypatch.delenv("PENTAGI_API_TOKEN", raising=False)
    monkeypatch.delenv("PENTAGI_VERIFY_SSL", raising=False)
    monkeypatch.delenv("PENTAGI_CA_CERT", raising=False)
    monkeypatch.delenv("PENTAGI_WS_MAX_RETRIES", raising=False)

    cfg = Config.from_env(str(env_file))
    assert cfg.base_url == "https://localhost:8443"
    assert cfg.api_token == "tok123"
    assert cfg.verify_ssl is False
    assert cfg.ca_cert is None
    assert cfg.ws_max_retries == 3


def test_from_env_missing_base_url(monkeypatch):
    monkeypatch.delenv("PENTAGI_BASE_URL", raising=False)
    monkeypatch.setenv("PENTAGI_API_TOKEN", "tok")
    with pytest.raises(ConfigError, match="PENTAGI_BASE_URL"):
        Config.from_env("/nonexistent/.env")


def test_from_env_missing_api_token(monkeypatch):
    monkeypatch.setenv("PENTAGI_BASE_URL", "https://localhost:8443")
    monkeypatch.delenv("PENTAGI_API_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="PENTAGI_API_TOKEN"):
        Config.from_env("/nonexistent/.env")


def test_ws_url_https():
    cfg = Config(base_url="https://localhost:8443", api_token="t")
    assert cfg.ws_url == "wss://localhost:8443/api/v1/graphql"


def test_ws_url_http():
    cfg = Config(base_url="http://localhost:8080", api_token="t")
    assert cfg.ws_url == "ws://localhost:8080/api/v1/graphql"


def test_requests_verify_false():
    cfg = Config(base_url="https://localhost:8443", api_token="t", verify_ssl=False)
    assert cfg.requests_verify is False


def test_requests_verify_true_no_ca():
    cfg = Config(base_url="https://localhost:8443", api_token="t", verify_ssl=True)
    assert cfg.requests_verify is True


def test_requests_verify_true_with_ca(tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_text("fake")
    cfg = Config(base_url="https://localhost:8443", api_token="t", verify_ssl=True, ca_cert=str(ca))
    assert cfg.requests_verify == str(ca)


def test_ws_sslopt_no_verify():
    cfg = Config(base_url="https://localhost:8443", api_token="t", verify_ssl=False)
    sslopt = cfg.ws_sslopt
    assert sslopt.get("cert_reqs") == ssl.CERT_NONE


def test_ws_sslopt_verify_system_ca():
    cfg = Config(base_url="https://localhost:8443", api_token="t", verify_ssl=True)
    assert cfg.ws_sslopt == {}


def test_trailing_slash_stripped():
    cfg = Config(base_url="https://localhost:8443/", api_token="t")
    assert cfg.base_url == "https://localhost:8443"
    assert cfg.rest_base == "https://localhost:8443/api/v1"


def test_invalid_base_url_scheme():
    with pytest.raises(ConfigError, match="http"):
        Config(base_url="ftp://localhost", api_token="t")


def test_ca_cert_missing_file():
    with pytest.raises(ConfigError, match="not found"):
        Config(base_url="https://localhost:8443", api_token="t",
               verify_ssl=True, ca_cert="/nonexistent/ca.pem")
