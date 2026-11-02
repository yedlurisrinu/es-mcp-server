from dataclasses import dataclass

from elasticsearch import Elasticsearch

from adapters.search import Search

@dataclass(frozen=True)
class AppResources:
    es: Elasticsearch
    search : Search
    