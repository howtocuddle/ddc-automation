#!/usr/bin/env python3
"""Brute-force hierarchy reconstruction with range support for Sch*.cleaned.json.

Enhancements over fix_hierarchy_bruteforce.py:
- Recognizes range codes (containing '-') as parent containers.
- A range code R like 004-006 becomes parent of any code whose root (before first '.') is numerically within [4,6] inclusive.
- A dotted range like 026.0001-026.0005 becomes parent of any code whose numeric value (at same precision) lies within the span.
  * For dotted ranges, only codes sharing the same prefix before the varying numeric part are considered.
  * Example: range 026.0001-026.0005 covers 026.0001, 026.0002, ..., 026.0005 (if present) and any further decimal extensions that start with those exact codes?  User request implies immediate codes (exact match). We include exact codes; deeper extensions (e.g., 026.0002.1) are children of 026.0002 as usual, not directly of the range.
- Range nodes also get broader computed by removing last segment (like ordinary codes) OR, for simple integer ranges (004-006), broader is null unless a shorter prefix range exists.

Rules Recap:
1. Extract bfCode from id (after VolumeN-); fall back to notation if needed.
2. Classify codes into:
   - simple: no '-' present
   - range: has '-'
3. Build child sets:
   a) For simple -> immediate dot segment children (as previous script).
   b) Additionally, for each range code, add each simple code that falls numerically inside the range and is not itself a range. Do not add codes that differ at a higher precision inside dotted range beyond exact coverage.
4. Ensure no duplicates in narrower arrays.
5. Broader assignment:
   - For simple codes: as before (truncate dot segments).
   - For range codes: attempt broader by truncating trailing dot segment if dotted range; for pure integer range (e.g., 004-006) try the left part before first '-' (004) if it exists as a standalone code, else null.

Limitations:
- Numeric parsing assumes each dot segment and range boundary after stripping leading zeros can be interpreted as integers.
- If parsing fails, fallback: do not link range children.

Outputs: SchN.bfrange.json + report hierarchy_report_bfrange.txt
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple
import re

ROOT = Path('.')
REPORT: List[str] = []
ID_CODE_RE = re.compile(r"^Volume\d+-(.+)$", re.IGNORECASE)
RANGE_RE = re.compile(r"^(.+)-(\d.*)$")  # simplified detection


def extract_code(entry: dict) -> str:
    idv = entry.get('id') or ''
    m = ID_CODE_RE.match(idv)
    if not m:
        return entry.get('notation') or ''
    return m.group(1)


def split_range(code: str) -> Tuple[str,str] | None:
    if '-' not in code:
        return None
    # Find last '-' that separates two numericish tails with a shared prefix possibility
    # For simplicity use first '-' occurrence; complex multi dashes rare here
    parts = code.split('-')
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def build_indices(entries: List[dict]):
    code_to_entries: Dict[str, List[dict]] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        code = extract_code(e)
        e['bfCode'] = code
        if code:
            code_to_entries.setdefault(code, []).append(e)
    return code_to_entries


def immediate_children_simple(codes: List[str]) -> Dict[str, Set[str]]:
    children: Dict[str, Set[str]] = {c: set() for c in codes}
    for c in codes:
        if '-' in c:  # skip range for simple child logic
            continue
        prefix = c + '.'
        plen = len(prefix)
        for d in codes:
            if d.startswith(prefix) and '-' not in d:
                remainder = d[plen:]
                if remainder and '.' not in remainder:
                    children[c].add(d)
    return children


def numeric_value_for(code: str) -> Tuple[str, str] | None:
    # Return (prefix, numeric_tail) for dotted codes where last segment is numeric
    if '-' in code:
        return None
    if '.' not in code:
        # treat root as (code, code) for range comparators that expect prefix
        return code, code
    parts = code.split('.')
    prefix = '.'.join(parts[:-1])
    tail = parts[-1]
    if not tail.replace('0','').isdigit() and not tail.isdigit():
        return None
    return prefix, tail


def expand_range_children(range_code: str, simple_codes: Set[str]) -> Set[str]:
    # Identify children covered by range.
    res: Set[str] = set()
    rng = split_range(range_code)
    if not rng:
        return res
    left, right = rng
    # Case 1: pure integer range (no dot in left and right start with digits)
    if '.' not in left and '.' not in right:
        try:
            l = int(left)
            r = int(right)
        except ValueError:
            return res
        for sc in simple_codes:
            if '-' in sc:
                continue
            if '.' in sc:
                continue
            try:
                v = int(sc)
            except ValueError:
                continue
            if l <= v <= r:
                res.add(sc)
        return res
    # Case 2: dotted range; require both sides share prefix before varying numeric portion
    # Strategy: find common prefix up to last dot of left side; compare numeric tails at that depth
    if '.' in left and '.' in right:
        lpref, ltail = left.rsplit('.',1)
        rpref, rtail = right.rsplit('.',1)
        if lpref != rpref:
            return res
        try:
            li = int(ltail)
            ri = int(rtail)
        except ValueError:
            return res
        # Candidate codes must match lpref.<num> exactly within bounds
        target_prefix = lpref + '.'
        for sc in simple_codes:
            if not sc.startswith(target_prefix):
                continue
            if '-' in sc:
                continue
            # Only accept one more segment beyond lpref (no deeper dots)
            rest = sc[len(target_prefix):]
            if not rest or '.' in rest:
                continue
            try:
                vi = int(rest)
            except ValueError:
                continue
            if li <= vi <= ri:
                res.add(sc)
    return res


def compute_broader(code: str, simple_set: Set[str]) -> str | None:
    if '-' in code:
        # For range codes try dotted truncation if dotted
        if '.' in code:
            left, _ = split_range(code) or (None,None)
            if left and '.' in left:
                parent = left.rsplit('.',1)[0]
                if parent in simple_set:
                    return parent
        # Otherwise attempt left side root for integer range
        left, _ = split_range(code) or (None,None)
        if left and left in simple_set:
            return left
        return None
    # Simple code
    if '.' not in code:
        return None
    parts = code.split('.')
    for i in range(len(parts)-1,0,-1):
        cand = '.'.join(parts[:i])
        if cand in simple_set:
            return cand
    return None


def range_parent(code: str, simple_set: Set[str]) -> str | None:
    """Return the parent simple code that should list this range as a child.
    Examples:
      004-006 -> None (do not attach to 004 unless explicit requirement). We choose left root if exists.
      026.0001-026.0005 -> 026 (base before first dot of left side)
    Implementation:
      - For dotted range: take left side, take its base root (split at first '.') -> candidate parent.
      - If that candidate exists as simple code, return it.
      - For pure integer range: take left side as candidate if exists in simple_set.
    """
    if '-' not in code:
        return None
    rng = split_range(code)
    if not rng:
        return None
    left, _ = rng
    if '.' in left:
        base_root = left.split('.',1)[0]
        if base_root in simple_set:
            return base_root
    else:
        if left in simple_set:
            return left
    return None


def process_file(path: Path):
    try:
        entries = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        REPORT.append(f"{path.name}: parse error {e}")
        return
    if not isinstance(entries, list):
        REPORT.append(f"{path.name}: root not list")
        return
    code_to_entries = build_indices(entries)
    codes = list(code_to_entries.keys())
    simple_codes = {c for c in codes if '-' not in c}
    range_codes = {c for c in codes if '-' in c}
    # Simple immediate children
    simple_child_map = immediate_children_simple(codes)
    # Range children
    range_children: Dict[str, Set[str]] = {}
    for rc in range_codes:
        range_children[rc] = expand_range_children(rc, simple_codes)
    # Build union child map (initialize)
    child_map: Dict[str, Set[str]] = {c: set() for c in codes}
    for c, kids in simple_child_map.items():
        child_map[c].update(kids)
    for rc, kids in range_children.items():
        child_map[rc].update(kids)
    # Add range nodes themselves as children of their base parent if applicable
    for rc in range_codes:
        parent = range_parent(rc, simple_codes)
        if parent:
            child_map[parent].add(rc)
    # Compute broader for each code
    simple_set = simple_codes  # for lookup
    broader_map: Dict[str, str | None] = {}
    for c in codes:
        broader_map[c] = compute_broader(c, simple_set)
    # Assign hierarchy
    for code, ents in code_to_entries.items():
        narrower_sorted = sorted(child_map.get(code, []))
        broader = broader_map.get(code)
        for e in ents:
            e['hierarchy'] = {
                'broader': broader,
                'narrower': narrower_sorted
            }
    out_path = path.with_name(path.stem.replace('.cleaned', '.bfrange') + '.json')
    out_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
    REPORT.append(f"{path.name}: entries={len(entries)} codes={len(codes)} ranges={len(range_codes)}")


def main():
    for p in sorted(Path('.').glob('Sch*.cleaned.json')):
        process_file(p)
    Path('hierarchy_report_bfrange.txt').write_text('\n'.join(REPORT)+'\n', encoding='utf-8')
    print('\n'.join(REPORT))
    print('Report written to hierarchy_report_bfrange.txt')

if __name__ == '__main__':
    main()
