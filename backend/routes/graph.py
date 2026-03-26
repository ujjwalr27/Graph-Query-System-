"""
Graph API routes.
"""

from fastapi import APIRouter, Query

from graph_builder import (
    get_graph_json,
    get_node_with_neighbors,
    get_entity_types,
    get_clusters as _get_clusters,
)

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get("")
async def get_graph(
    entity_type: str | None = Query(None, description="Filter nodes by entity type"),
    max_nodes: int = Query(200, description="Maximum number of nodes to return"),
    max_edges: int = Query(2000, description="Maximum number of edges to return"),
):
    """Return the full graph (or a filtered subgraph) with entity type counts."""
    graph_data = get_graph_json(max_nodes=max_nodes, max_edges=max_edges)

    if entity_type:
        # Filter nodes by type and keep only relevant edges
        filtered_nodes = [n for n in graph_data["nodes"] if n["type"] == entity_type]
        node_ids = {n["id"] for n in filtered_nodes}
        filtered_links = [
            l
            for l in graph_data["links"]
            if l["source"] in node_ids or l["target"] in node_ids
        ]
        connected_ids = set()
        for l in filtered_links:
            connected_ids.add(l["source"])
            connected_ids.add(l["target"])
        all_nodes = [n for n in graph_data["nodes"] if n["id"] in connected_ids]
        graph_data = {"nodes": all_nodes, "links": filtered_links}

    # Include entity type counts to avoid a separate /types API call
    graph_data["entity_types"] = get_entity_types()

    return graph_data


@router.get("/types")
async def get_types():
    """Return all entity types and their counts."""
    return get_entity_types()


@router.get("/node/{node_id:path}")
async def get_node(
    node_id: str,
    depth: int = Query(1, description="How many hops from the node to include"),
):
    """Return a node and its neighbors."""
    return get_node_with_neighbors(node_id, depth=depth)


@router.get("/clusters")
async def get_clusters_endpoint():
    """Return community cluster assignments for all nodes."""
    return {"clusters": _get_clusters()}
