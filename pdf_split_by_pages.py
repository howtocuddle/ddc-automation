#!/usr/bin/env python3
"""
pdf_split_by_pages.py
---------------------
Split a PDF into new PDF files by either explicit page ranges or cut points.

Dependencies:
    pip install pypdf tqdm

Two ways to split:
1) By explicit ranges (each range becomes an output file)
   --ranges "1-5,6-10,12,20-25"
   Supports open-ended "-10" (1..10) and "50-" (50..end).

2) By cut points (split the document at given pages)
   --cuts "10,20"  -> creates: 1..10, 11..20, 21..end

You can also extract a single combined subset into one file with --extract:
   --extract "2-3,10,15-18"  -> writes just one PDF with those pages in order.

Usage:
    python pdf_split_by_pages.py input.pdf --ranges "1-5,6-10,12"
    python pdf_split_by_pages.py input.pdf --cuts "10,20"
    python pdf_split_by_pages.py input.pdf --extract "2-3,10,15-18" -o outdir --prefix part_

Notes:
- Page numbers are 1-based in the CLI; inclusive ranges.
- Encrypted PDFs: provide --password if needed.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Tuple
import sys

from pypdf import PdfReader, PdfWriter
from tqdm import tqdm


def parse_ranges_spec(spec: str, total: int) -> List[Tuple[int, int]]:
    """
    Parse a comma-separated range spec like "1-5,8,10-12" into a list of (start,end),
    with 1-based inclusive bounds. Supports open-ended "-10" and "5-" (clamped to total).
    Ignores parts that fall completely out of range.
    Preserves the given order and does not merge overlaps automatically.
    """
    ranges: List[Tuple[int, int]] = []
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        if "-" in part:
            a, b = part.split("-", 1)
            a = a.strip()
            b = b.strip()
            start = 1 if a == "" else int(a)
            end = total if b == "" else int(b)
        else:
            start = end = int(part)
        # clamp to [1, total]
        if end < 1 or start > total:
            continue
        start = max(1, start)
        end = min(total, end)
        if start > end:
            start, end = end, start
        ranges.append((start, end))
    if not ranges:
        raise ValueError("No valid page ranges parsed from specification.")
    return ranges


def parse_cuts_spec(spec: str, total: int) -> List[Tuple[int, int]]:
    """
    Parse cut points like "10,20" and produce contiguous segments:
      1..10, 11..20, 21..total
    Cut points outside [1, total-1] are ignored.
    """
    raw = []
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        try:
            n = int(part)
            if 1 <= n <= total - 1:
                raw.append(n)
        except ValueError:
            pass
    cuts = sorted(set(raw))
    if not cuts:
        # if no valid cuts, the whole doc is one segment
        return [(1, total)]
    segments: List[Tuple[int, int]] = []
    start = 1
    for c in cuts:
        segments.append((start, c))
        start = c + 1
    if start <= total:
        segments.append((start, total))
    return segments


def write_chunk(reader: PdfReader, start: int, end: int, outpath: Path) -> int:
    """
    Write pages [start..end] (1-based inclusive) from reader to outpath.
    Returns number of pages written.
    """
    writer = PdfWriter()
    for p in range(start, end + 1):
        writer.add_page(reader.pages[p - 1])
    outpath.parent.mkdir(parents=True, exist_ok=True)
    with outpath.open("wb") as f:
        writer.write(f)
    return end - start + 1


def main():
    parser = argparse.ArgumentParser(description="Split a PDF into parts by ranges or cut points.")
    parser.add_argument("pdf", type=Path, help="Path to input PDF")
    parser.add_argument("-o", "--outdir", type=Path, default=None, help="Output directory (default: <pdf_basename>_split/)")
    parser.add_argument("--prefix", type=str, default="part_", help="Output filename prefix (default: part_)")
    parser.add_argument("--password", type=str, default=None, help="Password for encrypted PDFs")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ranges", type=str, help='Comma-separated ranges like "1-5,8,10-12" (each range -> separate file)')
    group.add_argument("--cuts", type=str, help='Comma-separated cut points like "10,20" (splits into contiguous parts)')
    group.add_argument("--extract", type=str, help='Extract pages as one combined subset: e.g., "2-3,10,15-18"')

    parser.add_argument("--digits", type=int, default=None, help="Zero-pad width for part numbers (default: auto)")
    args = parser.parse_args()

    pdf_path: Path = args.pdf
    if not pdf_path.exists():
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    outdir = args.outdir or Path(f"{pdf_path.stem}_split")
    outdir.mkdir(parents=True, exist_ok=True)

    # Open PDF
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as e:
        print(f"Failed to open PDF: {e}", file=sys.stderr)
        sys.exit(2)

    # Decrypt if needed
    if reader.is_encrypted:
        if not args.password:
            print("Error: PDF is encrypted. Provide --password.", file=sys.stderr)
            sys.exit(3)
        try:
            ok = reader.decrypt(args.password)
            # pypdf returns 0 if failed, 1/2 if success
            if ok == 0:
                print("Error: Incorrect password.", file=sys.stderr)
                sys.exit(3)
        except Exception as e:
            print(f"Error decrypting PDF: {e}", file=sys.stderr)
            sys.exit(3)

    total = len(reader.pages)

    # Determine chunks
    chunks: List[Tuple[int, int]]
    mode = None
    if args.ranges:
        mode = "ranges"
        chunks = parse_ranges_spec(args.ranges, total)
    elif args.cuts:
        mode = "cuts"
        chunks = parse_cuts_spec(args.cuts, total)
    else:
        mode = "extract"
        chunks = parse_ranges_spec(args.extract, total)

    # Digits for numbering
    digits = args.digits or max(2, len(str(len(chunks))))

    # Write outputs
    total_written = 0
    if mode == "extract":
        # single combined file
        writer = PdfWriter()
        selection = []
        for (s, e) in chunks:
            selection.extend(range(s, e + 1))
        for p in tqdm(selection, desc="Writing extract", unit="page"):
            writer.add_page(reader.pages[p - 1])
        outpath = outdir / f"{args.prefix}extract.pdf"
        with outpath.open("wb") as f:
            writer.write(f)
        total_written = len(selection)
        print(f"Wrote {outpath} ({total_written} pages)")
    else:
        # multiple parts
        for i, (s, e) in enumerate(tqdm(chunks, desc="Writing parts", unit="part"), start=1):
            part_no = str(i).zfill(digits)
            outpath = outdir / f"{args.prefix}{part_no}_{str(s).zfill(len(str(total)))}-{str(e).zfill(len(str(total)))}.pdf"
            written = write_chunk(reader, s, e, outpath)
            total_written += written
            print(f"Wrote {outpath} ({written} pages)")

    print(f"Done. Total pages written: {total_written} (source had {total} pages)")


if __name__ == "__main__":
    main()
