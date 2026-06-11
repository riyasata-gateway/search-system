"""Embed brand-linked mentions into the OpenAI insight collection (Qdrant) for
the semantic-insight lenses. Pass source types as args, else defaults to the
consumer-voice review set.

  .venv/bin/python scripts/index_insight_corpus.py farmaline medimarket trustpilot
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from core.config import settings
import intelligence.evidence_rag as rag

args = sys.argv[1:]
fresh = "--fresh" in args
srcs = [a for a in args if not a.startswith("--")] or list(rag.VOICE_SOURCES)
with Session(create_engine(settings.DATABASE_SYNC_URL)) as db:
    if fresh:
        rag.reset_collection()
        print("reset insight collection (fresh re-embed)")
    n = rag.index_corpus(db, srcs)
    print(f"indexed {n} points from {srcs}")
