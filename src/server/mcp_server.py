from typing import Awaitable, Callable

from httpx2 import Request, Response
from mcp.server.mcpserver import MCPServer, RequestStateSecurity
from mcp.server.auth.settings import AuthSettings
import os
from adapters.lifespan import lifespan
from starlette.responses import JSONResponse
from server.token_verifier import RateLimitTokenVerifier
from tools.tool import search
from config.application_config import get_config

class ESMCPServer:
    def __init__(self,lifespan : lifespan):
        self.lifespan = lifespan

    def make_health_check(self, replica_id: str) -> Callable[[Request], Awaitable[Response]]:
        def health_check(request: Request) -> Response:
               return JSONResponse({"status": "ok", "replica": replica_id}, headers={"X-Replica-Id": replica_id}) 
        return health_check

    def create_mcp_server(self, replica_id : str) -> MCPServer:
        security = RequestStateSecurity(keys=[os.getenv('ES_MCP_SERVER_SHARED_SYMMETRIC_KEY')]) 
        es_mcp_server = MCPServer(name="es-mcp-server", version="1.0", request_state_security=security,
                                   lifespan=self.lifespan, 
                                   token_verifier=RateLimitTokenVerifier(issuer=get_config("issuer_realm"),audience=get_config("audience")),
                                   auth=AuthSettings(issuer_url=get_config("issuer_realm"), resource_server_url=get_config("audience"), validate_token_resource=True)
                                   )
        es_mcp_server.add_tool(search, description='tool to search Ealsticsearch for relevant news articles based on user query')
        es_mcp_server.custom_route("/healthz", methods=['GET'], name='Health Check')(self.make_health_check(replica_id))
        return es_mcp_server
