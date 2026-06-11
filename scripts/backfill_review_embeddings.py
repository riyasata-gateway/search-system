#!/usr/bin/env python
"""Embed review mentions into Qdrant — vector + full payload (incl. text).

Writes to the Qdrant server at QDRANT_URL when reachable, else falls back to an
on-disk **embedded** Qdrant store at QDRANT_PATH (see processing/embeddings.py
_connect_qdrant). The payload stores the review text and key facets so Qdrant
points are self-describing for semantic search and inspection:

    {mention_id, text, rating, brand_name, source_type, country, language}

Batched encoding (paraphrase-multilingual-mpnet-base-v2, 768-dim, CPU) keeps
throughput up. Resumable: only embeds mentions whose qdrant_point_id is NULL.

Usage:
    python scripts/backfill_review_embeddings.py                 # all review mentions
    python scripts/backfill_review_embeddings.py --batch 256
    python scripts/backfill_review_embeddings.py --limit 100000  # cap (e.g. demo subset)
"""
from __future__ import annotations

import argparse
import os
import sys
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from core.config import settings
from models.mention import Mention

REVIEW_SOURCES = ("farmaline", "medimarket")


def _qdrant():
    from processing.embeddings import _connect_qdrant
    from qdrant_client.models import Distance, VectorParams
    client, mode = _connect_qdrant()
    try:
        client.get_collection(settings.QDRANT_COLLECTION)
    except Exception:
        client.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )
    print(f"[qdrant] connected in {mode} mode "
          f"({settings.QDRANT_URL if mode == 'server' else settings.QDRANT_PATH})", flush=True)
    return client


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--limit", type=int, default=0, help="max mentions to embed (0 = all)")
    args = ap.parse_args()

    from sentence_transformers import SentenceTransformer
    from qdrant_client.models import PointStruct

    model = SentenceTransformer(settings.EMBEDDING_MODEL, device="cpu")
    client = _qdrant()
    engine = create_engine(settings.DATABASE_SYNC_URL)

    done = 0
    while True:
        with Session(engine) as db:
            rows = db.execute(
                select(
                    Mention.id, Mention.clean_text, Mention.rating,
                    Mention.brand_name, Mention.source_type,
                    Mention.country, Mention.language,
                )
                .where(
                    Mention.source_type.in_(REVIEW_SOURCES),
                    Mention.qdrant_point_id.is_(None),
                    Mention.is_deleted.is_(False),
                )
                .limit(args.batch)
            ).all()

        if not rows:
            break

        texts = [(r.clean_text or "")[:512] for r in rows]
        vectors = model.encode(texts, normalize_embeddings=True, batch_size=64).tolist()

        points, id_map = [], []
        for r, vec in zip(rows, vectors):
            if not r.clean_text or len(r.clean_text.strip()) < 1:
                continue
            pid = str(uuid4())
            points.append(PointStruct(id=pid, vector=vec, payload={
                "mention_id": r.id,
                "text": (r.clean_text or "")[:1000],
                "rating": r.rating,
                "brand_name": r.brand_name,
                "source_type": r.source_type,
                "country": r.country,
                "language": r.language,
            }))
            id_map.append((r.id, pid))

        if points:
            client.upsert(collection_name=settings.QDRANT_COLLECTION, points=points)
            with Session(engine) as db:
                for mid, pid in id_map:
                    db.execute(update(Mention).where(Mention.id == mid).values(qdrant_point_id=pid))
                db.commit()

        done += len(id_map)
        print(f"[embed] {done:,} embedded", flush=True)
        if args.limit and done >= args.limit:
            break

    print(f"[embed] DONE — {done:,} review mentions embedded into Qdrant", flush=True)


if __name__ == "__main__":
    main()
