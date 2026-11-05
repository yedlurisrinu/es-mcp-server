from contextlib import asynccontextmanager
from typing import AsyncGenerator
from data.app_resource import AppResources
from adapters.elasticsearch import get_es_client
from mcp.server import MCPServer

@asynccontextmanager
async def lifespan(server: MCPServer[AppResources]) -> AsyncGenerator[AppResources, None]:
    """
    Server lifespan: open the Elasticsearch client once, expose it to the tools as
    ``AppResources`` (``ctx.request_context.lifespan_context``), close it on shutdown.
    """
    with get_es_client() as es:
       yield AppResources(es=es)