
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar, Mapping

@dataclass(frozen=True, slots=True)
class SeedData:
    PROTOCOL = "2026-07-28"

    META : ClassVar[Mapping[str, Any]] = MappingProxyType({
        "io.modelcontextprotocol/protocolVersion": PROTOCOL,
        "io.modelcontextprotocol/clientCapabilities": {"elicitation": {}},
        "io.modelcontextprotocol/clientInfo": {"name": "c1-raw", "version": "1.0"},
    })

    TOOL_DESCRIPTIONS : ClassVar[Mapping[str, Any]] = MappingProxyType({
        "search" : "Search Elasticsearch news index with the provided query and send the results"
    })