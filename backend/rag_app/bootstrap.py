from dataclasses import dataclass

from rag_app.config import Settings
from rag_app.graph.nodes import RAGNodes
from rag_app.graph.workflow import RAGWorkflow
from rag_app.services.agicto import AGICTOClient
from rag_app.services.elasticsearch import ElasticsearchStore
from rag_app.services.ingestion import IngestionService
from rag_app.services.memory import ConversationMemory
from rag_app.services.mineru import MinerUAdapter


@dataclass
class ApplicationServices:
    settings: Settings
    store: ElasticsearchStore
    agicto: AGICTOClient
    mineru: MinerUAdapter
    ingestion: IngestionService
    memory: ConversationMemory
    workflow: RAGWorkflow

    @classmethod
    def create(cls, settings: Settings) -> "ApplicationServices":
        store = ElasticsearchStore(settings)
        agicto = AGICTOClient(settings)
        mineru = MinerUAdapter(settings)
        ingestion = IngestionService(settings, store, mineru, agicto)
        memory = ConversationMemory(settings=settings, store=store, agicto=agicto)
        nodes = RAGNodes(
            settings=settings,
            store=store,
            agicto=agicto,
            memory=memory,
        )
        return cls(
            settings=settings,
            store=store,
            agicto=agicto,
            mineru=mineru,
            ingestion=ingestion,
            memory=memory,
            workflow=RAGWorkflow(nodes),
        )

    async def close(self) -> None:
        await self.agicto.close()
        await self.store.close()
