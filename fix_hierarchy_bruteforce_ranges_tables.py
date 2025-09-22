#!/usr/bin/env python3
"""Brute-force hierarchy reconstruction with range support for Table*.cleaned.json.

Based on fix_hierarchy_bruteforce_ranges.py but adapted for table files.
Tables use notation patterns like:
- "-04" (standard subdivision)
- "-092" (biography)
- "-0901" (persons treatment)
- etc.

The hierarchy logic remains the same but adapted for table notation patterns.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple

REPORT = []


def extract_code(entry: dict) -> str | None:
    """Extract bfCode from table entry."""
    # For tables, use notation directly as it's already the key identifier
    notation = entry.get('notation')
    if notation:
        return notation
    
    # Fallback to id parsing if needed
    id_str = entry.get('id', '')
    if id_str.startswith('T'):
        # Format like "T1:-04" -> "-04"
        if ':' in id_str:
            return id_str.split(':', 1)[1]
    
    return None


def split_range(code: str) -> Tuple[str, str] | None:
    """Split range notation like "-004--006" into ("-004", "-006")."""
    if '--' not in code:
        return None
    parts = code.split('--')
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def build_indices(entries: List[dict]):
    """Build code to entries mapping."""
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
    """Find immediate children for simple (non-range) codes."""
    children: Dict[str, Set[str]] = {c: set() for c in codes}
    for c in codes:
        if '--' in c:  # skip range codes
            continue
        
        # For table codes, look for immediate extensions
        # E.g., "-09" is parent of "-092", "-093", etc.
        for d in codes:
            if d == c or '--' in d:
                continue
            
            # Check if d is an immediate child of c
            if d.startswith(c) and len(d) > len(c):
                remainder = d[len(c):]
                # Immediate child if remainder has no further structure
                # For tables, this means remainder should be just digits
                if remainder.isdigit() and len(remainder) <= 3:  # reasonable limit
                    children[c].add(d)
    
    return children


def expand_range_children(range_code: str, simple_codes: Set[str]) -> Set[str]:
    """Find children covered by a range notation."""
    res: Set[str] = set()
    rng = split_range(range_code)
    if not rng:
        return res
    
    left, right = rng
    
    # For table codes, we need to handle patterns like "-004--006"
    # Strip leading '-' for numeric comparison if present
    left_num = left.lstrip('-')
    right_num = right.lstrip('-')
    
    try:
        l = int(left_num)
        r = int(right_num)
    except ValueError:
        return res
    
    for sc in simple_codes:
        if '--' in sc:
            continue
        
        # Extract numeric part for comparison
        sc_num = sc.lstrip('-')
        if not sc_num.isdigit():
            continue
            
        try:
            v = int(sc_num)
        except ValueError:
            continue
            
        if l <= v <= r:
            res.add(sc)
    
    return res


def compute_broader(code: str, simple_set: Set[str]) -> str | None:
    """Compute the broader (parent) code."""
    if '--' in code:
        # For range codes, try to find parent by truncating
        left, _ = split_range(code) or (None, None)
        if left:
            # Try progressively shorter versions
            for i in range(len(left) - 1, 0, -1):
                cand = left[:i]
                if cand in simple_set:
                    return cand
        return None
    
    # For simple codes, find parent by truncating
    if len(code) <= 1:
        return None
    
    # Try progressively shorter versions
    for i in range(len(code) - 1, 0, -1):
        cand = code[:i]
        if cand in simple_set:
            return cand
    
    return None


def range_parent(code: str, simple_set: Set[str]) -> str | None:
    """Find which simple code should list this range as a child."""
    if '--' not in code:
        return None
    
    rng = split_range(code)
    if not rng:
        return None
    
    left, _ = rng
    
    # Try to find a parent by truncating the left side
    for i in range(len(left) - 1, 0, -1):
        cand = left[:i]
        if cand in simple_set:
            return cand
    
    return None


def process_file(path: Path):
    """Process a single table file."""
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
    simple_codes = {c for c in codes if '--' not in c}
    range_codes = {c for c in codes if '--' in c}
    
    REPORT.append(f"{path.name}: {len(entries)} entries, {len(simple_codes)} simple codes, {len(range_codes)} range codes")
    
    # Build simple children
    simple_child_map = immediate_children_simple(codes)
    
    # Build range children
    range_children: Dict[str, Set[str]] = {}
    for rc in range_codes:
        range_children[rc] = expand_range_children(rc, simple_codes)
    
    # Combine all children
    child_map: Dict[str, Set[str]] = {c: set() for c in codes}
    for c, kids in simple_child_map.items():
        child_map[c].update(kids)
    
    for rc, kids in range_children.items():
        child_map[rc].update(kids)
        # Also add this range as child of its parent
        parent = range_parent(rc, simple_codes)
        if parent:
            child_map[parent].add(rc)
    
    # Compute broader relationships
    broader_map: Dict[str, str | None] = {}
    for c in codes:
        broader_map[c] = compute_broader(c, simple_codes)
    
    # Update all entries with hierarchy
    updated_count = 0
    for c, entry_list in code_to_entries.items():
        narrower = sorted(child_map.get(c, set()))
        broader = broader_map.get(c)
        
        for entry in entry_list:
            if 'hierarchy' not in entry:
                entry['hierarchy'] = {}
            entry['hierarchy']['narrower'] = narrower
            entry['hierarchy']['broader'] = broader
            updated_count += 1
    
    REPORT.append(f"{path.name}: updated {updated_count} entries with hierarchy")
    
    # Write output file
    out_path = path.with_name(path.stem.replace('.cleaned', '.bfrange') + '.json')
    out_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding='utf-8')
    REPORT.append(f"{path.name}: wrote {out_path.name}")


def main():
    """Process all table files."""
    table_files = sorted(Path('.').glob('Table*.cleaned.json'))
    
    if not table_files:
        print("No Table*.cleaned.json files found")
        return
    
    for p in table_files:
        process_file(p)
    
    # Write report
    report_path = Path('hierarchy_report_tables_bfrange.txt')
    report_path.write_text('\n'.join(REPORT) + '\n', encoding='utf-8')
    
    print('\n'.join(REPORT))
    print(f'Report written to {report_path.name}')


if __name__ == '__main__':
    main()