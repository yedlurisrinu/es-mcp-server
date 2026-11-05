"""Elasticsearch client factory — the only place es-mcp-server connects to Elasticsearch.

The read-only API key comes from Vault (loaded into the environment at startup); the URL
and client tuning come from resources/application-config.yaml.
"""

from __future__ import annotations

import os
from functools import lru_cache
from elasticsearch import Elasticsearch
from config.application_config import get_config
# ---------------------------------------------------------------------------
# Elasticsearch client
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_es_client() -> Elasticsearch:
    """
    Build and return a cached Elasticsearch client.
    Expects ``ELASTIC_READ_API_KEY`` in the environment (from Vault, secret/CREDENTIALS)
    and ``ELASTIC_URL``, ``request_timeout``, ``retry_on_timeout``, ``max_retries``,
    ``http_compress``, ``connections_per_node`` in application-config.yaml.
    Fails fast: a missing ``ELASTIC_URL`` key raises ``KeyError`` (from ``get_config``), an
    empty URL or a missing/empty API key raises ``RuntimeError``, and so does a failed ping.
    """

    elastic_url = get_config("ELASTIC_URL")
    api_key = os.getenv("ELASTIC_READ_API_KEY")
    if not elastic_url or not api_key:
        raise RuntimeError(
            "ELASTIC_URL and ELASTIC_READ_API_KEY must be set. "
            "Check that Vault secrets loaded correctly."
        )
    es = Elasticsearch(
        elastic_url,
        api_key=api_key,
        request_timeout=int(get_config("request_timeout")),
        retry_on_timeout=bool(get_config("retry_on_timeout")),
        max_retries=int(get_config("max_retries")),
        http_compress=bool(get_config("http_compress")),
        # Connection pooling for cloud,
        connections_per_node=int(get_config("connections_per_node")),
    )
    if not es.ping():
        raise RuntimeError("ping returned False")
    return es
