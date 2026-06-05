"""Backfill Qdrant embeddings for mentions that were ingested before the vector
store existed (or after it was cleared).

Why this exists
---------------
Embeddings are normally written *inline* during NLP processing
(`workers/processing_worker.py` → `upsert_mention_embedding`). If the Qdrant
collection is empty while `mentions` is full — e.g. Qdrant was wiped, the
collection was recreated, or mentions were imported without the worker running —
then `/api/v1/search/semantic` returns 0 results for everything because there are
no vectors to search. This script regenerates the missing vectors.

It mirrors the production write path exactly:
  - same embedder (`embed_text`, paraphrase-multilingual-mpnet-base-v2, 768-dim)
  - same payload shape ({mention_id, source_type, country, language})
  - writes the resulting Qdrant point id back to `mentions.qdrant_point_id`

Idempotent: by default only processes mentions with no `qdrant_point_id`. Pass
`--all` to re-embed everything (e.g. after changing the embedding model).

Usage:
  python scripts/backfill_embeddings.py            # only missing
  python scripts/backfill_embeddings.py --all      # re-embed all live mentions
  python scripts/backfill_embeddings.py --batch 128
"""
import argparse
import os
import sys
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from core.config import settings
from models.mention import Mention


def _qdrant():
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams
    client = QdrantClient(url=settings.QDRANT_URL)
    try:
        client.get_collection(settings.QDRANT_COLLECTION)
    except Exception:
        client.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )
    return client


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="re-embed every live mention, not just those missing a vector")
    ap.add_argument("--batch", type=int, default=64, help="encode/upsert batch size")
    args = ap.parse_args()

    from sentence_transformers import SentenceTransformer
    from qdrant_client.models import PointStruct

    print(f"Loading embedder {settings.EMBEDDING_MODEL} (CPU)…")
    model = SentenceTransformer(settings.EMBEDDING_MODEL, device="cpu")
    client = _qdrant()

    engine = create_engine(settings.DATABASE_SYNC_URL)
    with Session(engine) as db:
        # Live mentions with usable text. clean_text preferred, raw_text fallback.
        q = select(
            Mention.id, Mention.clean_text, Mention.raw_text,
            Mention.source_type, Mention.country, Mention.language,
        ).where(Mention.is_deleted == False)  # noqa: E712
        if not args.all:
            q = q.where(Mention.qdrant_point_id.is_(None))

        rows = db.execute(q).all()
        # Keep only rows with text long enough to embed (matches embed_text's >=5 guard).
        work = [
            (mid, (clean or raw or "").strip(), stype, country, lang)
            for (mid, clean, raw, stype, country, lang) in rows
            if len((clean or raw or "").strip()) >= 5
        ]
        skipped_empty = len(rows) - len(work)
        total = len(work)
        print(f"Mentions to embed: {total}  (skipped {skipped_empty} with no/short text)")
        if total == 0:
            print("Nothing to do. Semantic store already populated for these mentions.")
            return

        done = 0
        for i in range(0, total, args.batch):
            chunk = work[i:i + args.batch]
            texts = [t[1][:512] for t in chunk]
            vectors = model.encode(texts, normalize_embeddings=True, batch_size=args.batch)

            points = []
            id_map = {}  # mention_id -> point_id
            for (mid, _text, stype, country, lang), vec in zip(chunk, vectors):
                pid = str(uuid4())
                id_map[mid] = pid
                points.append(PointStruct(
                    id=pid,
                    vector=vec.tolist(),
                    payload={"mention_id": mid, "source_type": stype,
                             "country": country, "language": lang},
                ))
            client.upsert(collection_name=settings.QDRANT_COLLECTION, points=points)

            # Record the point ids back on the mentions (so re-runs are idempotent).
            for mid, pid in id_map.items():
                db.execute(update(Mention).where(Mention.id == mid).values(qdrant_point_id=pid))
            db.commit()

            done += len(chunk)
            print(f"  …{done}/{total}")

        count = client.count(collection_name=settings.QDRANT_COLLECTION).count
        print(f"Done. Qdrant '{settings.QDRANT_COLLECTION}' now holds {count} points.")


if __name__ == "__main__":
    main()
