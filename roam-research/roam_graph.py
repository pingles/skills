"""Local graph index and igraph operations for Roam Research.

This module keeps graph analysis separate from `roam.py`, which remains the
live Roam API/content client. The index stores only metadata and topology:
page titles, UIDs, timestamps, page/block hierarchy, and references.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any, Iterable, Optional, Sequence

import roam

PAGES_METADATA_QUERY = """
[:find ?uid ?title ?create ?edit
 :where
 [?p :node/title ?title]
 [?p :block/uid ?uid]
 [(get-else $ ?p :create/time 0) ?create]
 [(get-else $ ?p :edit/time 0) ?edit]]
"""

BLOCKS_METADATA_QUERY = """
[:find ?uid ?page-uid ?order ?create ?edit
 :where
 [?b :block/uid ?uid]
 [?b :block/page ?p]
 [?p :block/uid ?page-uid]
 [(get-else $ ?b :block/order 0) ?order]
 [(get-else $ ?b :create/time 0) ?create]
 [(get-else $ ?b :edit/time 0) ?edit]]
"""

CHILD_EDGES_QUERY = """
[:find ?parent-uid ?child-uid
 :where
 [?parent :block/children ?child]
 [?parent :block/uid ?parent-uid]
 [?child :block/uid ?child-uid]]
"""

REF_EDGES_QUERY = """
[:find ?from-uid ?to-uid
 :where
 [?from :block/refs ?to]
 [?from :block/uid ?from-uid]
 [?to :block/uid ?to-uid]]
"""


def _now_ms() -> int:
    return int(time.time() * 1000)


def default_index_path() -> Path:
    graph = os.environ.get("ROAMRESEARCH_GRAPH", "default")
    safe_graph = re.sub(r"[^A-Za-z0-9_.-]+", "_", graph).strip("_") or "default"
    return Path.home() / ".cache" / "roam-research" / f"{safe_graph}.sqlite3"


def connect_index(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    path = Path(db_path).expanduser() if db_path else default_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_index(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            graph TEXT NOT NULL,
            kind TEXT NOT NULL,
            started_at_ms INTEGER NOT NULL,
            completed_at_ms INTEGER,
            page_count INTEGER DEFAULT 0,
            block_count INTEGER DEFAULT 0,
            edge_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL CHECK (kind IN ('page', 'block', 'unknown')),
            title TEXT,
            page_uid TEXT,
            parent_uid TEXT,
            order_index INTEGER,
            create_time INTEGER,
            edit_time INTEGER,
            last_seen_sync INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            src_uid TEXT NOT NULL,
            dst_uid TEXT NOT NULL,
            kind TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            last_seen_sync INTEGER NOT NULL,
            UNIQUE (src_uid, dst_uid, kind)
        );

        CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
        CREATE INDEX IF NOT EXISTS idx_nodes_title ON nodes(title);
        CREATE INDEX IF NOT EXISTS idx_nodes_page_uid ON nodes(page_uid);
        CREATE INDEX IF NOT EXISTS idx_nodes_parent_uid ON nodes(parent_uid);
        CREATE INDEX IF NOT EXISTS idx_nodes_edit_time ON nodes(edit_time);
        CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_uid);
        CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_uid);
        CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
        """
    )
    conn.commit()


def _rows(result: Iterable[Any]) -> Iterable[tuple[Any, ...]]:
    for row in result:
        yield tuple(row) if isinstance(row, (list, tuple)) else (row,)


def _upsert_node(
    conn: sqlite3.Connection,
    *,
    uid: str,
    kind: str,
    sync_id: int,
    title: Optional[str] = None,
    page_uid: Optional[str] = None,
    parent_uid: Optional[str] = None,
    order_index: Optional[int] = None,
    create_time: Optional[int] = None,
    edit_time: Optional[int] = None,
) -> None:
    conn.execute(
        """
        INSERT INTO nodes (
            uid, kind, title, page_uid, parent_uid, order_index,
            create_time, edit_time, last_seen_sync
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(uid) DO UPDATE SET
            kind = CASE
                WHEN excluded.kind != 'unknown' THEN excluded.kind
                ELSE nodes.kind
            END,
            title = COALESCE(excluded.title, nodes.title),
            page_uid = COALESCE(excluded.page_uid, nodes.page_uid),
            parent_uid = COALESCE(excluded.parent_uid, nodes.parent_uid),
            order_index = COALESCE(excluded.order_index, nodes.order_index),
            create_time = COALESCE(NULLIF(excluded.create_time, 0), nodes.create_time),
            edit_time = COALESCE(NULLIF(excluded.edit_time, 0), nodes.edit_time),
            last_seen_sync = excluded.last_seen_sync
        """,
        (
            uid,
            kind,
            title,
            page_uid,
            parent_uid,
            order_index,
            create_time,
            edit_time,
            sync_id,
        ),
    )


def _upsert_edge(
    conn: sqlite3.Connection,
    *,
    src_uid: str,
    dst_uid: str,
    kind: str,
    sync_id: int,
    weight: float = 1.0,
) -> None:
    _upsert_node(conn, uid=src_uid, kind="unknown", sync_id=sync_id)
    _upsert_node(conn, uid=dst_uid, kind="unknown", sync_id=sync_id)
    conn.execute(
        """
        INSERT INTO edges (src_uid, dst_uid, kind, weight, last_seen_sync)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(src_uid, dst_uid, kind) DO UPDATE SET
            weight = excluded.weight,
            last_seen_sync = excluded.last_seen_sync
        """,
        (src_uid, dst_uid, kind, weight, sync_id),
    )


def build_index(db_path: Optional[str | Path] = None) -> dict[str, Any]:
    graph, _ = roam._env()
    conn = connect_index(db_path)
    init_index(conn)
    started_at = _now_ms()
    cur = conn.execute(
        "INSERT INTO sync_runs (graph, kind, started_at_ms) VALUES (?, 'full', ?)",
        (graph, started_at),
    )
    sync_id = int(cur.lastrowid)

    pages = list(_rows(roam.query(PAGES_METADATA_QUERY)))
    blocks = list(_rows(roam.query(BLOCKS_METADATA_QUERY)))
    child_edges = list(_rows(roam.query(CHILD_EDGES_QUERY)))
    ref_edges = list(_rows(roam.query(REF_EDGES_QUERY)))

    page_count = 0
    block_count = 0
    edge_count = 0

    with conn:
        for uid, title, create_time, edit_time in pages:
            _upsert_node(
                conn,
                uid=str(uid),
                kind="page",
                title=str(title),
                sync_id=sync_id,
                create_time=int(create_time or 0),
                edit_time=int(edit_time or 0),
            )
            page_count += 1

        for uid, page_uid, order_index, create_time, edit_time in blocks:
            _upsert_node(
                conn,
                uid=str(uid),
                kind="block",
                page_uid=str(page_uid),
                sync_id=sync_id,
                order_index=int(order_index or 0),
                create_time=int(create_time or 0),
                edit_time=int(edit_time or 0),
            )
            _upsert_edge(
                conn,
                src_uid=str(page_uid),
                dst_uid=str(uid),
                kind="page_contains",
                sync_id=sync_id,
                weight=0.25,
            )
            block_count += 1
            edge_count += 1

        for parent_uid, child_uid in child_edges:
            _upsert_edge(
                conn,
                src_uid=str(parent_uid),
                dst_uid=str(child_uid),
                kind="parent_child",
                sync_id=sync_id,
                weight=0.5,
            )
            conn.execute(
                "UPDATE nodes SET parent_uid = ? WHERE uid = ?",
                (str(parent_uid), str(child_uid)),
            )
            edge_count += 1

        for from_uid, to_uid in ref_edges:
            _upsert_edge(
                conn,
                src_uid=str(from_uid),
                dst_uid=str(to_uid),
                kind="reference",
                sync_id=sync_id,
                weight=1.0,
            )
            edge_count += 1

        conn.execute("DELETE FROM edges WHERE last_seen_sync != ?", (sync_id,))
        conn.execute("DELETE FROM nodes WHERE last_seen_sync != ?", (sync_id,))
        conn.execute(
            """
            UPDATE sync_runs
            SET completed_at_ms = ?, page_count = ?, block_count = ?, edge_count = ?
            WHERE id = ?
            """,
            (_now_ms(), page_count, block_count, edge_count, sync_id),
        )
        conn.execute(
            """
            INSERT INTO metadata (key, value) VALUES ('last_sync_id', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(sync_id),),
        )
        conn.execute(
            """
            INSERT INTO metadata (key, value) VALUES ('graph', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (graph,),
        )

    conn.close()
    return {
        "db_path": str(Path(db_path).expanduser() if db_path else default_index_path()),
        "graph": graph,
        "sync_id": sync_id,
        "pages": page_count,
        "blocks": block_count,
        "edges": edge_count,
    }


def stats(db_path: Optional[str | Path] = None) -> dict[str, Any]:
    conn = connect_index(db_path)
    init_index(conn)
    try:
        nodes = {
            row["kind"]: row["count"]
            for row in conn.execute("SELECT kind, COUNT(*) AS count FROM nodes GROUP BY kind")
        }
        edges = {
            row["kind"]: row["count"]
            for row in conn.execute("SELECT kind, COUNT(*) AS count FROM edges GROUP BY kind")
        }
        last_sync = conn.execute(
            """
            SELECT id, graph, kind, started_at_ms, completed_at_ms,
                   page_count, block_count, edge_count
            FROM sync_runs
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        return {
            "db_path": str(Path(db_path).expanduser() if db_path else default_index_path()),
            "nodes": nodes,
            "edges": edges,
            "last_sync": dict(last_sync) if last_sync else None,
        }
    finally:
        conn.close()


def _require_igraph():
    try:
        import igraph as ig
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "python-igraph is required. Install with: "
            "python3 -m pip install -r /Users/paul/.claude/skills/roam-research/requirements.txt"
        ) from exc
    return ig


def _node_summary(vertex: Any) -> dict[str, Any]:
    return {
        "uid": vertex["uid"],
        "kind": vertex["kind"],
        "title": vertex["title"],
        "page_uid": vertex["page_uid"],
        "parent_uid": vertex["parent_uid"],
        "order_index": vertex["order_index"],
        "create_time": vertex["create_time"],
        "edit_time": vertex["edit_time"],
    }


def _with_score(vertex: Any, score: float, key: str) -> dict[str, Any]:
    row = _node_summary(vertex)
    row[key] = float(score)
    return row


def load_graph(
    db_path: Optional[str | Path] = None,
    *,
    directed: bool = True,
    edge_kinds: Optional[Sequence[str]] = None,
) -> tuple[Any, dict[str, int]]:
    ig = _require_igraph()
    conn = connect_index(db_path)
    init_index(conn)
    try:
        node_rows = list(
            conn.execute(
                """
                SELECT uid, kind, title, page_uid, parent_uid, order_index,
                       create_time, edit_time
                FROM nodes
                ORDER BY id
                """
            )
        )
        uid_to_idx = {row["uid"]: idx for idx, row in enumerate(node_rows)}
        if edge_kinds:
            placeholders = ",".join("?" for _ in edge_kinds)
            edge_rows = list(
                conn.execute(
                    f"SELECT src_uid, dst_uid, kind, weight FROM edges WHERE kind IN ({placeholders})",
                    tuple(edge_kinds),
                )
            )
        else:
            edge_rows = list(conn.execute("SELECT src_uid, dst_uid, kind, weight FROM edges"))
    finally:
        conn.close()

    edges = []
    kinds = []
    weights = []
    for row in edge_rows:
        src = uid_to_idx.get(row["src_uid"])
        dst = uid_to_idx.get(row["dst_uid"])
        if src is None or dst is None:
            continue
        edges.append((src, dst))
        kinds.append(row["kind"])
        weights.append(float(row["weight"]))

    graph = ig.Graph(n=len(node_rows), edges=edges, directed=directed)
    for attr in ("uid", "kind", "title", "page_uid", "parent_uid", "order_index", "create_time", "edit_time"):
        graph.vs[attr] = [row[attr] for row in node_rows]
    graph.es["kind"] = kinds
    graph.es["weight"] = weights
    return graph, uid_to_idx


def load_relationship_graph(db_path: Optional[str | Path] = None) -> tuple[Any, dict[str, int]]:
    graph, uid_to_idx = load_graph(db_path, directed=False)
    if graph.ecount():
        graph = graph.simplify(combine_edges={"weight": "sum", "kind": "first"})
    return graph, uid_to_idx


def _resolve_vertex(graph: Any, identifier: str) -> int:
    matches = graph.vs.select(uid_eq=identifier)
    if matches:
        return int(matches[0].index)
    matches = graph.vs.select(title_eq=identifier)
    if matches:
        return int(matches[0].index)
    lowered = identifier.casefold()
    for vertex in graph.vs:
        title = vertex["title"]
        if title and str(title).casefold() == lowered:
            return int(vertex.index)
    raise ValueError(f"No indexed node found for {identifier!r}")


def _top_scored(
    graph: Any,
    scores: Sequence[float],
    *,
    limit: int,
    node_kind: Optional[str],
    key: str,
    exclude: Optional[set[int]] = None,
) -> list[dict[str, Any]]:
    exclude = exclude or set()
    ranked = sorted(
        range(graph.vcount()),
        key=lambda idx: (scores[idx], graph.vs[idx]["title"] or graph.vs[idx]["uid"]),
        reverse=True,
    )
    out = []
    for idx in ranked:
        if idx in exclude:
            continue
        vertex = graph.vs[idx]
        if node_kind and vertex["kind"] != node_kind:
            continue
        out.append(_with_score(vertex, scores[idx], key))
        if len(out) >= limit:
            break
    return out


def overview(db_path: Optional[str | Path] = None) -> dict[str, Any]:
    graph, _ = load_graph(db_path)
    weak = graph.connected_components(mode="weak") if graph.vcount() else []
    return {
        "vertices": graph.vcount(),
        "edges": graph.ecount(),
        "directed": graph.is_directed(),
        "weak_components": len(weak),
        "largest_weak_component": max(weak.sizes()) if weak else 0,
        "density": graph.density() if graph.vcount() > 1 else 0.0,
    }


def pagerank(
    db_path: Optional[str | Path] = None,
    *,
    limit: int = 25,
    node_kind: Optional[str] = "page",
) -> list[dict[str, Any]]:
    graph, _ = load_graph(db_path)
    scores = graph.pagerank(damping=0.85, weights="weight" if graph.ecount() else None)
    return _top_scored(graph, scores, limit=limit, node_kind=node_kind, key="pagerank")


def personalized_pagerank(
    seeds: Sequence[str],
    db_path: Optional[str | Path] = None,
    *,
    limit: int = 25,
    node_kind: Optional[str] = "page",
    include_seeds: bool = False,
) -> list[dict[str, Any]]:
    if not seeds:
        raise ValueError("At least one seed UID or page title is required")
    graph, _ = load_relationship_graph(db_path)
    seed_indexes = {_resolve_vertex(graph, seed) for seed in seeds}
    reset = [0.0] * graph.vcount()
    for idx in seed_indexes:
        reset[idx] = 1.0 / len(seed_indexes)
    scores = graph.personalized_pagerank(
        damping=0.85,
        reset=reset,
        weights="weight" if graph.ecount() else None,
    )
    exclude = set() if include_seeds else seed_indexes
    return _top_scored(
        graph,
        scores,
        limit=limit,
        node_kind=node_kind,
        key="personalized_pagerank",
        exclude=exclude,
    )


def shortest_path(source: str, target: str, db_path: Optional[str | Path] = None) -> dict[str, Any]:
    graph, _ = load_relationship_graph(db_path)
    src = _resolve_vertex(graph, source)
    dst = _resolve_vertex(graph, target)
    paths = graph.get_shortest_paths(src, to=dst, output="vpath")
    path = paths[0] if paths else []
    return {
        "source": _node_summary(graph.vs[src]),
        "target": _node_summary(graph.vs[dst]),
        "distance": len(path) - 1 if path else None,
        "path": [_node_summary(graph.vs[idx]) for idx in path],
    }


def centrality(
    db_path: Optional[str | Path] = None,
    *,
    metric: str = "betweenness",
    limit: int = 25,
    node_kind: Optional[str] = "page",
) -> list[dict[str, Any]]:
    graph, _ = load_graph(db_path)
    if metric == "degree":
        scores = graph.degree(mode="all")
    elif metric == "indegree":
        scores = graph.degree(mode="in")
    elif metric == "outdegree":
        scores = graph.degree(mode="out")
    elif metric == "betweenness":
        scores = graph.betweenness(directed=True, weights=None)
    elif metric == "closeness":
        scores = graph.closeness(mode="all")
    elif metric == "eigenvector":
        scores = graph.eigenvector_centrality(directed=True, weights="weight" if graph.ecount() else None)
    elif metric == "hub":
        scores = graph.hub_score(weights="weight" if graph.ecount() else None)
    elif metric == "authority":
        scores = graph.authority_score(weights="weight" if graph.ecount() else None)
    else:
        raise ValueError("unknown centrality metric")
    return _top_scored(graph, scores, limit=limit, node_kind=node_kind, key=metric)


def components(
    db_path: Optional[str | Path] = None,
    *,
    mode: str = "weak",
    limit: int = 10,
) -> list[dict[str, Any]]:
    graph, _ = load_graph(db_path)
    parts = graph.connected_components(mode=mode)
    ranked = sorted(enumerate(parts), key=lambda item: len(item[1]), reverse=True)
    out = []
    for component_id, vertices in ranked[:limit]:
        pages = [idx for idx in vertices if graph.vs[idx]["kind"] == "page"]
        top = sorted(
            (_node_summary(graph.vs[idx]) for idx in pages),
            key=lambda row: row["title"] or row["uid"],
        )[:10]
        out.append(
            {
                "component": component_id,
                "size": len(vertices),
                "page_count": len(pages),
                "sample_pages": top,
            }
        )
    return out


def communities(
    db_path: Optional[str | Path] = None,
    *,
    method: str = "leiden",
    limit: int = 20,
) -> list[dict[str, Any]]:
    graph, _ = load_relationship_graph(db_path)
    if method == "leiden":
        clusters = graph.community_leiden(
            objective_function="modularity",
            weights="weight" if graph.ecount() else None,
        )
    elif method in ("louvain", "multilevel"):
        clusters = graph.community_multilevel(weights="weight" if graph.ecount() else None)
    elif method == "label_propagation":
        clusters = graph.community_label_propagation(weights="weight" if graph.ecount() else None)
    elif method == "infomap":
        clusters = graph.community_infomap(edge_weights="weight" if graph.ecount() else None)
    else:
        raise ValueError("unknown community method")

    pr = graph.pagerank(weights="weight" if graph.ecount() else None)
    rows = []
    for community_id, vertices in enumerate(clusters):
        pages = [idx for idx in vertices if graph.vs[idx]["kind"] == "page"]
        top_pages = sorted(pages, key=lambda idx: pr[idx], reverse=True)[:10]
        rows.append(
            {
                "community": community_id,
                "size": len(vertices),
                "page_count": len(pages),
                "top_pages": [_with_score(graph.vs[idx], pr[idx], "pagerank") for idx in top_pages],
            }
        )
    rows.sort(key=lambda row: row["size"], reverse=True)
    return rows[:limit]


def core(
    db_path: Optional[str | Path] = None,
    *,
    limit: int = 25,
    node_kind: Optional[str] = "page",
) -> list[dict[str, Any]]:
    graph, _ = load_relationship_graph(db_path)
    scores = graph.coreness(mode="all")
    return _top_scored(graph, scores, limit=limit, node_kind=node_kind, key="coreness")


def link_suggestions(
    seed: str,
    db_path: Optional[str | Path] = None,
    *,
    limit: int = 25,
    node_kind: Optional[str] = "page",
) -> list[dict[str, Any]]:
    graph, _ = load_relationship_graph(db_path)
    seed_idx = _resolve_vertex(graph, seed)
    seed_neighbors = set(graph.neighbors(seed_idx))
    candidates = set()
    for neighbor in seed_neighbors:
        candidates.update(graph.neighbors(neighbor))
    candidates.discard(seed_idx)
    candidates -= seed_neighbors

    scored = []
    for idx in candidates:
        vertex = graph.vs[idx]
        if node_kind and vertex["kind"] != node_kind:
            continue
        neighbors = set(graph.neighbors(idx))
        shared = seed_neighbors & neighbors
        union = seed_neighbors | neighbors
        if not shared or not union:
            continue
        jaccard = len(shared) / len(union)
        adamic_adar = sum(
            1.0 / math.log(graph.degree(shared_idx))
            for shared_idx in shared
            if graph.degree(shared_idx) > 1
        )
        scored.append((jaccard, adamic_adar, len(shared), idx))

    scored.sort(reverse=True)
    out = []
    for jaccard, adamic_adar, shared_count, idx in scored[:limit]:
        row = _node_summary(graph.vs[idx])
        row.update(
            {
                "jaccard": float(jaccard),
                "adamic_adar": float(adamic_adar),
                "shared_neighbor_count": shared_count,
            }
        )
        out.append(row)
    return out


def stale_important(
    db_path: Optional[str | Path] = None,
    *,
    limit: int = 25,
    node_kind: Optional[str] = "page",
) -> list[dict[str, Any]]:
    graph, _ = load_relationship_graph(db_path)
    now = _now_ms()
    pr = graph.pagerank(weights="weight" if graph.ecount() else None)
    max_pr = max(pr) if pr else 0.0
    scores = []
    for idx, score in enumerate(pr):
        edit_time = graph.vs[idx]["edit_time"] or graph.vs[idx]["create_time"] or now
        age_days = max(0.0, (now - int(edit_time)) / 86_400_000)
        scores.append((score / max_pr if max_pr else 0.0) * math.log1p(age_days))
    return _top_scored(graph, scores, limit=limit, node_kind=node_kind, key="stale_importance")


def related_context(
    seeds: Sequence[str],
    db_path: Optional[str | Path] = None,
    *,
    limit: int = 25,
) -> dict[str, Any]:
    if not seeds:
        raise ValueError("At least one seed UID or page title is required")
    graph, _ = load_relationship_graph(db_path)
    seed_indexes = {_resolve_vertex(graph, seed) for seed in seeds}
    reset = [0.0] * graph.vcount()
    for idx in seed_indexes:
        reset[idx] = 1.0 / len(seed_indexes)
    pr = graph.personalized_pagerank(
        damping=0.85,
        reset=reset,
        weights="weight" if graph.ecount() else None,
    )

    seed_neighbors = set()
    for seed_idx in seed_indexes:
        seed_neighbors.update(graph.neighbors(seed_idx))
    shared_counts = []
    for idx in range(graph.vcount()):
        if idx in seed_indexes:
            shared_counts.append(0)
        else:
            shared_counts.append(len(seed_neighbors & set(graph.neighbors(idx))))
    max_shared = max(shared_counts) if shared_counts else 0

    scores = []
    for idx, score in enumerate(pr):
        if idx in seed_indexes:
            continue
        shared_score = shared_counts[idx] / max_shared if max_shared else 0.0
        page_boost = 0.002 if graph.vs[idx]["kind"] == "page" else 0.0
        scores.append((float(score) + (0.05 * shared_score) + page_boost, idx))
    scores.sort(reverse=True)
    return {
        "seeds": [_node_summary(graph.vs[idx]) for idx in sorted(seed_indexes)],
        "candidates": [
            _with_score(graph.vs[idx], score, "context_score")
            for score, idx in scores[:limit]
        ],
    }


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _kind(value: str) -> Optional[str]:
    return None if value == "all" else value


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Roam local graph index and analysis")
    sub = parser.add_subparsers(dest="command")

    index_cmd = sub.add_parser("index", help="Build or refresh the local graph index")
    index_cmd.add_argument("--db")

    stats_cmd = sub.add_parser("stats", help="Show index stats")
    stats_cmd.add_argument("--db")

    overview_cmd = sub.add_parser("overview", help="Show graph overview")
    overview_cmd.add_argument("--db")

    pr_cmd = sub.add_parser("pagerank", help="Global PageRank")
    pr_cmd.add_argument("--db")
    pr_cmd.add_argument("--limit", type=int, default=25)
    pr_cmd.add_argument("--kind", choices=("page", "block", "unknown", "all"), default="page")

    ppr_cmd = sub.add_parser("personalized-pagerank", help="Personalized PageRank")
    ppr_cmd.add_argument("seeds", nargs="+")
    ppr_cmd.add_argument("--db")
    ppr_cmd.add_argument("--limit", type=int, default=25)
    ppr_cmd.add_argument("--kind", choices=("page", "block", "unknown", "all"), default="page")
    ppr_cmd.add_argument("--include-seeds", action="store_true")

    path_cmd = sub.add_parser("path", help="Shortest relationship path")
    path_cmd.add_argument("source")
    path_cmd.add_argument("target")
    path_cmd.add_argument("--db")

    cent_cmd = sub.add_parser("centrality", help="Centrality ranking")
    cent_cmd.add_argument("metric", choices=("degree", "indegree", "outdegree", "betweenness", "closeness", "eigenvector", "hub", "authority"))
    cent_cmd.add_argument("--db")
    cent_cmd.add_argument("--limit", type=int, default=25)
    cent_cmd.add_argument("--kind", choices=("page", "block", "unknown", "all"), default="page")

    comp_cmd = sub.add_parser("components", help="Connected components")
    comp_cmd.add_argument("--db")
    comp_cmd.add_argument("--mode", choices=("weak", "strong"), default="weak")
    comp_cmd.add_argument("--limit", type=int, default=10)

    comm_cmd = sub.add_parser("communities", help="Community detection")
    comm_cmd.add_argument("--db")
    comm_cmd.add_argument("--method", choices=("leiden", "louvain", "multilevel", "label_propagation", "infomap"), default="leiden")
    comm_cmd.add_argument("--limit", type=int, default=20)

    core_cmd = sub.add_parser("core", help="K-core/coreness")
    core_cmd.add_argument("--db")
    core_cmd.add_argument("--limit", type=int, default=25)
    core_cmd.add_argument("--kind", choices=("page", "block", "unknown", "all"), default="page")

    links_cmd = sub.add_parser("link-suggestions", help="Common-neighbor link suggestions")
    links_cmd.add_argument("seed")
    links_cmd.add_argument("--db")
    links_cmd.add_argument("--limit", type=int, default=25)
    links_cmd.add_argument("--kind", choices=("page", "block", "unknown", "all"), default="page")

    stale_cmd = sub.add_parser("stale-important", help="Important but neglected nodes")
    stale_cmd.add_argument("--db")
    stale_cmd.add_argument("--limit", type=int, default=25)
    stale_cmd.add_argument("--kind", choices=("page", "block", "unknown", "all"), default="page")

    related_cmd = sub.add_parser("related-context", help="Combined context retrieval")
    related_cmd.add_argument("seeds", nargs="+")
    related_cmd.add_argument("--db")
    related_cmd.add_argument("--limit", type=int, default=25)

    args = parser.parse_args(argv)
    if args.command == "index":
        _print_json(build_index(args.db))
    elif args.command == "stats":
        _print_json(stats(args.db))
    elif args.command == "overview":
        _print_json(overview(args.db))
    elif args.command == "pagerank":
        _print_json(pagerank(args.db, limit=args.limit, node_kind=_kind(args.kind)))
    elif args.command == "personalized-pagerank":
        _print_json(
            personalized_pagerank(
                args.seeds,
                args.db,
                limit=args.limit,
                node_kind=_kind(args.kind),
                include_seeds=args.include_seeds,
            )
        )
    elif args.command == "path":
        _print_json(shortest_path(args.source, args.target, args.db))
    elif args.command == "centrality":
        _print_json(centrality(args.db, metric=args.metric, limit=args.limit, node_kind=_kind(args.kind)))
    elif args.command == "components":
        _print_json(components(args.db, mode=args.mode, limit=args.limit))
    elif args.command == "communities":
        _print_json(communities(args.db, method=args.method, limit=args.limit))
    elif args.command == "core":
        _print_json(core(args.db, limit=args.limit, node_kind=_kind(args.kind)))
    elif args.command == "link-suggestions":
        _print_json(link_suggestions(args.seed, args.db, limit=args.limit, node_kind=_kind(args.kind)))
    elif args.command == "stale-important":
        _print_json(stale_important(args.db, limit=args.limit, node_kind=_kind(args.kind)))
    elif args.command == "related-context":
        _print_json(related_context(args.seeds, args.db, limit=args.limit))
    else:
        parser.print_help()
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
