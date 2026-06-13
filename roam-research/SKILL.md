---
name: roam-research
description: Query and create content in RoamResearch graphs via the Roam Backend API.
---

# RoamResearch API Skill

Interact with a user's RoamResearch graph: query for blocks/pages using Datalog, retrieve entity data, create whole new pages with nested block trees, and run fast local graph analysis over a metadata-only SQLite index.

## Authentication

Credentials are read from environment variables:

- `ROAMRESEARCH_GRAPH` -- the graph name
- `ROAMRESEARCH_KEY` -- the API token (generated in Roam under Settings > API Tokens)

Before making any API call, verify both are set. If either is missing, tell the user to set them (e.g. `export ROAMRESEARCH_GRAPH=mygraph` and `export ROAMRESEARCH_KEY=roam-...`).

## Python Client

All API interaction uses the Python module at `roam-research/roam.py`. It handles authentication, the 308 peer redirect, and UID generation. Run commands via:

```bash
python3 /Users/paul/.claude/skills/roam-research/roam.py pages
```

Or import in inline Python:

```python
import sys; sys.path.insert(0, "/Users/paul/.claude/skills/roam-research")
import roam
```

## Available Functions

### Query

| Function | Description |
|----------|-------------|
| `roam.query(datalog, args=None)` | Run a raw Datalog query |
| `roam.pull(uid, selector="[*]")` | Pull a single entity by UID |
| `roam.pull_many(uids, selector="[*]")` | Pull multiple entities |

### Local Graph Index

Graph analysis lives in `roam_graph.py`, keeping the existing `roam.py` content CLI intact. The graph index stores page/block metadata and topology in SQLite: UIDs, page titles, timestamps, page/block hierarchy, and references. It deliberately does **not** store block strings/content. After graph analysis identifies useful UIDs, fetch full content with `roam.pull`, `roam.pull_many`, or `roam.page_tree`.

Graph operations require `python-igraph`:

```bash
python3 -m pip install -r /Users/paul/.claude/skills/roam-research/requirements.txt
```

Default DB path: `~/.cache/roam-research/$ROAMRESEARCH_GRAPH.sqlite3`.

Build or refresh the index:

```bash
python3 /Users/paul/.claude/skills/roam-research/roam_graph.py index
```

Use `--db /path/to/index.sqlite3` to override the DB path.

| Function | Description |
|----------|-------------|
| `roam_graph.build_index(db_path=None)` | Full metadata/topology refresh into SQLite |
| `roam_graph.stats(db_path=None)` | Show index counts and last sync metadata |
| `roam_graph.load_graph(db_path=None, directed=True, edge_kinds=None)` | Load the index into `python-igraph` |
| `roam_graph.load_relationship_graph(db_path=None)` | Load a simplified undirected graph for related-idea operations |
| `roam_graph.overview(db_path=None)` | Basic graph size, density, and component stats |

### Graph Algorithms

| Function | Description |
|----------|-------------|
| `roam_graph.pagerank(db_path=None, limit=25, node_kind="page")` | Global importance ranking over the directed graph |
| `roam_graph.personalized_pagerank(seeds, db_path=None, limit=25, node_kind="page")` | Related nodes from seed page titles or UIDs using the undirected relationship view |
| `roam_graph.shortest_path(source, target, db_path=None)` | Explain how two nodes connect using the undirected relationship view |
| `roam_graph.centrality(db_path=None, metric="betweenness", limit=25, node_kind="page")` | Degree, betweenness, closeness, eigenvector, hub, or authority |
| `roam_graph.components(db_path=None, mode="weak", limit=10)` | Largest connected components and sample pages |
| `roam_graph.communities(db_path=None, method="leiden", limit=20)` | Topic/community detection |
| `roam_graph.core(db_path=None, limit=25, node_kind="page")` | K-core/coreness ranking |
| `roam_graph.link_suggestions(seed, db_path=None, limit=25, node_kind="page")` | Common-neighbor link suggestions |
| `roam_graph.stale_important(db_path=None, limit=25, node_kind="page")` | Important but neglected nodes |
| `roam_graph.related_context(seeds, db_path=None, limit=25)` | Combined context retrieval using personalized PageRank plus local shared-neighbor signal |

Equivalent CLI commands:

```bash
python3 /Users/paul/.claude/skills/roam-research/roam_graph.py stats
python3 /Users/paul/.claude/skills/roam-research/roam_graph.py pagerank --limit 20
python3 /Users/paul/.claude/skills/roam-research/roam_graph.py personalized-pagerank "Artificial Intelligence Agents"
python3 /Users/paul/.claude/skills/roam-research/roam_graph.py path "Artificial Intelligence Agents" "TDD"
python3 /Users/paul/.claude/skills/roam-research/roam_graph.py communities --method leiden
python3 /Users/paul/.claude/skills/roam-research/roam_graph.py link-suggestions "AI Operating Model"
python3 /Users/paul/.claude/skills/roam-research/roam_graph.py related-context "Claude Code" "AI Operating Model"
```

### Compound Agent Operations

| User goal | Operation |
|----------|-----------|
| Find important context for a question | `roam_graph.related_context`, then fetch returned UIDs with `pull_many` or `page_tree` |
| Explain a connection between concepts | `roam_graph.shortest_path`, then fetch the page trees for the pages in the path |
| Discover themes/MOCs | `roam_graph.communities`, then inspect the top pages in each community |
| Resurface useful forgotten material | `roam_graph.stale_important`, then fetch the top pages |
| Improve graph hygiene | `roam_graph.components`, `roam_graph.link_suggestions`, and `roam_graph.core` |
| Find bridging ideas | `roam_graph.centrality(metric="betweenness")` |

### Query Helpers

| Function | Description |
|----------|-------------|
| `roam.list_pages()` | List all pages (title + uid) |
| `roam.find_page(title)` | Find a page by exact title |
| `roam.page_blocks(title)` | Get top-level blocks on a page |
| `roam.search_blocks(text)` | Find blocks containing text |
| `roam.page_tree(uid)` | Get full recursive block tree for a page |

### Write

| Function | Returns |
|----------|---------|
| `roam.create_page(title, uid=None)` | page UID |
| `roam.create_block(parent_uid, text, order="last", uid=None)` | block UID |
| `roam.update_block(uid, text)` | response dict |
| `roam.update_page(uid, title)` | response dict |
| `roam.delete_block(uid)` | response dict |
| `roam.delete_page(uid)` | response dict |
| `roam.move_block(uid, new_parent_uid, order=0)` | response dict |

### Batch Page Creation

```python
roam.create_page_with_blocks("My Page", [
    {"text": "First block", "children": [
        {"text": "Nested child"},
    ]},
    {"text": "Second block"},
])
```

### UID Generation

`roam.generate_uid()` returns a 9-character alphanumeric string matching Roam's native format. All create functions auto-generate UIDs if not provided.

## Datalog Reference

The query language is Datalog (same as Datomic). Common patterns:

Find blocks containing text:
```
[:find (pull ?b [:block/string :block/uid]) :where [?b :block/string ?s] [(clojure.string/includes? ?s "search term")]]
```

Find a page by title:
```
[:find (pull ?p [:node/title :block/uid]) :where [?p :node/title "Page Title"]]
```

List all page titles:
```
[:find (pull ?p [:node/title :block/uid]) :where [?p :node/title _]]
```

Find blocks on a specific page:
```
[:find (pull ?b [:block/string :block/uid :block/order]) :where [?p :node/title "Page Title"] [?b :block/page ?p]]
```

Find blocks referencing a tag/page:
```
[:find (pull ?b [:block/string :block/uid]) :where [?b :block/refs ?ref] [?ref :node/title "TagName"]]
```

## Roam Markdown Reference

Block content supports Roam's markup:

- `**bold**` / `__italic__` / `~~strikethrough~~` / `^^highlight^^`
- `[[Page Reference]]` -- links to another page
- `((block-uid))` -- embeds/references another block
- `#tag` or `#[[multi word tag]]` -- tags (equivalent to page refs)
- `{{[[TODO]]}}` / `{{[[DONE]]}}` -- checkboxes
- `{{embed: ((block-uid))}}` -- block embed
- `` `inline code` `` and triple-backtick code blocks
- `![alt](url)` -- images
- `[text](url)` -- links

## Workflow Guidance

When asked to **query/search**: Use `roam.query()` with Datalog, or use the helper functions (`list_pages`, `search_blocks`, etc.). Start broad, refine as needed.

When asked to **read a page**: Use `roam.find_page(title)` to get the UID, then `roam.page_tree(uid)` for the full block tree.

When asked to **create a page**: Use `roam.create_page_with_blocks(title, blocks)` for pages with content, or `roam.create_page(title)` + individual `roam.create_block()` calls.

When asked to **update content**: Query first to find the target block UID, then use `roam.update_block(uid, text)`.

When asked to **analyze graph structure or find related material quickly**: Use `roam_graph.py` and the local graph index. If the index may be stale, run `roam_graph.py index` once, then use graph commands locally. Do not fetch page trees in a loop while traversing the graph.
