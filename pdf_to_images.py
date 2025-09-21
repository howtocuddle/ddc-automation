#!/usr/bin/env python3
"""
pdf_to_images.py
----------------
Convert every page of a PDF into image files and save them into a new (or specified) folder.

Dependencies (install via pip):
    pip install pymupdf tqdm

Why PyMuPDF?
- No external system dependency (unlike pdf2image which needs Poppler).
- Fast and reliable rendering.

Usage:
    python pdf_to_images.py input.pdf
    python pdf_to_images.py input.pdf --outdir ./images_out --prefix page_ --dpi 200 --fmt png
    python pdf_to_images.py input.pdf --password "secret" --start 1 --end 10

Notes:
- --dpi controls rendering resolution (~72 dpi is PDF default). 200–300 is crisp for OCR.
- Output filenames follow: {prefix}{page_num}.{fmt}, 1-based page numbers.
"""

import argparse
import sys
from pathlib import Path
import fitz  # PyMuPDF
from tqdm import tqdm

def convert_pdf_to_images(
    pdf_path: Path,
    outdir: Path = None,
    dpi: int = 200,
    fmt: str = "png",
    prefix: str = "page_",
    password: str = None,
    start: int = None,
    end: int = None,
) -> int:
    """
    Render pages of a PDF to images.

    Returns number of pages exported.
    """
    if outdir is None:
        outdir = pdf_path.with_suffix("")  # e.g., input.pdf -> input/
    outdir.mkdir(parents=True, exist_ok=True)

    if fmt.lower() not in {"png", "jpg", "jpeg", "tiff", "tif"}:
        raise ValueError("fmt must be one of: png, jpg, jpeg, tiff, tif")

    # Open PDF
    doc = fitz.open(pdf_path)

    # Decrypt if needed
    if doc.needs_pass:
        if not password:
            raise ValueError("PDF is encrypted. Provide --password to open it.")
        if not doc.authenticate(password):
            raise ValueError("Incorrect password for encrypted PDF.")

    # Clamp page range
    total_pages = doc.page_count
    first = 1 if start is None else max(1, start)
    last = total_pages if end is None else min(total_pages, end)
    if first > last:
        raise ValueError(f"Invalid range: start={first}, end={last}, total_pages={total_pages}")

    # Compute zoom matrix from dpi
    # 72 dpi is the PDF default; scale accordingly
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    exported = 0
    for pno in tqdm(range(first, last + 1), desc="Rendering pages", unit="page"):
        page = doc[pno - 1]  # 0-based index
        pix = page.get_pixmap(matrix=mat)  # render
        # Normalize format / extension
        ext = "jpg" if fmt.lower() == "jpeg" else fmt.lower()
        outpath = outdir / f"{prefix}{pno}.{ext}"
        if ext in {"jpg", "jpeg"}:
            # Use JPEG quality if available (PyMuPDF uses 'jpg' option)
            pix.save(outpath, jpg_quality=95)
        else:
            pix.save(outpath)
        exported += 1

    doc.close()
    return exported


def main():
    parser = argparse.ArgumentParser(description="Convert PDF pages to images (one image per page).")
    parser.add_argument("pdf", type=Path, help="Path to input PDF")
    parser.add_argument("--outdir", type=Path, default=None, help="Output folder (default: <pdf_basename>/)")
    parser.add_argument("--dpi", type=int, default=200, help="Output DPI (default: 200)")
    parser.add_argument("--fmt", type=str, default="png", help="Image format: png | jpg | jpeg | tiff | tif (default: png)")
    parser.add_argument("--prefix", type=str, default="page_", help="Filename prefix (default: page_)")
    parser.add_argument("--password", type=str, default=None, help="Password for encrypted PDFs")
    parser.add_argument("--start", type=int, default=None, help="Start page (1-based, inclusive)")
    parser.add_argument("--end", type=int, default=None, help="End page (1-based, inclusive)")

    args = parser.parse_args()

    pdf_path = args.pdf
    if not pdf_path.exists():
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    try:
        count = convert_pdf_to_images(
            pdf_path=pdf_path,
            outdir=args.outdir,
            dpi=args.dpi,
            fmt=args.fmt,
            prefix=args.prefix,
            password=args.password,
            start=args.start,
            end=args.end,
        )
        print(f"Done. Exported {count} page(s) to {args.outdir or pdf_path.with_suffix('')}")
    except Exception as e:
        print(f"Failed: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
