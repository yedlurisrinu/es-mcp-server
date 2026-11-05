from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Callable

from mcp.server.mcpserver import MCPServer, RequestStateSecurity
from mcp.server.auth.settings import AuthSettings
from mcp.types import ToolAnnotations
import os
from starlette.requests import Request
from starlette.responses import JSONResponse
from data.app_resource import AppResources
from server.token_verifier import RateLimitTokenVerifier
from tools.search_tools import NewsSearchTools
from config.application_config import get_config

# All three tools only read the news index: safe to call repeatedly, no side effects.
READ_ONLY_TOOL = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

class ESMCPServer:
    def __init__(self, lifespan : Callable[[MCPServer[AppResources]], AbstractAsyncContextManager[AppResources]]):
        self.lifespan = lifespan

    def make_health_check(self, replica_id: str) -> Callable[[Request], JSONResponse]:
        def health_check(request: Request) -> JSONResponse:
               return JSONResponse({"status": "ok", "replica": replica_id}, headers={"X-Replica-Id": replica_id}) 
        return health_check

    def create_mcp_server(self, replica_id : str) ->  MCPServer:
        security = RequestStateSecurity(keys=[os.environ['ES_MCP_SERVER_SHARED_SYMMETRIC_KEY'].encode()])
        verifier = RateLimitTokenVerifier(issuer=get_config("issuer_realm"),audience=get_config("audience"))

        @asynccontextmanager
        async def lifespan(server: MCPServer[AppResources]) -> AsyncIterator[AppResources]:
            # the verifier's HTTP client lives as long as the server
            try:
                async with self.lifespan(server) as resources:
                    yield resources
            finally:
                await verifier.aclose()

        es_mcp_server = MCPServer(name="es-mcp-server", version="1.0", request_state_security=security,
                                   lifespan=lifespan,
                                   token_verifier=verifier,
                                   auth=AuthSettings(issuer_url=get_config("issuer_realm"), resource_server_url=get_config("audience"), validate_token_resource=True)
                                   )
        es_mcp_server.add_tool(NewsSearchTools.article_search, description='tool to search for relevant news articles based on user query', annotations=READ_ONLY_TOOL)
        es_mcp_server.add_tool(NewsSearchTools.category_search, description='tool to count news articles that match the given categories', annotations=READ_ONLY_TOOL)
        es_mcp_server.add_tool(NewsSearchTools.mget, description='tool to get multiple articles based on article ids', annotations=READ_ONLY_TOOL)
        es_mcp_server.custom_route("/healthz", methods=['GET'], name='Health Check')(self.make_health_check(replica_id))
        return es_mcp_server
