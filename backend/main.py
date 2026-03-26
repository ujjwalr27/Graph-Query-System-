"""
Dodgeai Backend – FastAPI application entry point.
Production-ready with logging, CORS configuration, and health checks.
"""

import os
import sys
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dodgeai")

from db import load_data_into_db, get_schema
from graph_builder import build_graph
from llm import build_system_prompt
from search import build_search_index


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: load data, build graph, cache LLM prompt."""
    logger.info("Loading dataset into SQLite...")
    tables = load_data_into_db()
    if tables:
        logger.info("Loaded %d tables: %s", len(tables), ", ".join(tables))
        schema = get_schema()
        for table, cols in schema.items():
            col_names = [c["name"] for c in cols]
            logger.info("  %s: %s", table, ", ".join(col_names))
    else:
        logger.warning("No data loaded! Place CSV files in backend/data/")

    logger.info("Building graph...")
    try:
        graph = build_graph()
        logger.info(
            "Graph ready: %d nodes, %d edges",
            graph.number_of_nodes(),
            graph.number_of_edges(),
        )
    except Exception as e:
        logger.error("Failed to build graph: %s", e)

    # Pre-build and cache the LLM system prompt (avoids per-request rebuilds)
    logger.info("Caching LLM system prompt...")
    try:
        build_system_prompt()
        logger.info("System prompt cached.")
    except Exception as e:
        logger.warning("Could not cache system prompt: %s", e)

    # Build semantic search index
    logger.info("Building semantic search index...")
    try:
        build_search_index()
        logger.info("Search index ready.")
    except Exception as e:
        logger.warning("Could not build search index: %s", e)

    logger.info("Ready!")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Dodgeai - Graph-Based Data Query System",
    description="LLM-powered natural language query interface over a business dataset graph",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS – configurable via environment
ALLOWED_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000,http://localhost:80",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS + ["*"],  # Add wildcard for demo convenience
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from routes.graph import router as graph_router
from routes.chat import router as chat_router
from routes.search import router as search_router

app.include_router(graph_router)
app.include_router(chat_router)
app.include_router(search_router)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "message": "Dodgeai backend is running"}


@app.get("/api/schema")
async def get_db_schema():
    """Return database schema for debugging."""
    return get_schema()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
