"""
PharmaWatch — EU Pharmaceutical Brand Intelligence Engine
Entry point for local development.

Usage:
    uvicorn main:app --reload --port 8000

For production use the Dockerfile + docker-compose.yml.
"""

from api.main import app  # noqa: F401 — re-exported for uvicorn

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
