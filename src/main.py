
import os
import socket

import uvicorn

from adapters.lifespan import lifespan
from config.logging_setup import setup_logging
from config.vault_secrets import load_secrets
from server.mcp_server import ESMCPServer
from config.application_config import load_config
from mcp.server.transport_security import TransportSecuritySettings
setup_logging()
load_secrets()
load_config()
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "es-mcp-lb:9599").split(",") if h.strip()]
def create_app():
   replica_id = os.environ.get("REPLICA_ID") or socket.gethostname()
   return ESMCPServer(lifespan).create_mcp_server(replica_id=replica_id).streamable_http_app(
stateless_http=True, transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
        allowed_hosts=ALLOWED_HOSTS, allowed_origins=[],), host="0.0.0.0")

if __name__ == '__main__':
   uvicorn.run(create_app())