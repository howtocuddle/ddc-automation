#!/usr/bin/env python3
"""Shared helpers for merging page-level JSON checkpoints."""
from __future__ import annotations

from typing import Dict, List, Optional

CONT_SENTINEL_ID = "__CONT__"
PAGE_SENTINEL_ID = "__PAGE__"


def apply_continuation_if_any(page_objs: List[dict], merged: List[dict]) -> List[dict]:
    """Handle a leading continuation sentinel for the current page.

    When a page begins mid-entry, the generation step prepends a continuation
    sentinel (``__CONT__``). The sentinel carries additional ``scope.notes``
    lines that should be appended to the trailing real concept from previous
    pages. After applying the carry-over notes the sentinel is removed.

    Args:
        page_objs: Objects loaded for the current page.
        merged: Accumulated objects from prior pages; used to locate the last
            real concept that should receive the continuation notes.

    Returns:
        The page objects with the sentinel removed (if present).
    """
    if not page_objs:
        return page_objs

    first = page_objs[0]
    if not (isinstance(first, dict) and first.get("id") == CONT_SENTINEL_ID and first.get("notation") == CONT_SENTINEL_ID):
        return page_objs

    scope = first.get("scope") or {}
    cont_notes: List[str] = []
    if isinstance(scope, dict):
        notes_val = scope.get("notes")
        if isinstance(notes_val, list):
            cont_notes = notes_val

    if cont_notes:
        for i in range(len(merged) - 1, -1, -1):
            candidate = merged[i]
            if not isinstance(candidate, dict):
                continue
            if candidate.get("id") in (CONT_SENTINEL_ID, PAGE_SENTINEL_ID):
                continue

            tgt_scope = candidate.setdefault("scope", {})
            if not isinstance(tgt_scope, dict):
                tgt_scope = {}
                candidate["scope"] = tgt_scope

            notes = tgt_scope.setdefault("notes", [])
            if isinstance(notes, list):
                notes.extend(cont_notes)
            else:
                tgt_scope["notes"] = cont_notes
            break

    return page_objs[1:]


def is_page_lead_sentinel(obj: dict, page_number: Optional[int] = None, img_name: Optional[str] = None) -> bool:
    """Return True if *obj* represents a page-lead (``__PAGE__``) sentinel."""
    if not isinstance(obj, dict):
        return False
    if obj.get("id") != PAGE_SENTINEL_ID or obj.get("notation") != PAGE_SENTINEL_ID:
        return False
    if obj.get("type") != "Concept":
        return False

    if page_number is not None and obj.get("page") != page_number:
        return False

    if img_name is not None:
        src = obj.get("source", {})
        if not isinstance(src, dict) or src.get("fileName") != img_name:
            return False

    return True


def apply_page_lead_if_any(
    page_objs: List[dict],
    page_number: int,
    img_name: Optional[str],
    page_leads: Dict[int, dict],
) -> List[dict]:
    """Capture and drop a leading ``__PAGE__`` sentinel if present.

    The sentinel is stored inside *page_leads* under the 1-based page number.
    When no sentinel is present, *page_objs* is returned unchanged.
    """
    if not page_objs:
        return page_objs

    first = page_objs[0]
    if is_page_lead_sentinel(first, page_number, img_name):
        page_leads[page_number] = first
        return page_objs[1:]
    return page_objs


__all__ = [
    "apply_continuation_if_any",
    "apply_page_lead_if_any",
    "is_page_lead_sentinel",
    "CONT_SENTINEL_ID",
    "PAGE_SENTINEL_ID",
]
