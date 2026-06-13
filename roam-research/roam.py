"""Roam Research API client.

Reads credentials from environment variables:
  ROAMRESEARCH_GRAPH  - graph name
  ROAMRESEARCH_KEY    - API token

Handles the 308 peer redirect that Roam uses for graph routing.
"""

import json
import os
import random
import string
from typing import Any, Dict, List, Optional, Union
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE_URL = "https://api.roamresearch.com"


def _env():
    graph = os.environ.get("ROAMRESEARCH_GRAPH")
    key = os.environ.get("ROAMRESEARCH_KEY")
    if not graph or not key:
        raise RuntimeError(
            "Set ROAMRESEARCH_GRAPH and ROAMRESEARCH_KEY environment variables"
        )
    return graph, key


def _headers(key: str) -> dict:
    return {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {key}",
        "x-authorization": f"Bearer {key}",
    }


def _post(url: str, body: dict, headers: dict) -> dict:
    data = json.dumps(body).encode()
    req = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        if e.code in (301, 302, 307, 308):
            redirect_url = e.headers.get("Location")
            if redirect_url:
                return _post(redirect_url, body, headers)
        body_text = e.read().decode() if e.fp else ""
        if e.code == 401:
            raise RuntimeError(
                f"HTTP 401 Unauthorized: {body_text}\n"
                "Check that ROAMRESEARCH_KEY has read (and write) access. "
                "Generate a new token in Roam: Settings > Graph > API Tokens."
            ) from e
        raise RuntimeError(f"HTTP {e.code}: {body_text}") from e


def _api(endpoint: str, body: dict) -> dict:
    graph, key = _env()
    url = f"{BASE_URL}/api/graph/{graph}/{endpoint}"
    return _post(url, body, _headers(key))


def generate_uid() -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=9))


# --- Query ---

def query(datalog: str, args: Optional[Dict] = None) -> List:
    payload = {"query": datalog}
    if args:
        payload["args"] = args
    result = _api("q", payload)
    return result if isinstance(result, list) else result.get("result", result)


def pull(uid: str, selector: str = "[*]") -> dict:
    return _api("pull", {
        "eid": f'[:block/uid "{uid}"]',
        "selector": selector,
    })


def pull_many(uids: List[str], selector: str = "[*]") -> List:
    return _api("pull-many", {
        "eids": [f'[:block/uid "{u}"]' for u in uids],
        "selector": selector,
    })


# --- Query helpers ---

def list_pages() -> List[Dict]:
    return query('[:find (pull ?p [:node/title :block/uid]) :where [?p :node/title _]]')


def find_page(title: str) -> List[Dict]:
    q = f'[:find (pull ?p [:node/title :block/uid]) :where [?p :node/title "{title}"]]'
    return query(q)


def page_blocks(title: str) -> List[Dict]:
    q = (
        '[:find (pull ?b [:block/string :block/uid :block/order]) '
        f':where [?p :node/title "{title}"] [?b :block/page ?p]]'
    )
    return query(q)


def search_blocks(text: str) -> List[Dict]:
    q = (
        '[:find (pull ?b [:block/string :block/uid]) '
        ':where [?b :block/string ?s] '
        f'[(clojure.string/includes? ?s "{text}")]]'
    )
    return query(q)


def page_tree(uid: str) -> dict:
    return pull(uid, "[:node/title :block/uid :block/string :block/order {:block/children ...}]")


# --- Write ---

def _write(body: dict) -> dict:
    return _api("write", body)


def create_page(title: str, uid: Optional[str] = None, children_view: str = "bullet") -> str:
    uid = uid or generate_uid()
    _write({
        "action": "create-page",
        "page": {"title": title, "uid": uid, "children-view-type": children_view},
    })
    return uid


def create_block(parent_uid: str, text: str, order: Union[int, str] = "last", uid: Optional[str] = None) -> str:
    uid = uid or generate_uid()
    _write({
        "action": "create-block",
        "location": {"parent-uid": parent_uid, "order": order},
        "block": {"string": text, "uid": uid},
    })
    return uid


def update_block(uid: str, text: str) -> dict:
    return _write({
        "action": "update-block",
        "block": {"uid": uid, "string": text},
    })


def update_page(uid: str, title: str) -> dict:
    return _write({
        "action": "update-page",
        "page": {"uid": uid, "title": title},
    })


def delete_block(uid: str) -> dict:
    return _write({"action": "delete-block", "block": {"uid": uid}})


def delete_page(uid: str) -> dict:
    return _write({"action": "delete-page", "page": {"uid": uid}})


def move_block(uid: str, new_parent_uid: str, order: Union[int, str] = 0) -> dict:
    return _write({
        "action": "move-block",
        "location": {"parent-uid": new_parent_uid, "order": order},
        "block": {"uid": uid},
    })


def create_page_with_blocks(title: str, blocks: list) -> str:
    """Create a page with a nested block tree.

    blocks is a list of dicts: {"text": "...", "children": [...]}
    Children follow the same structure recursively.
    Returns the page UID.
    """
    page_uid = create_page(title)

    def _create_children(parent_uid: str, children: list):
        for i, block in enumerate(children):
            block_uid = create_block(parent_uid, block["text"], order=i)
            if block.get("children"):
                _create_children(block_uid, block["children"])

    _create_children(page_uid, blocks)
    return page_uid


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "pages":
        for row in list_pages():
            page = row[0] if isinstance(row, list) else row
            print(f"  {page.get(':node/title', '?'):50s}  uid={page.get(':block/uid', '?')}")
    else:
        print("Usage: python roam.py pages")
