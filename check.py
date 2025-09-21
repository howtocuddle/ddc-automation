#!/usr/bin/env python3
"""
Check for missing files named like: 2_p00017.json ... 2_p01305.json

Defaults:
  folder = current directory
  start  = 17
  end    = 1305
  prefix = "2_p"
  width  = 5    (zero-padded)
  ext    = ".json"

Usage:
  python check_missing.py --dir /path/to/folder
  # optional tweaks:
  # python check_missing.py --start 1 --end 500 --prefix 2_p --width 5 --ext .json
"""
from pathlib import Path
import argparse
from itertools import groupby

def compress_ranges(nums):
    """Return compact ranges like [(17,20), (27,27)] from a sorted list."""
    if not nums:
        return []
    ranges = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
        else:
            ranges.append((start, prev))
            start = prev = n
    ranges.append((start, prev))
    return ranges

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".", help="Folder containing the files")
    ap.add_argument("--start", type=int, default=17)
    ap.add_argument("--end", type=int, default=1305)
    ap.add_argument("--prefix", default="2_p")
    ap.add_argument("--width", type=int, default=5)
    ap.add_argument("--ext", default=".json")
    args = ap.parse_args()

    folder = Path(args.dir)

    # Build expected set
    expected_idxs = list(range(args.start, args.end + 1))
    expected_names = {f"{args.prefix}{i:0{args.width}d}{args.ext}" for i in expected_idxs}

    # Scan existing following the pattern strictly
    existing = set()
    existing_idxs = set()
    for p in folder.iterdir():
        if not p.is_file():
            continue
        name = p.name
        if not (name.startswith(args.prefix) and name.endswith(args.ext)):
            continue
        core = name[len(args.prefix):-len(args.ext)]
        if len(core) == args.width and core.isdigit():
            idx = int(core)
            existing.add(name)
            existing_idxs.add(idx)

    missing_idxs = sorted(set(expected_idxs) - existing_idxs)
    extra_names = sorted(existing - expected_names)

    # Report
    print(f"Checked folder: {folder.resolve()}")
    print(f"Pattern: {args.prefix}{'0'*args.width}{args.ext} | Range: {args.start}..{args.end}")
    print(f"Expected files: {len(expected_idxs)}")
    print(f"Found matching files: {len(existing_idxs)}")

    if not missing_idxs:
        print("✅ No files missing.")
    else:
        print(f"❌ Missing count: {len(missing_idxs)}")
        # Compact range summary
        ranges = compress_ranges(missing_idxs)
        range_str = ", ".join(f"{a}" if a==b else f"{a}-{b}" for a,b in ranges)
        print(f"Missing index ranges: {range_str}")
        # List concrete filenames
        print("Missing filenames:")
        for i in missing_idxs:
            print(f"  {args.prefix}{i:0{args.width}d}{args.ext}")

    if extra_names:
        print("\n(Info) Extra files that match the shape but are outside expected range or name set:")
        for n in extra_names:
            print(f"  {n}")

if __name__ == "__main__":
    main()
