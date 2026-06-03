from functools import lru_cache
from typing import List, Optional
from uuid import uuid4

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(settings.EMBEDDING_MODEL, device="cpu")


def _connect_qdrant():
    """Connect to the Qdrant server at QDRANT_URL, falling back to an on-disk
    embedded store at QDRANT_PATH when the server is unreachable.

    Embedded mode is single-process (file-locked): only one process — the API
    *or* a backfill script — may hold it at a time. It exists so vectors are
    still persisted in Qdrant format when the Docker server isn't running.
    """
    from qdrant_client import QdrantClient
    try:
        client = QdrantClient(url=settings.QDRANT_URL, timeout=3.0)
        client.get_collections()  # cheap reachability probe
        return client, "server"
    except Exception as exc:
        logger.warning("qdrant_server_unreachable_fallback_embedded",
                       url=settings.QDRANT_URL, path=settings.QDRANT_PATH, error=str(exc))
        import os
        os.makedirs(settings.QDRANT_PATH, exist_ok=True)
        return QdrantClient(path=settings.QDRANT_PATH), "embedded"


@lru_cache(maxsize=1)
def _get_qdrant():
    from qdrant_client.models import Distance, VectorParams
    client, _mode = _connect_qdrant()
    try:
        client.get_collection(settings.QDRANT_COLLECTION)
    except Exception:
        client.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )
    return client


def embed_text(text: str) -> Optional[List[float]]:
    """Generate embedding using paraphrase-multilingual-mpnet-base-v2 (768 dims)."""
    if not text or len(text.strip()) < 5:
        return None
    try:
        model = _get_model()
        vector = model.encode(text[:512], normalize_embeddings=True).tolist()
        return vector
    except Exception as exc:
        logger.warning("embedding_failed", error=str(exc))
        return None


def upsert_mention_embedding(mention_id: str, text: str, metadata: dict) -> Optional[str]:
    """
    Embed text and upsert to Qdrant. Returns Qdrant point_id (UUID str).
    """
    vector = embed_text(text)
    if vector is None:
        return None
    try:
        client = _get_qdrant()
        from qdrant_client.models import PointStruct
        point_id = str(uuid4())
        client.upsert(
            collection_name=settings.QDRANT_COLLECTION,
            points=[PointStruct(id=point_id, vector=vector, payload={"mention_id": mention_id, **metadata})],
        )
        return point_id
    except Exception as exc:
        logger.warning("qdrant_upsert_failed", mention_id=mention_id, error=str(exc))
        return None


def semantic_search(query: str, top_k: int = 20) -> List[dict]:
    """Semantic search over mentions using Qdrant cosine similarity."""
    vector = embed_text(query)
    if vector is None:
        return []
    try:
        client = _get_qdrant()
        results = client.search(
            collection_name=settings.QDRANT_COLLECTION,
            query_vector=vector,
            limit=top_k,
        )
        return [{"mention_id": r.payload.get("mention_id"), "score": r.score} for r in results]
    except Exception as exc:
        logger.warning("qdrant_search_failed", error=str(exc))
        return []
