"""
Semantic search API routes.
"""

from fastapi import APIRouter, Query

from search import search as run_search

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
async def search_entities(
    q: str = Query(..., description="Natural language search query"),
    limit: int = Query(10, ge=1, le=50, description="Maximum results to return"),
):
    """
    Search graph entities by natural language query.
    Returns top matching nodes sorted by relevance score.
    """
    if not q.strip():
        return {"results": [], "query": q}

    results = run_search(q.strip(), limit=limit)
    return {"results": results, "query": q, "count": len(results)}
