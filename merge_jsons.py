#!/usr/bin/env python3
"""Merge page-level JSON checkpoints produced by :mod:`gemini`."""
from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from merge_utils import apply_continuation_if_any, apply_page_lead_if_any

LOG = logging.getLogger("merge_jsons")
PAGE_FILE_RE = re.compile(r"^(?P<stem>.+)_p(?P<page>\d{5})$")


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def find_page_files(jsons_dir: Path, stem: Optional[str]) -> List[Tuple[str, int, Path]]:
    """Return ``(stem, page, path)`` tuples for per-page checkpoint files."""
    files: List[Tuple[str, int, Path]] = []
    for path in sorted(jsons_dir.glob("*.json")):
        match = PAGE_FILE_RE.match(path.stem)
        if not match:
            continue
        match_stem = match.group("stem")
        if stem and match_stem != stem:
            continue
        page = int(match.group("page"))
        files.append((match_stem, page, path))
    files.sort(key=lambda x: x[1])
    return files


def load_page_objects(path: Path) -> List[dict]:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data
    raise ValueError(f"JSON file {path} did not contain an object or array.")


def detect_image_name(page_objs: Sequence[dict]) -> Optional[str]:
    for obj in page_objs:
        if not isinstance(obj, dict):
            continue
        src = obj.get("source")
        if isinstance(src, dict):
            img = src.get("fileName")
            if isinstance(img, str):
                return img
    return None


def write_atomic_json(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".part")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def merge_pages(
    entries: Sequence[Tuple[str, int, Path]],
    capture_page_leads: bool,
    page_leads_path: Optional[Path],
    final_path: Path,
) -> None:
    merged: List[dict] = []
    page_leads: Dict[int, dict] = {}

    for stem, page, path in entries:
        page_objs = load_page_objects(path)
        img_name = detect_image_name(page_objs)

        if capture_page_leads:
            page_objs = apply_page_lead_if_any(page_objs, page, img_name, page_leads)
            if page in page_leads:
                LOG.debug("Captured __PAGE__ sentinel for p%d (%s)", page, stem)

        page_objs = apply_continuation_if_any(page_objs, merged)
        merged.extend(page_objs)
        LOG.info("Merged p%d from %s (%d object(s))", page, path.name, len(page_objs))

    write_atomic_json(final_path, merged)
    LOG.info("Wrote merged output → %s (%d objects)", final_path, len(merged))

    if capture_page_leads and page_leads:
        assert page_leads_path is not None
        ordered = [page_leads[p] for p in sorted(page_leads)]
        write_atomic_json(page_leads_path, ordered)
        LOG.info(
            "Wrote %d page-lead sentinel(s) → %s",
            len(ordered),
            page_leads_path,
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge per-page JSON checkpoints into a final array.")
    ap.add_argument("--jsons_dir", type=Path, default=Path("./jsons"))
    ap.add_argument("--stem", type=str, default=None, help="Filter checkpoints to this PDF stem.")
    ap.add_argument("--output", type=Path, default=Path("./final.json"), help="Merged JSON output path.")
    ap.add_argument(
        "--page_leads",
        action="store_true",
        help="Capture __PAGE__ sentinel objects into a sidecar file (removed from final merge).",
    )
    ap.add_argument(
        "--page_leads_path",
        type=Path,
        default=None,
        help="Explicit path for the page-leads sidecar. Defaults to <jsons>/<stem>.page_leads.json",
    )
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    setup_logging(args.verbose)

    if not args.jsons_dir.exists():
        raise SystemExit(f"JSON directory not found: {args.jsons_dir}")

    entries = find_page_files(args.jsons_dir, args.stem)
    if not entries:
        raise SystemExit("No checkpoint files were found.")

    stems = {stem for stem, _, _ in entries}
    if args.stem is None:
        if len(stems) > 1:
            raise SystemExit(
                "Multiple stems detected. Specify --stem to select which document to merge: "
                + ", ".join(sorted(stems))
            )
        args.stem = stems.pop()
    else:
        missing = [stem for stem in stems if stem != args.stem]
        if missing:
            LOG.warning(
                "Ignoring %d file(s) because their stem does not match --stem=%s",
                len(missing),
                args.stem,
            )

    page_leads_path = args.page_leads_path
    if args.page_leads:
        if page_leads_path is None:
            if args.stem is None:
                raise SystemExit("Cannot infer page_leads_path without a stem.")
            page_leads_path = args.jsons_dir / f"{args.stem}.page_leads.json"
        LOG.info("Page-lead sidecar will be written to %s", page_leads_path)
    else:
        if page_leads_path is not None:
            LOG.warning("--page_leads_path provided without --page_leads; ignoring the path.")
        page_leads_path = None

    merge_pages(entries, args.page_leads, page_leads_path, args.output)


if __name__ == "__main__":
    main()
