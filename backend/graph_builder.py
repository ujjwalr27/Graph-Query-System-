"""
Graph construction module – builds a NetworkX graph from the SQLite database.
Optimized: graph JSON, entity types, and cluster assignments are cached after build.
"""

import logging
from collections import Counter

import networkx as nx
from networkx.algorithms import community as nx_community

from db import get_connection, get_schema

logger = logging.getLogger(__name__)

_graph: nx.DiGraph | None = None

# ── Cached serialized outputs (rebuilt only when graph changes) ──
_graph_json_cache: dict | None = None
_entity_types_cache: dict[str, int] | None = None
_clusters_cache: list[dict] | None = None


def build_graph() -> nx.DiGraph:
    """
    Build a directed graph from the database tables.

    Strategy:
      1. Each table row becomes a node, keyed as "{table}:{row_index}"
      2. Columns with matching names across tables create edges.
    """
    global _graph, _graph_json_cache, _entity_types_cache
    conn = get_connection()
    schema = get_schema()

    G = nx.DiGraph()

    # ── Step 1: Load all table data and create nodes ──
    value_index: dict[str, dict] = {}

    for table in schema:
        cursor = conn.cursor()
        cursor.execute(f"SELECT rowid, * FROM '{table}'")
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

        value_index[table] = {}

        for row in rows:
            row_dict = dict(zip(columns, row))
            rowid = row_dict.pop("rowid", row[0])
            node_id = f"{table}:{rowid}"

            # Find a display label
            label = str(rowid)
            for col in columns[1:4]:
                val = row_dict.get(col)
                if val is not None and str(val).strip():
                    label = str(val)[:30]
                    break

            G.add_node(
                node_id,
                type=table,
                label=label,
                **{k: _safe_value(v) for k, v in row_dict.items()},
            )

            # Index values for relationship detection
            for col in columns[1:]:
                val = row_dict.get(col)
                if val is not None and str(val).strip():
                    idx = value_index[table].setdefault(col, {})
                    str_val = str(val).strip()
                    idx.setdefault(str_val, []).append(node_id)

    # ── Step 2: Detect and create relationships ──
    tables = list(schema.keys())
    columns_by_table = {t: [c["name"] for c in cols] for t, cols in schema.items()}

    # Only create edges on ID/key-like columns to avoid combinatorial explosion.
    # These suffixes/exact names indicate foreign-key-style references.
    FK_SUFFIXES = (
        "order", "document", "party", "partner", "id", "no", "key",
        "number", "item", "delivery", "invoice", "payment", "customer",
        "product", "material", "plant", "address", "company", "code",
        "account", "journal", "entry",
    )

    def _is_fk_column(col: str) -> bool:
        col_lower = col.lower()
        return any(col_lower.endswith(s) or col_lower == s for s in FK_SUFFIXES)

    # Track which (table_a, table_b, col) pairs we've already processed
    processed_pairs = set()

    for table_a in tables:
        for col_a in columns_by_table[table_a]:
            if not _is_fk_column(col_a):
                continue
            for table_b in tables:
                if table_a == table_b:
                    continue
                # Avoid duplicate: (A->B, col) and (B->A, col) process same values
                pair_key = (min(table_a, table_b), max(table_a, table_b), col_a)
                if pair_key in processed_pairs:
                    continue

                if col_a in columns_by_table[table_b]:
                    _create_edges_by_column(
                        G, value_index, table_a, table_b, col_a, col_a
                    )
                    processed_pairs.add(pair_key)

    _graph = G

    # ── Step 3: Community detection (cluster assignment) ──
    _run_community_detection(G)

    # Pre-cache serialized outputs (after cluster_id is assigned)
    _graph_json_cache = _serialize_graph(G)
    _entity_types_cache = _compute_entity_types(G)

    logger.info(
        "Built graph: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges()
    )
    return G


def _run_community_detection(G: nx.DiGraph) -> None:
    """
    Detect communities using greedy modularity maximization on the undirected
    projection of the graph. Assigns 'cluster_id' and 'cluster_label' to every node.
    Results are cached in _clusters_cache.
    """
    global _clusters_cache

    if G.number_of_nodes() == 0:
        _clusters_cache = []
        return

    # Work on undirected version (community detection needs undirected graph)
    U = G.to_undirected()

    try:
        # Greedy modularity is fast and works well for medium-sized graphs
        communities = list(nx_community.greedy_modularity_communities(U))
    except Exception as e:
        logger.warning("Community detection failed: %s — falling back to entity types", e)
        # Fallback: each entity type is its own cluster
        types = set(nx.get_node_attributes(G, "type").values())
        type_list = sorted(types)
        communities = [
            frozenset(n for n, d in G.nodes(data=True) if d.get("type") == t)
            for t in type_list
        ]

    # Sort clusters by size descending
    communities = sorted(communities, key=len, reverse=True)

    cluster_summary = []
    for cluster_id, members in enumerate(communities):
        # Assign cluster_id to each node in the graph
        for node_id in members:
            if node_id in G.nodes:
                G.nodes[node_id]["cluster_id"] = cluster_id

        # Compute dominant entity type for the cluster
        type_counts = Counter(
            G.nodes[n].get("type", "unknown")
            for n in members
            if n in G.nodes
        )
        dominant_type = type_counts.most_common(1)[0][0] if type_counts else "unknown"
        cluster_summary.append({
            "id": cluster_id,
            "size": len(members),
            "dominant_type": dominant_type,
            "type_breakdown": dict(type_counts),
            "label": f"Cluster {cluster_id} ({dominant_type})",
        })

    _clusters_cache = cluster_summary
    logger.info("Community detection: %d clusters found", len(communities))


def _safe_value(v):
    """Convert value to a JSON-safe type."""
    if v is None:
        return None
    if isinstance(v, (int, float, bool)):
        return v
    return str(v)


def _create_edges_by_column(
    G: nx.DiGraph,
    value_index: dict,
    table_a: str,
    table_b: str,
    col_a: str,
    col_b: str,
):
    """Create edges between nodes in table_a and table_b based on matching column values."""
    idx_a = value_index.get(table_a, {}).get(col_a)
    idx_b = value_index.get(table_b, {}).get(col_b)
    if not idx_a or not idx_b:
        return

    edges_added = 0
    MAX_EDGES_PER_PAIR = 500  # Cap per relationship to prevent combinatorial explosion
    for val, nodes_a in idx_a.items():
        if val in idx_b:
            nodes_b = idx_b[val]
            for na in nodes_a:
                for nb in nodes_b:
                    if edges_added >= MAX_EDGES_PER_PAIR:
                        break
                    if not G.has_edge(na, nb):
                        G.add_edge(na, nb, relation=col_a, label=col_a)
                        edges_added += 1
                if edges_added >= MAX_EDGES_PER_PAIR:
                    break
        if edges_added >= MAX_EDGES_PER_PAIR:
            break

    if edges_added > 0:
        logger.info("  %s.%s -> %s.%s: %d edges", table_a, col_a, table_b, col_b, edges_added)


def _serialize_node(node_id: str, data: dict) -> dict:
    """Shared serialization for a single graph node. DRY helper."""
    return {
        "id": node_id,
        "type": data.get("type", "unknown"),
        "label": data.get("label", node_id),
        **{k: v for k, v in data.items() if k not in ("type", "label")},
    }


def _serialize_edge(source: str, target: str, data: dict) -> dict:
    """Shared serialization for a single graph edge. DRY helper."""
    return {
        "source": source,
        "target": target,
        "relation": data.get("relation", "related"),
        "label": data.get("label", ""),
    }


def _serialize_graph(G: nx.DiGraph, max_nodes: int | None = None, max_edges: int = 3000) -> dict:
    """Serialize a graph (or subgraph) to JSON-safe dict with node/edge caps."""
    if max_nodes and G.number_of_nodes() > max_nodes:
        subset = list(G.nodes())[:max_nodes]
        G = G.subgraph(subset)

    nodes = [_serialize_node(nid, data) for nid, data in G.nodes(data=True)]
    all_edges = list(G.edges(data=True))
    if len(all_edges) > max_edges:
        all_edges = all_edges[:max_edges]
    links = [_serialize_edge(s, t, d) for s, t, d in all_edges]
    return {"nodes": nodes, "links": links}


def _compute_entity_types(G: nx.DiGraph) -> dict[str, int]:
    """Compute entity type counts from graph."""
    counts = {}
    for _, data in G.nodes(data=True):
        t = data.get("type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    return counts


# ── Public API ──

def get_graph() -> nx.DiGraph:
    """Return the cached graph (must call build_graph first)."""
    if _graph is None:
        raise RuntimeError("Graph not built yet. Call build_graph() first.")
    return _graph


def get_graph_json(max_nodes: int = 300, max_edges: int = 3000) -> dict:
    """
    Return the graph as JSON dict for the frontend.
    Uses cache when possible, otherwise serializes with caps.
    """
    G = get_graph()
    # Return full cache only when it fits within both caps
    if (
        _graph_json_cache
        and G.number_of_nodes() <= max_nodes
        and len(_graph_json_cache.get("links", [])) <= max_edges
    ):
        return _graph_json_cache
    return _serialize_graph(G, max_nodes=max_nodes, max_edges=max_edges)


def get_node_with_neighbors(node_id: str, depth: int = 1) -> dict:
    """Return a node and its neighbors up to a given depth."""
    G = get_graph()

    if node_id not in G:
        return {"nodes": [], "links": []}

    # BFS to collect neighbors
    visited = {node_id}
    frontier = {node_id}

    for _ in range(depth):
        next_frontier = set()
        for n in frontier:
            for neighbor in list(G.successors(n)) + list(G.predecessors(n)):
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.add(neighbor)
        frontier = next_frontier

    subgraph = G.subgraph(visited)
    return _serialize_graph(subgraph)


def get_entity_types() -> dict[str, int]:
    """Return cached entity type counts."""
    if _entity_types_cache is not None:
        return _entity_types_cache
    return _compute_entity_types(get_graph())


def get_clusters() -> list[dict]:
    """Return cached cluster summary from community detection."""
    if _clusters_cache is not None:
        return _clusters_cache
    # Trigger build if not yet run
    G = get_graph()
    _run_community_detection(G)
    return _clusters_cache or []
