from dataclasses import dataclass

from elasticsearch import Elasticsearch


@dataclass(frozen=True)
class AppResources:
    es: Elasticsearch
