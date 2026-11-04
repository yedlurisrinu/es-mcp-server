from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
from data.app_resource import AppResources
from adapters.elasticsearch import get_es_client
from mcp.server import MCPServer

@asynccontextmanager
async def lifespan(server: MCPServer[AppResources]) -> AsyncGenerator[AppResources, None]:
    """
    A context manager to maintain postgres saver connection , model connection, elasticsearch connection
    and inject into graph.
    """
    with get_es_client() as es:
       yield AppResources(es=es)