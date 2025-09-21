#!/usr/bin/env python3
"""
pdf_to_ddc_json_pages_stream_cached_retry_dual_resumable.py

RESUMABLE FEATURES
- Per-page checkpoint files in --jsons_dir: <PDF_STEM>_p00001.json
- Skip pages that already have a valid checkpoint (unless --force)
- Atomic writes via .part → rename to avoid corruption on crash
- Lightweight manifest: <jsons>/<PDF_STEM>.resume.json (informational; not required to resume)
- Final merge rebuilt each run from selected pages' checkpoints

OTHER FEATURES (unchanged)
- Uses cached page images only (no re-render): <PDF_STEM>_p00001.png in --images_dir
- Streams Gemini responses per page (optional --stream)
- Enforces your short-key DDC schema (schema.json) + prompts.txt
- Continuation sentinel:
        If a page starts mid-entry, model must prepend:
            { "id":"__CONT__", "n":"__CONT__", "lbl":"", "note":["..."], "pg":<pg>, "src":{"file":"<img>"} }
        Program appends note[] to the LAST real concept from earlier pages, then discards the sentinel.
- Robust per-page retry on errors (JSON parse, empty reply, metadata mismatch)
- Provider: google-generativeai (Gemini) only. Vertex support removed for simplicity.
"""
from __future__ import annotations

import argparse, json, logging, os, re, sys, time, shutil, itertools
from pathlib import Path
from typing import List, Optional, Tuple, Any, Dict

from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, before_log, after_log, before_sleep_log
)
from tqdm import tqdm

from merge_utils import apply_continuation_if_any, apply_page_lead_if_any

# Optional: for page-count validation only (no rendering in this script)
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    from dotenv import load_dotenv  # optional
except Exception:
    load_dotenv = None

LOG = logging.getLogger("pdf_to_ddc_dual_resumable")

# --------------------------- logging ---------------------------
def setup_logging(verbose: bool, lvl: Optional[str]) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    if lvl: level = getattr(logging, lvl.upper(), level)
    logging.basicConfig(level=level, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", datefmt="%H:%M:%S")

# --------------------------- CLI utils ------------------------
def parse_pages_arg(pages_arg: str, total_pages: int) -> List[int]:
    if not pages_arg or pages_arg.strip().lower() == "all":
        return list(range(1, total_pages + 1))
    sel = set()
    for part in [x.strip() for x in pages_arg.split(",") if x.strip()]:
        if "-" in part:
            a, b = part.split("-", 1)
            start = max(1, int(a)); end = min(total_pages, int(b))
            if start <= end: sel.update(range(start, end + 1))
        else:
            n = int(part)
            if 1 <= n <= total_pages: sel.add(n)
    return sorted(sel)

def ensure_dirs(*dirs: Path) -> None:
    for d in dirs: d.mkdir(parents=True, exist_ok=True)

def json_strip_fences(text: str) -> str:
    t = (text or "").strip()
    if not t: return t
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[-1]
        if not (t.strip().startswith("{") or t.strip().startswith("[")):
            parts = t.split("```"); t = max(parts, key=len)
    return t

def parse_page_json(text: str) -> List[dict]:
    t = json_strip_fences(text)
    data = json.loads(t)
    if isinstance(data, dict): return [data]
    if not isinstance(data, list): raise ValueError("Model did not return a JSON array or object.")
    return data

def read_prompt(prompt_path: Path) -> str:
    if prompt_path.exists():
        t = prompt_path.read_text(encoding="utf-8").strip()
        LOG.debug("Loaded prompt (%d chars) from %s", len(t), prompt_path)
        return t
    # Fallback prompt aligned to the new schema (safe quoting)
    return (
        '''Convert this Dewey Decimal Schedule page (or pages) into JSON for a linked database.
Do not hallucinate. Use only visible text from the image(s). Preserve wording verbatim where practical.

OUTPUT CONTRACT (MANDATORY)
• Output ONLY a JSON ARRAY valid to the provided response_schema (no prose, no explanations, no code fences).
• Every object MUST include: id, type="Concept", notation, prefLabel.en, page, source.fileName.
• Maintain the top-to-bottom order of entries as they appear on the page.

ON-PAGE-ONLY RULE
• Emit ONLY concepts whose DDC notation is visibly printed on THIS page image (or images in this request).
• Do NOT infer siblings, parents, or children that are not printed on the page.

ID & NOTATION RULE
• For normal entries: set id EXACTLY equal to the notation string (e.g., "004.21"). No prefixes.
• For sentinels: use id="__CONT__"/"__PAGE__" and notation the same sentinel.

ONE TOP-OF-PAGE RULE (APPLIES TO EACH PAGE)
A) If the first printed content is a fresh DDC heading/notation (^(\\d{3})(?:\\.\\d+)*), DO NOT emit a sentinel.
B) Otherwise prepend EXACTLY ONE sentinel for THIS page:
   • Continuation from previous page (begins mid-sentence):
     {"id":"__CONT__","type":"Concept","notation":"__CONT__","prefLabel":{"en":""},
      "scope":{"notes":["<carry-over text from the very top of THIS page>"]},
      "page":<THIS_PAGE_NUMBER>,"source":{"fileName":"<THIS_IMAGE_FILE>","span":null}}
   • Page-level context (non-DDC header like SUMMARY/PREFACE/legends before first notation):
     {"id":"__PAGE__","type":"Concept","notation":"__PAGE__",
      "prefLabel":{"en":"<header text or 'PAGE_CONTEXT'>"},
      "scope":{"notes":["<verbatim lines from that block>"]},
      "page":<THIS_PAGE_NUMBER>,"source":{"fileName":"<THIS_IMAGE_FILE>","span":null}}

HEURISTICS FOR DDC HEADINGS
• Notations match ^\\d{3}(?:\\.\\d+)* (e.g., 003, 004.36, 621.381.3).
• If the first line begins mid-sentence or no notation precedes body text, treat as continuation (__CONT__).
• If a heading carries markers (*, †, ‡, etc.), copy their footnote text into scope.notes[].

FIELD MAPPING (STRICT, ON-PAGE ONLY)
• notation: printed DDC number (verbatim). id: same as notation (sentinels use __CONT__/__PAGE__).
• prefLabel.en: the printed heading line (verbatim).
• altLabel[]: variant names printed on the page.
• hierarchy fields: omit unless the parent/children are explicitly printed on THIS page.
• scope.classHere[]: lines starting with "Class here …"
• scope.including[]: lines starting with "Including …"
• scope.seeAlso[]: lines like "See also …" or "For …, see 001.4" → capture the target notation when present.
• scope.manualRefs[]: lines like "See Manual at …"
• scope.tableRefs[]: any line referring to "Table 1 …" / "Use notation 019 from Table 1 …" (also implies standardSubdivisions=true)
• scope.addToBaseRules[]: lines starting "Add to base …"
• scope.relocations[]: lines mentioning relocation
• scope.variantNameLabel[]: "Variant name: …"
• scope.notes[]: keep only residual notes not covered by the above rules.
• ranges[]: only visible on-page spans; shape {"from":"004.11","to":"004.16","label":"…"}.
• examples[]: explicit examples printed for that entry.
• page: THIS page number (integer). source.fileName: THIS image's filename (exact).
• skos.inScheme: "DDC23" (topConceptOf only if explicitly shown on the page).

MULTI-PAGE CALLS
• Return a SINGLE JSON ARRAY covering ALL attached pages; each object must carry its correct page and source.fileName.
• Apply the TOP-OF-PAGE sentinel rule per page independently.
'''
    )


# -------------------- provider adapters -----------------------
class ProviderAdapter:
    def __init__(self, name: str):
        self.name = name  # 'studio'
        self.model = None
    def init(self, **kwargs): ...
    def build_model(self, model_name: str, schema: Optional[dict], max_output_tokens: int): ...
    def make_file_part(self, path: Path) -> Any: ...
    def generate_stream_or_text(self, msgs: list, stream: bool) -> str: ...

class StudioAdapter(ProviderAdapter):
    def __init__(self):
        super().__init__("studio")
        self.genai = None
    def init(self, api_key: str, **kwargs):
        import google.generativeai as genai
        self.genai = genai
        genai.configure(api_key=api_key)
    def reconfigure(self, api_key: str):
        """Reconfigure underlying client with a new API key (for rotation)."""
        if self.genai is None:
            import google.generativeai as genai
            self.genai = genai
        self.genai.configure(api_key=api_key)
    def build_model(self, model_name: str, schema: Optional[dict], max_output_tokens: int):
        cfg = {
            "response_mime_type": "application/json",
            "temperature": 0, "top_p": 0, "top_k": 1, "candidate_count": 1,
            "max_output_tokens": max_output_tokens,
        }
        if schema: cfg["response_schema"] = schema
        import google.generativeai as genai
        self.model = genai.GenerativeModel(model_name=model_name, generation_config=cfg, system_instruction=None)
    @retry(reraise=True, stop=stop_after_attempt(5),
           wait=wait_exponential(multiplier=1, min=1, max=16),
           retry=retry_if_exception_type(Exception),
           before=before_log(LOG, logging.DEBUG), after=after_log(LOG, logging.DEBUG),
           before_sleep=before_sleep_log(LOG, logging.WARNING))
    def make_file_part(self, path: Path):
        return self.genai.upload_file(path=path.as_posix())
    def generate_stream_or_text(self, msgs: list, stream: bool) -> str:
        if stream:
            acc: List[str] = []
            s = self.model.generate_content(msgs, stream=True, request_options={"timeout": 600})
            for ch in s:
                delta = getattr(ch, "text", "") or ""
                if delta:
                    acc.append(delta); sys.stdout.write(delta); sys.stdout.flush()
            return "".join(acc)
        else:
            resp = self.model.generate_content(msgs, request_options={"timeout": 600})
            return getattr(resp, "text", "") or ""

"""Vertex adapter removed."""

# -------------------- robust API key load (Studio) -------------
def load_api_key(cli_key: Optional[str]) -> str:
    if load_dotenv:
        try: load_dotenv()
        except Exception: pass
    api_key = cli_key or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        key_file = Path("key.txt")
        if key_file.exists():
            api_key = key_file.read_text(encoding="utf-8").strip()
    if not api_key:
        LOG.critical("Missing API key. Provide via --api_key, env GOOGLE_API_KEY, .env, or key.txt")
        raise SystemExit(1)
    return api_key

def load_api_key_pool(primary: Optional[str]) -> List[str]:
    """Load a pool of API keys for failover rotation.

    Sources (in order):
      1. --api_key (single explicit) -> returned alone if provided
      2. apikey.txt (one key per line, blank/comment lines ignored)
      3. GOOGLE_API_KEY env / key.txt fallback (if apikey.txt absent)
    Duplicates removed preserving order.
    """
    if primary:
        return [primary.strip()]
    keys: List[str] = []
    pool_file = Path("apikey.txt")
    if pool_file.exists():
        for line in pool_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith('#'): continue
            keys.append(line)
    if not keys:
        # fallback to single key logic
        single = load_api_key(None)
        keys.append(single)
    # de-dupe preserving order
    dedup = []
    seen = set()
    for k in keys:
        if k and k not in seen:
            dedup.append(k); seen.add(k)
    return dedup

# -------------------- cached images ---------------------------
def build_expected_name(pdf_stem: str, page_number: int) -> str:
    return f"{pdf_stem}_p{page_number:05d}.png"

def collect_cached_images(pdf_stem: str, images_dir: Path, pages: List[int], strict_cache: bool) -> List[Path]:
    imgs: List[Path] = []
    missing: List[int] = []
    for pg in pages:
        p = images_dir / build_expected_name(pdf_stem, pg)
        if p.exists(): imgs.append(p)
        else:
            missing.append(pg); imgs.append(p)
    if missing and strict_cache:
        miss_list = ", ".join(str(x) for x in missing)
        raise SystemExit(
            f"[ERROR] Missing cached images for pages: {miss_list}\n"
            f"Expected under: {images_dir}\n"
            f"Pattern: {pdf_stem}_p00001.png"
        )
    return imgs

# -------------------- generation core -------------------------
REQUIRED_KEYS = {"id", "type", "notation", "prefLabel", "page", "source"}

def validate_page_objects(objs: List[dict], page_number: int, img_name: str) -> Tuple[bool, List[str]]:
    errs: List[str] = []
    if not isinstance(objs, list):
        return False, ["Top-level JSON must be an array."]
    for i, o in enumerate(objs):
        if not isinstance(o, dict):
            errs.append(f"[{i}] not an object"); continue

        missing = REQUIRED_KEYS - set(o.keys())
        if missing:
            errs.append(f"[{i}] missing keys: {sorted(missing)}")

        # type
        if o.get("type") != "Concept":
            errs.append(f"[{i}] type must be 'Concept', got {o.get('type')}")

        # prefLabel.en
        pl = o.get("prefLabel")
        if not (isinstance(pl, dict) and isinstance(pl.get("en"), str)):
            errs.append(f"[{i}] prefLabel.en missing or not a string")

        # page
        pg = o.get("page")
        if not isinstance(pg, int) or pg != page_number:
            errs.append(f"[{i}] bad page: {pg} (expected {page_number})")

        # source.fileName
        src = o.get("source")
        if not (isinstance(src, dict) and src.get("fileName") == img_name):
            got = src.get("fileName") if isinstance(src, dict) else None
            errs.append(f"[{i}] bad source.fileName: {got} (expected {img_name})")

    return (len(errs) == 0), errs

def split_objects_by_page(objs: List[dict]) -> Dict[int, List[dict]]:
    """Group objects by their 'page' integer."""
    by_pg: Dict[int, List[dict]] = {}
    for o in objs:
        if not isinstance(o, dict):
            continue
        pg_val = o.get("page")
        if isinstance(pg_val, int):
            by_pg.setdefault(pg_val, []).append(o)
        else:
            LOG.debug("Discard object lacking valid page: %s", o)
    return by_pg

def _strip_hierarchy(page_objs: List[dict]) -> List[dict]:
    """Remove optional 'hierarchy' field from each concept object, in-place safe."""
    for o in page_objs:
        if isinstance(o, dict):
            o.pop("hierarchy", None)
    return page_objs

def route_scope_fields(objs: List[dict]) -> List[dict]:
    """Move well-known lines from scope.notes[] into specific fields."""
    import re
    
    # Simple phrase/regex-based router from scope.notes[] -> structured fields
    ROUTE_PATTERNS = [
        # ("target_field", compiled_regex, strip_prefix_in_capture?)
        ("classHere", re.compile(r"^\s*class here[:\s-]*(.*)$", re.I), True),
        ("including", re.compile(r"^\s*including[:\s-]*(.*)$", re.I), True),
        ("seeAlso",  re.compile(r"^\s*(?:for .*?,\s*)?see\s+([0-9][0-9][0-9](?:\.[0-9]+)?)\s*\.?\s*$", re.I), False),
        ("seeAlso",  re.compile(r"^\s*see also[:\s-]*(.*)$", re.I), True),
        ("manualRefs", re.compile(r"^\s*see manual at[:\s-]*(.*)$", re.I), True),
        ("tableRefs",  re.compile(r".*\btable\s+1\b.*", re.I), False),
        ("addToBaseRules", re.compile(r"^\s*add to base .*", re.I), False),
        ("relocations",   re.compile(r".*\brelocat(?:ed|ion)\b.*", re.I), False),
        ("variantNameLabel", re.compile(r"^\s*variant name[:\s-]*(.*)$", re.I), True),
    ]
    
    for o in objs:
        if not isinstance(o, dict):
            continue
        sc = o.get("scope")
        if not isinstance(sc, dict):
            continue

        notes = sc.get("notes")
        if not isinstance(notes, list) or not notes:
            continue

        remaining: List[str] = []
        # ensure target arrays exist when first needed
        def _push(key: str, val: str):
            arr = sc.get(key)
            if not isinstance(arr, list):
                sc[key] = arr = []
            if val and val not in arr:
                arr.append(val)

        std_subdiv = False

        for line in notes:
            if not isinstance(line, str):
                continue
            raw = line.strip()
            low = raw.lower()

            # quick signals for standard subdivisions
            if "standard subdivisions" in low or "use notation 019 from table 1" in low:
                std_subdiv = True

            routed = False
            for target, pat, capture_after in ROUTE_PATTERNS:
                m = pat.match(raw)
                if m:
                    if target in ("tableRefs", "addToBaseRules", "relocations"):
                        _push(target, raw)  # keep full line for these
                    elif target == "seeAlso" and m.lastindex:
                        _push(target, m.group(1).strip())
                    elif m.lastindex and capture_after:
                        _push(target, m.group(1).strip())
                    else:
                        _push(target, raw)
                    routed = True
                    break

            if not routed:
                remaining.append(raw)

        # write back remaining notes
        if remaining:
            sc["notes"] = remaining
        else:
            # drop empty notes array
            sc.pop("notes", None)

        # set boolean only if explicitly indicated
        if std_subdiv:
            sc["standardSubdivisions"] = True

    return objs

def stream_or_generate_json(adapter, prompt: str, img_path: Path, page_number: int, stream: bool, show_prompt: bool=False) -> str:
    page_hint = (
        f"\nPage context:\n"
        f" - page (page number) to set: {page_number}\n"
        f" - source.fileName (image file name): {img_path.name}\n"
        f"Ensure every object includes page and source.fileName accordingly.\n"
    )
    full_prompt = prompt + page_hint
    if show_prompt:
        LOG.info("\n===== PROMPT (page %d) =====\n%s\n============================", page_number, full_prompt)
    file_part = adapter.make_file_part(img_path)
    msgs = [{"role": "user", "parts": [{"text": full_prompt}, file_part]}]
    if stream:
        sys.stdout.write(f"\n--- streaming page {page_number} ---\n"); sys.stdout.flush()
    text = adapter.generate_stream_or_text(msgs, stream=stream)
    if stream:
        sys.stdout.write("\n--- end stream ---\n"); sys.stdout.flush()
    return text

def stream_or_generate_json_dual(adapter, prompt: str, img_path1: Path, page_number1: int, img_path2: Path, page_number2: int, stream: bool, show_prompt: bool=False) -> str:
    """Send TWO consecutive page images in one request.

    The prompt is augmented with explicit instructions that BOTH pages are provided and all
    objects must carry the correct pg and src.file referencing one of the two images.
    Model must still return a single JSON array (or object) which we will parse then split
    by page number.
    """
    page_hint = (
        f"\nPages context (dual call):\n"
        f" - Page A: page={page_number1}, source.fileName={img_path1.name}\n"
        f" - Page B: page={page_number2}, source.fileName={img_path2.name}\n"
        f"Return a SINGLE JSON array for BOTH pages. Each object MUST set the correct page and source.fileName. If page B begins with a continuation, still emit the continuation sentinel first for that page.\n"
    )
    full_prompt = prompt + page_hint
    if show_prompt:
        LOG.info("\n===== PROMPT (pages %d+%d) =====\n%s\n================================", page_number1, page_number2, full_prompt)
    file_part1 = adapter.make_file_part(img_path1)
    file_part2 = adapter.make_file_part(img_path2)
    msgs = [{"role": "user", "parts": [{"text": full_prompt}, file_part1, file_part2]}]
    if stream:
        sys.stdout.write(f"\n--- streaming pages {page_number1}+{page_number2} ---\n"); sys.stdout.flush()
    text = adapter.generate_stream_or_text(msgs, stream=stream)
    if stream:
        sys.stdout.write("\n--- end stream ---\n"); sys.stdout.flush()
    return text

# -------------------- checkpointing / resume -------------------
def page_json_path(jsons_dir: Path, pdf_stem: str, page_number: int) -> Path:
    return jsons_dir / f"{pdf_stem}_p{page_number:05d}.json"

def write_atomic_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".part")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic on POSIX; safe on Windows if same volume

def try_load_existing_page(path: Path) -> Optional[List[dict]]:
    if not path.exists(): return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict): data = [data]
        if not isinstance(data, list): return None
        return data
    except Exception:
        return None

def existing_is_valid_for_page(data: List[dict], page_number: int, img_name: str) -> bool:
    ok, errs = validate_page_objects(data, page_number, img_name)
    if not ok:
        LOG.debug("Existing checkpoint invalid for p%d: %s", page_number, " | ".join(errs[:4]))
    return ok

def load_manifest(manifest_path: Path) -> Dict[str, Any]:
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"processed_pages": [], "updated_at": None}

def save_manifest(manifest_path: Path, processed_pages: List[int]) -> None:
    write_atomic_json(manifest_path, {"processed_pages": processed_pages, "updated_at": int(time.time())})

# --------------------------- main -----------------------------
def main():
    ap = argparse.ArgumentParser(description="Cached images → Gemini (Gemini Studio API) with streaming, continuation, retries — RESUMABLE.")
    # Common
    ap.add_argument("--pdf_path", type=Path, required=True)
    ap.add_argument("--pages", type=str, default="all", help='Pages: "all" or "1-5,7,10-13" (1-based).')
    ap.add_argument("--images_dir", type=Path, default=Path("./images"))
    ap.add_argument("--jsons_dir", type=Path, default=Path("./jsons"))
    ap.add_argument("--final_path", type=Path, default=Path("./final.json"))
    ap.add_argument("--manifest_path", type=Path, default=None, help="Optional explicit path; default is <jsons>/<PDF_STEM>.resume.json")
    ap.add_argument("--prompt_path", type=Path, default=Path("./prompts.txt"))
    ap.add_argument("--schema_path", type=Path, default=None)
    ap.add_argument("--model", type=str, default="gemini-2.0-pro-exp")
    ap.add_argument("--max_output_tokens", type=int, default=32768)
    ap.add_argument("--max_attempts", type=int, default=4)
    ap.add_argument("--retry_backoff", type=float, default=2.0)
    ap.add_argument("--stream", action="store_true")
    ap.add_argument("--pages_per_call", type=int, choices=[1,2], default=1, help="Process 1 page per model call (default) or 2 consecutive pages together.")
    ap.add_argument("--show_prompt", action="store_true", help="Print the full prompt (including page hints) before each call.")
    ap.add_argument("--save_raw", action="store_true", help="Save raw model output text beside checkpoints as *.raw.txt for inspection.")
    ap.add_argument("--page_leads", action="store_true",
                    help="Capture ANY non-DDC top-of-page block via __PAGE__ sentinel into a sidecar file.")
    ap.add_argument("--force", action="store_true", help="Reprocess pages even if a valid checkpoint exists.")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--log_level", type=str, default=None)
    ap.add_argument("--strict_cache", action="store_true", default=True)
    # Studio-only
    ap.add_argument("--api_key", type=str, default=None)
    # (Vertex options removed)
    args = ap.parse_args()

    setup_logging(args.verbose, args.log_level)

    # Provider init (studio only)
    if load_dotenv:
        try: load_dotenv()
        except Exception: pass
    # API key rotation pool
    api_keys = load_api_key_pool(args.api_key)
    if not api_keys:
        LOG.critical("No API keys available.")
        raise SystemExit(1)
    adapter: ProviderAdapter = StudioAdapter()
    active_key_index = 0
    adapter.init(api_key=api_keys[active_key_index])
    LOG.info("Using API key #1/%d", len(api_keys))

    # Schema
    schema = None
    if args.schema_path and Path(args.schema_path).exists():
        try:
            schema = json.loads(Path(args.schema_path).read_text(encoding="utf-8"))
            LOG.info("Loaded schema from %s", args.schema_path)
        except Exception as e:
            LOG.warning("Failed to load schema (%s). Proceeding without response_schema.", e)

    # Build model
    adapter.build_model(args.model, schema, args.max_output_tokens)

    # Page selection (PDF only for page count)
    if not args.pdf_path.exists(): raise SystemExit(f"PDF not found: {args.pdf_path}")
    total = 9_999_999
    if fitz:
        try:
            with fitz.open(args.pdf_path) as doc:
                total = doc.page_count
        except Exception:
            LOG.warning("Could not read page count from PDF; skipping strict validation.")
    pages = parse_pages_arg(args.pages, total)
    if not pages:
        LOG.warning("No pages selected."); return

    # Paths
    ensure_dirs(args.images_dir, args.jsons_dir)
    pdf_stem = args.pdf_path.stem
    manifest_path = args.manifest_path or (args.jsons_dir / f"{pdf_stem}.resume.json")

    # Cached images
    img_paths = collect_cached_images(pdf_stem, args.images_dir, pages, strict_cache=args.strict_cache)

    # Prompt
    prompt = read_prompt(args.prompt_path)

    # Resume state
    manifest = load_manifest(manifest_path)
    processed_pages: List[int] = list(manifest.get("processed_pages") or [])

    merged: List[dict] = []

    # First, if resuming, preload previously processed pages into 'merged' in order
    for pg, img_path in zip(pages, img_paths):
        chk = page_json_path(args.jsons_dir, pdf_stem, pg)
        if chk.exists():
            existing = try_load_existing_page(chk)
            if existing and existing_is_valid_for_page(existing, pg, img_path.name):
                # Continuation sentinel should already be resolved in saved file,
                # so just extend merged.
                merged.extend(existing)
                if pg not in processed_pages:
                    processed_pages.append(pg)

    # Now run over pages; skip if valid checkpoint unless --force.
    # If pages_per_call == 2 we advance in steps of 2 combining consecutive pages.
    i = 0
    # Storage for captured page lead sentinels (if enabled)
    page_leads: Dict[int, dict] = {}

    while i < len(pages):
        pg1 = pages[i]
        img1 = img_paths[i]
        pg2 = None; img2 = None
        dual = (args.pages_per_call == 2 and i + 1 < len(pages))
        if dual:
            pg2 = pages[i+1]
            img2 = img_paths[i+1]

        # Helper to check single page skip condition
        def checkpoint_valid(pg, img_path):
            chk = page_json_path(args.jsons_dir, pdf_stem, pg)
            existing = try_load_existing_page(chk)
            return existing and existing_is_valid_for_page(existing, pg, img_path.name)

        if dual:
            # If BOTH pages already valid and not forcing, skip both
            if (not args.force) and checkpoint_valid(pg1, img1) and checkpoint_valid(pg2, img2):
                LOG.info("Skip pages %d & %d (valid checkpoints).", pg1, pg2)
                i += 2
                continue
        else:
            if (not args.force) and checkpoint_valid(pg1, img1):
                LOG.info("Skip p%d (valid checkpoint).", pg1)
                i += 1
                continue

        attempt = 0
        success = False
        last_err = None
        while attempt < args.max_attempts and not success:
            attempt += 1
            try:
                if dual:
                    LOG.info("[STUDIO] Pages %d+%d attempt %d/%d", pg1, pg2, attempt, args.max_attempts)
                    raw = stream_or_generate_json_dual(adapter, prompt, img1, pg1, img2, pg2, stream=args.stream, show_prompt=args.show_prompt)
                else:
                    LOG.info("[STUDIO] Page %d attempt %d/%d", pg1, attempt, args.max_attempts)
                    raw = stream_or_generate_json(adapter, prompt, img1, pg1, stream=args.stream, show_prompt=args.show_prompt)
                if not raw.strip():
                    raise ValueError("Empty response from model")

                objs = parse_page_json(raw)
                by_pg = split_objects_by_page(objs)

                # Build batch list for unified handling
                batch = [(img1, pg1)] + ([(img2, pg2)] if dual else [])
                ordered_objs: List[dict] = []

                for img_path, pg in batch:
                    page_objs = by_pg.get(pg, [])
                    # (a) capture + remove page-lead sentinel (sidecar)
                    if args.page_leads:
                        page_objs = apply_page_lead_if_any(page_objs, pg, img_path.name, page_leads)
                    # (b) continuation sentinel merge & drop
                    page_objs = apply_continuation_if_any(page_objs, merged)

                    # NEW: route well-known lines from notes -> structured scope fields
                    page_objs = route_scope_fields(page_objs)

                    # Optional hierarchy stripping before validation
                    page_objs = _strip_hierarchy(page_objs)
                    ok_pg, errs_pg = validate_page_objects(page_objs, pg, img_path.name)
                    if not ok_pg and page_objs:
                        raise ValueError(f"Per-page validation failed for p{pg}: " + " | ".join(errs_pg[:6]))

                    chk_path = page_json_path(args.jsons_dir, pdf_stem, pg)
                    if args.save_raw and pg == pg1:  # save once per call
                        raw_path = chk_path.with_suffix('.raw.txt') if not dual else (chk_path.parent / f"{pdf_stem}_p{pg1:05d}_p{(pg2 or pg1):05d}.raw.txt")
                        try:
                            raw_path.write_text(raw, encoding='utf-8')
                        except Exception as e:
                            LOG.warning("Could not write raw output file: %s", e)
                    write_atomic_json(chk_path, page_objs)
                    if pg not in processed_pages:
                        processed_pages.append(pg)
                    merged.extend(page_objs)
                    ordered_objs.extend(page_objs)
                    LOG.info("Page %d → %d object(s) [checkpoint saved]", pg, len(page_objs))

                save_manifest(manifest_path, processed_pages)
                success = True
            except Exception as e:
                last_err = e
                # Detect auth/quota style errors to trigger key rotation
                err_txt = str(e).lower()
                rotate = any(tok in err_txt for tok in ["permission", "quota", "unauthorized", "apikey", "api key", "403", "429"])
                if rotate and len(api_keys) > 1:
                    old_idx = active_key_index
                    active_key_index = (active_key_index + 1) % len(api_keys)
                    if active_key_index != old_idx:
                        new_key = api_keys[active_key_index]
                        try:
                            adapter.reconfigure(new_key)
                            adapter.build_model(args.model, schema, args.max_output_tokens)
                            LOG.warning("Rotated API key -> #%d/%d (trigger: %s)", active_key_index+1, len(api_keys), err_txt[:80])
                        except Exception as recfg_err:
                            LOG.error("Failed reconfiguring with rotated key: %s", recfg_err)
                if dual:
                    LOG.warning("Pages %d+%d error attempt %d: %s", pg1, pg2, attempt, e)
                else:
                    LOG.warning("Page %d error attempt %d: %s", pg1, attempt, e)
                if attempt < args.max_attempts:
                    sleep_s = args.retry_backoff * (2 ** (attempt - 1))
                    if dual:
                        LOG.info("Retrying pages %d+%d after %.1fs …", pg1, pg2, sleep_s)
                    else:
                        LOG.info("Retrying page %d after %.1fs …", pg1, sleep_s)
                    time.sleep(sleep_s)
        if not success:
            if dual:
                LOG.error("FAILED pages %d+%d after %d attempts. Leaving for resume.", pg1, pg2, args.max_attempts)
            else:
                LOG.error("FAILED page %d after %d attempts. Leaving for resume.", pg1, args.max_attempts)
        i += 2 if dual else 1

    # Final write (always rebuilt from 'merged' accumulated during this run)
    write_atomic_json(args.final_path, merged)
    LOG.info("FINAL total: %d object(s) → %s", len(merged), args.final_path)
    LOG.info("Processed pages this run or previously: %s", processed_pages)

    # Sidecar for page-leads (if any captured)
    if args.page_leads and page_leads:
        lead_path = args.jsons_dir / f"{pdf_stem}.page_leads.json"
        try:
            write_atomic_json(lead_path, [page_leads[k] for k in sorted(page_leads.keys())])
            LOG.info("PAGE LEADS: %d page(s) → %s", len(page_leads), lead_path)
        except Exception as e:
            LOG.warning("Failed writing page-leads sidecar: %s", e)

if __name__ == "__main__":
    setup_logging(False, None)  # safe default if imported
    main()
