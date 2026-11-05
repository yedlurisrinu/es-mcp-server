from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from mcp.server import MCPServer

from adapters.elasticsearch import get_es_client
from data.app_resource import AppResources


@asynccontextmanager
async def lifespan(
    server: MCPServer[AppResources],
) -> AsyncGenerator[AppResources, None]:
    """
    Server lifespan: open the Elasticsearch client once, expose it to the tools as
    ``AppResources`` (``ctx.request_context.lifespan_context``), close it on shutdown.
    """
    with get_es_client() as es:
        yield AppResources(es=es)
