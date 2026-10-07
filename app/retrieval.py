from uuid import UUID

from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models

from app.config import settings

VECTOR_SIZE = 384
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class KnowledgeIndex:
    def __init__(self) -> None:
        self.client = QdrantClient(url=settings.qdrant_url, timeout=10)
        self._embedder: TextEmbedding | None = None

    @property
    def embedder(self) -> TextEmbedding:
        if self._embedder is None:
            self._embedder = TextEmbedding(model_name=EMBEDDING_MODEL)
        return self._embedder

    def ensure_collection(self) -> None:
        if not self.client.collection_exists(settings.qdrant_collection):
            self.client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
            )

    def upsert(self, document_id: str, title: str, content: str, source: str) -> None:
        self.ensure_collection()
        vector = list(self.embedder.embed([f"{title}\n{content}"]))[0].tolist()
        self.client.upsert(
            collection_name=settings.qdrant_collection,
            points=[
                models.PointStruct(
                    id=str(UUID(document_id)),
                    vector=vector,
                    payload={"document_id": document_id, "title": title, "content": content, "source": source},
                )
            ],
            wait=True,
        )

    def delete(self, document_id: str) -> None:
        self.ensure_collection()
        self.client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=models.PointIdsList(points=[str(UUID(document_id))]),
            wait=True,
        )

    def search(self, query: str, limit: int = 5) -> list[dict]:
        self.ensure_collection()
        vector = list(self.embedder.query_embed(query))[0].tolist()
        hits = self.client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            limit=limit,
            with_payload=True,
        ).points
        return [
            {
                "id": hit.payload["document_id"],
                "title": hit.payload["title"],
                "source": hit.payload["source"],
                "content": hit.payload["content"][:12_000],
                "truncated": len(hit.payload["content"]) > 12_000,
                "score": hit.score,
            }
            for hit in hits
            if hit.payload
        ]


knowledge_index = KnowledgeIndex()
