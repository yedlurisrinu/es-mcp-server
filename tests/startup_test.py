"""
tests/startup_test.py

Start-up code without live services:
  - load_secrets: required env vars, Vault auth failure, secrets injected into os.environ
  - load_config / get_config; a missing config file is logged, not raised
  - setup_logging: replica id appended to the log file name; fallback on a bad file
  - get_es_client: fails fast on missing settings or a failed ping
  - lifespan: yields AppResources and closes the ES client
  - main.create_app: the streamable-HTTP app with DNS-rebinding protection
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.anyio


class TestLoadSecrets:
    def test_missing_addr_or_token_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config.vault_secrets import load_secrets

        monkeypatch.delenv("VAULT_ADDR", raising=False)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)
        with pytest.raises(ValueError, match="VAULT_ADDR and VAULT_TOKEN"):
            load_secrets()

    def test_missing_secret_path_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from config.vault_secrets import load_secrets

        monkeypatch.setenv("VAULT_ADDR", "http://vault-server:8200")
        monkeypatch.setenv("VAULT_TOKEN", "tok")
        monkeypatch.delenv("VAULT_SECRET_PATH", raising=False)
        with pytest.raises(ValueError, match="VAULT_SECRET_PATH"):
            load_secrets()

    def test_auth_failure_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from config.vault_secrets import load_secrets

        for k, v in {
            "VAULT_ADDR": "http://vault-server:8200",
            "VAULT_TOKEN": "tok",
            "VAULT_SECRET_PATH": "secret/CREDENTIALS",
        }.items():
            monkeypatch.setenv(k, v)
        client = MagicMock()
        client.is_authenticated.return_value = False
        with (
            patch("config.vault_secrets.Client", return_value=client),
            pytest.raises(ValueError, match="authentication failed"),
        ):
            load_secrets()

    def test_success_injects_env_for_each_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from config.vault_secrets import load_secrets

        for k, v in {
            "VAULT_ADDR": "http://vault-server:8200",
            "VAULT_TOKEN": "tok",
            "VAULT_SECRET_PATH": "secret/CREDENTIALS",
        }.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("INJECTED_KEY", raising=False)
        client = MagicMock()
        client.is_authenticated.return_value = True
        client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"INJECTED_KEY": "value"}}
        }
        with patch("config.vault_secrets.Client", return_value=client):
            load_secrets()
        assert os.environ["INJECTED_KEY"] == "value"
        assert client.secrets.kv.v2.read_secret_version.call_args.kwargs == {
            "path": "CREDENTIALS",
            "mount_point": "secret",
        }


class TestApplicationConfig:
    def test_get_config_reads_loaded_yaml(self) -> None:
        from config.application_config import get_config

        assert (
            get_config("ES_INDEX") == "news_articles"
            and get_config("ARTICLE_CONTENT_MAX_CHARS") == 1000
        )

    def test_missing_file_is_logged_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import config.application_config as app_config

        monkeypatch.setattr(app_config, "BASE_PATH", "/nonexistent")
        with patch.object(app_config, "logger") as logger:
            app_config.load_config()
        logger.exception.assert_called_once()


class TestSetupLogging:
    def test_replica_id_in_log_file_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from config.logging_setup import setup_logging

        monkeypatch.setenv("REPLICA_ID", "r9")
        with patch("config.logging_setup.logging.config.dictConfig") as dict_config:
            setup_logging()
        (config,), _ = dict_config.call_args
        assert (
            config["handlers"]["file"]["filename"] == "/app/logs/es-mcp-server-r9.log"
        )

    def test_bad_file_falls_back_to_basic_config(self) -> None:
        from config.logging_setup import setup_logging

        with patch("config.logging_setup.logging.basicConfig") as basic:
            setup_logging("does-not-exist.json")
        basic.assert_called_once()


class TestElasticsearchClient:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from adapters.elasticsearch import get_es_client

        get_es_client.cache_clear()
        yield
        get_es_client.cache_clear()

    def test_missing_api_key_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from adapters.elasticsearch import get_es_client

        monkeypatch.delenv("ELASTIC_READ_API_KEY", raising=False)
        with (
            patch("adapters.elasticsearch.Elasticsearch") as es_cls,
            pytest.raises(RuntimeError, match="ELASTIC_READ_API_KEY"),
        ):
            get_es_client()
        es_cls.assert_not_called()

    def test_failed_ping_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from adapters.elasticsearch import get_es_client

        monkeypatch.setenv("ELASTIC_READ_API_KEY", "read-key")
        with patch("adapters.elasticsearch.Elasticsearch") as es_cls:
            es_cls.return_value.ping.return_value = False
            with pytest.raises(RuntimeError, match="ping"):
                get_es_client()

    def test_builds_client_from_config_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from adapters.elasticsearch import get_es_client

        monkeypatch.setenv("ELASTIC_READ_API_KEY", "read-key")
        with patch("adapters.elasticsearch.Elasticsearch") as es_cls:
            es_cls.return_value.ping.return_value = True
            assert get_es_client() is get_es_client() is es_cls.return_value
        es_cls.assert_called_once()
        args, kwargs = es_cls.call_args
        assert (
            args == ("http://elasticsearch:9200",) and kwargs["api_key"] == "read-key"
        )
        assert kwargs["request_timeout"] == 60 and kwargs["connections_per_node"] == 10


class TestLifespan:
    async def test_yields_resources_and_closes_client(self) -> None:
        import adapters.lifespan as lifespan_mod

        es = MagicMock()
        es.__enter__.return_value = es
        with patch.object(lifespan_mod, "get_es_client", return_value=es):
            async with lifespan_mod.lifespan(MagicMock()) as resources:
                assert resources.es is es
                es.__exit__.assert_not_called()
        es.__exit__.assert_called_once()

    async def test_server_lifespan_closes_token_verifier(self) -> None:
        from contextlib import asynccontextmanager

        from server.mcp_server import ESMCPServer
        from server.token_verifier import RateLimitTokenVerifier

        @asynccontextmanager
        async def inner(server):  # type: ignore[no-untyped-def]
            yield MagicMock()

        with patch.object(RateLimitTokenVerifier, "aclose") as aclose:
            server = ESMCPServer(inner).create_mcp_server("r1")
            async with server.settings.lifespan(server):
                aclose.assert_not_called()
        aclose.assert_awaited_once()


class TestMain:
    def test_create_app_with_dns_rebinding_protection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MCP_ALLOWED_HOSTS", "es-mcp-lb:9599, localhost:9551")
        monkeypatch.setenv("REPLICA_ID", "r1")
        sys.modules.pop("main", None)
        with (
            patch("config.vault_secrets.load_secrets"),
            patch("config.logging_setup.setup_logging"),
        ):
            import main
        try:
            assert main.ALLOWED_HOSTS == ["es-mcp-lb:9599", "localhost:9551"]
            from starlette.testclient import TestClient

            app = main.create_app()
            resp = TestClient(app, base_url="http://es-mcp-lb:9599").get("/healthz")
            assert resp.status_code == 200 and resp.headers["x-replica-id"] == "r1"
        finally:
            sys.modules.pop("main", None)
