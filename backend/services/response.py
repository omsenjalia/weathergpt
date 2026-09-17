"""Output gate for LLM responses.

Guarantees that web and mobile clients only ever receive the final answer
plus valid widget blocks.

- extract_widgets / strip_widgets use the fence pattern ```widget:<name>\\n…```
- sanitize_response removes <think> etc blocks, strips leading reasoning
  preambles, validates widget JSON, merges required_widgets (authoritative),
  and returns prose + widgets at the end.
"""

from __future__ import annotations

import json
import re
from typing import List, Tuple, Optional

# ---------------------------------------------------------------------------
# Widget helpers
# ---------------------------------------------------------------------------

# ```widget:<name>\n JSON \n```
# Allow optional spaces before/after, capture type and inner content non-greedily.
WIDGET_RE = re.compile(r"```widget:([A-Za-z0-9_-]+)\s*\n(.*?)\s*```", re.DOTALL)

# Think-like tags to strip
THINK_TAGS = ("think", "thinking", "reasoning", "analysis", "scratchpad")
# Paired: <tag ...> ... </tag>
_THINK_PAIRED_RE = re.compile(
    r"<\s*(think|thinking|reasoning|analysis|scratchpad)(?:\s[^>]*)?>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
# Unpaired opening tag
_THINK_OPEN_RE = re.compile(
    r"<\s*(think|thinking|reasoning|analysis|scratchpad)(?:\s[^>]*)?>",
    re.IGNORECASE,
)

# Heading / HR detection
_HEADING_RE = re.compile(r"(?m)^\s*#{1,6}\s+.+$")
_HR_RE = re.compile(r"(?m)^\s*(?:---|\*\*\*|___)\s*$")
# Answer heading: optionally # and **, then answer|response|final answer
_ANSWER_HEADING_RE = re.compile(
    r"(?m)^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(?:final\s+answer|answer|response)\b[^\n]*:?\s*(?:\*\*)?\s*$",
    re.IGNORECASE,
)


def _normalize_heading_line(line: str) -> str:
    """Strip markdown markers for heading classification."""
    s = line.strip()
    # Remove leading #s
    s = re.sub(r"^\s*#{1,6}\s*", "", s)
    s = s.strip()
    # Strip surrounding ** or __ if present
    # Handle **foo** , **foo, foo**, etc.
    # Remove leading ** / __
    s = re.sub(r"^\*\*\s*", "", s)
    s = re.sub(r"\s*\*\*$", "", s)
    s = re.sub(r"^__\s*", "", s)
    s = re.sub(r"\s*__$", "", s)
    # Also strip single leading/trailing * that may remain from **Thinking:** -> Thinking:
    s = s.strip("*").strip()
    s = s.strip()
    return s


def _is_reasoning_heading(line: str) -> bool:
    norm = _normalize_heading_line(line)
    if not norm:
        return False
    low = norm.lower().rstrip(":").strip()
    # Patterns that indicate a reasoning preamble
    patterns = [
        r"^reasoning\b",
        r"^thinking\b",
        r"^thought process\b",
        r"^thought\b",
        r"^my approach\b",
        r"^my reasoning\b",
        r"^let me think\b",
        r"^first,?\s*i\b",  # First, I'll...
        r"^analysis\b",
        r"^scratchpad\b",
        r"^chain of thought\b",
        r"^step by step\b",
        r"^approach\b",
        r"^planning\b",
        r"^reasoning &",
        r"^reasoning and",
    ]
    for pat in patterns:
        if re.match(pat, low):
            return True
    return False


def _is_answer_heading(line: str) -> bool:
    norm = _normalize_heading_line(line)
    if not norm:
        return False
    low = norm.lower().rstrip(":").strip()
    return bool(re.match(r"^(?:final\s+answer|answer|response)\b", low))


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def extract_widgets(text: str) -> List[Tuple[str, str]]:
    """Return list of (type, json_str) found in text."""
    if not text:
        return []
    results: List[Tuple[str, str]] = []
    for m in WIDGET_RE.finditer(text):
        w_type = m.group(1).strip()
        j_str = m.group(2).strip()
        results.append((w_type, j_str))
    return results


def strip_widgets(text: str) -> str:
    """Return text with all widget fences removed."""
    if not text:
        return ""
    return WIDGET_RE.sub("", text)


def _strip_think_blocks(text: str) -> str:
    """Remove <think> etc paired blocks and handle unterminated opening tags."""
    if not text:
        return text

    # 1. Remove paired blocks
    text = _THINK_PAIRED_RE.sub("", text)

    # 2. Handle unterminated opening tags: cut to first heading or widget block
    # Loop because there could be multiple
    while True:
        m = _THINK_OPEN_RE.search(text)
        if not m:
            break
        start = m.start()
        # Look ahead for next heading or widget block
        substr = text[m.end() :]

        # Find next markdown heading
        hm = _HEADING_RE.search(substr)
        wm = WIDGET_RE.search(substr)
        # Also consider widget marker plain ```widget:
        # WIDGET_RE already covers it; but also search for literal
        # Use earliest occurrence
        candidates = []
        if hm:
            candidates.append(("heading", hm.start()))
        if wm:
            candidates.append(("widget", wm.start()))

        if candidates:
            # earliest
            candidates.sort(key=lambda x: x[1])
            earliest_pos = candidates[0][1]
            cut_to = m.end() + earliest_pos
            text = text[:start] + text[cut_to:]
        else:
            # No boundary -> drop from opening tag to end
            text = text[:start]
            break

    return text


def _strip_reasoning_preamble(text: str) -> str:
    """If first non-empty line is a reasoning heading, cut to real answer."""
    if not text:
        return text

    lines = text.splitlines()
    first_idx = None
    first_line = None
    for i, line in enumerate(lines):
        if line.strip():
            first_idx = i
            first_line = line
            break

    if first_idx is None or first_line is None:
        return text

    if not _is_reasoning_heading(first_line):
        return text

    # Build list of lines with their start offsets in original text to preserve original formatting
    # For simplicity, reconstruct remaining text after first line using original text
    # Find the position after first line in original text
    # We need to handle that first_line may appear multiple times; find nth occurrence
    # Instead, compute offset by summing lengths
    # Use splitlines(True) to keep line breaks
    lines_keep = text.splitlines(True)
    # Find first non-empty line index in keep list
    keep_idx = None
    for idx, l in enumerate(lines_keep):
        if l.strip():
            keep_idx = idx
            break
    if keep_idx is None:
        return text

    remaining_text = "".join(lines_keep[keep_idx + 1 :])
    remaining_original_start = len("".join(lines_keep[: keep_idx + 1]))

    # 1. Look for Answer/Response/Final answer heading (preference 1)
    ans_match = _ANSWER_HEADING_RE.search(remaining_text)
    if ans_match:
        # Cut after the heading line
        cut_pos = ans_match.end()
        # remaining_text[cut_pos:] is after heading
        return remaining_text[cut_pos:].lstrip()

    # 2. Look for horizontal rule ---
    hr_match = _HR_RE.search(remaining_text)
    if hr_match:
        cut_pos = hr_match.end()
        return remaining_text[cut_pos:].lstrip()

    # 3. Look for next markdown heading that isn't reasoning
    # Iterate through heading matches in remaining_text
    for hm in _HEADING_RE.finditer(remaining_text):
        heading_line = hm.group(0)
        if not _is_reasoning_heading(heading_line):
            # Cut to this heading (include it)
            cut_pos = hm.start()
            return remaining_text[cut_pos:].lstrip()

    # No boundary found -> leave unchanged per spec
    return text


def _is_valid_widget_json(json_str: str) -> bool:
    try:
        obj = json.loads(json_str)
        return isinstance(obj, dict)
    except Exception:
        return False


def sanitize_response(
    text: str,
    *,
    required_widgets: Optional[List[Tuple[str, str]]] = None,
) -> str:
    """Sanitize LLM output: strip reasoning, validate widgets, enforce prose+widgets order.

    Args:
        text: Raw LLM output.
        required_widgets: Optional list of (type, json_str) that are authoritative.
            They override any model-emitted widgets of same type.

    Returns:
        Cleaned string: prose (max one blank line) + widget blocks at end.
    """
    if text is None:
        text = ""
    if not isinstance(text, str):
        # Defensive: if somehow list, join
        try:
            # If it's a list of parts, try to extract text
            if isinstance(text, list):
                parts = []
                for p in text:
                    if isinstance(p, str):
                        parts.append(p)
                    elif isinstance(p, dict):
                        if "text" in p and isinstance(p["text"], str):
                            parts.append(p["text"])
                        elif "content" in p and isinstance(p["content"], str):
                            parts.append(p["content"])
                    else:
                        # LangChain message part may have .text
                        t = getattr(p, "text", None)
                        if isinstance(t, str):
                            parts.append(t)
                        else:
                            # fallback str
                            try:
                                parts.append(str(p))
                            except Exception:
                                pass
                text = "\n".join(parts)
            else:
                text = str(text)
        except Exception:
            text = str(text)

    # Step 1: Remove think-like blocks
    cleaned = _strip_think_blocks(text)

    # Step 2: Strip leading reasoning preamble
    cleaned = _strip_reasoning_preamble(cleaned)

    # Step 3: Extract widgets, validate
    extracted = extract_widgets(cleaned)
    valid_extracted: List[Tuple[str, str]] = []
    for w_type, j_str in extracted:
        if _is_valid_widget_json(j_str):
            valid_extracted.append((w_type, j_str))

    # Build map and order for valid extracted
    seen: dict[str, str] = {}
    order: List[str] = []
    for w_type, j_str in valid_extracted:
        if w_type not in seen:
            order.append(w_type)
        seen[w_type] = j_str  # last wins

    # Step 4: Merge required_widgets (authoritative)
    required_widgets = required_widgets or []
    # Validate required_widgets entries are (type, json_str) and keep even if we want to ensure dict?
    # Spec says backend-computed blocks are authoritative; we keep them if they are valid dict,
    # but even if invalid we still keep? To be safe, keep only if valid dict, otherwise still drop?
    # We'll keep only if valid dict, because otherwise widget would be broken.
    # However, if required is provided, it should be considered authoritative even if model had broken.
    # So filter required to valid dicts for final output, but still override.
    filtered_required: List[Tuple[str, str]] = []
    for item in required_widgets:
        try:
            w_type, j_str = item
        except Exception:
            continue
        if _is_valid_widget_json(j_str):
            filtered_required.append((w_type, j_str))
        else:
            # Even if invalid, we skip? But spec says broken/missing replaced by required, so required should be valid.
            # If invalid, we still include to preserve authoritative nature? We'll include only if valid.
            # To avoid broken output, skip invalid required as well.
            continue

    # Build required order unique
    req_order_unique: List[str] = []
    req_map: dict[str, str] = {}
    for w_type, j_str in filtered_required:
        if w_type not in req_order_unique:
            req_order_unique.append(w_type)
        req_map[w_type] = j_str
        # override seen
        if w_type not in seen:
            order.append(w_type)
        seen[w_type] = j_str

    # Final order: required order first, then remaining order not in required
    final_order: List[str]
    if req_order_unique:
        final_order = req_order_unique + [t for t in order if t not in req_order_unique]
    else:
        final_order = order

    final_widgets: List[Tuple[str, str]] = [(t, seen[t]) for t in final_order if t in seen]

    # Step 5: Prose handling
    prose = strip_widgets(cleaned)
    # Collapse to max one blank line
    # Replace multiple blank lines (with optional spaces) with \n\n
    prose = re.sub(r"\n\s*\n\s*\n+", "\n\n", prose)
    prose = re.sub(r"\n{3,}", "\n\n", prose)
    prose = prose.strip()

    # Reconstruct
    if prose and final_widgets:
        widget_blocks = "\n\n".join(f"```widget:{w_type}\n{j_str}\n```" for w_type, j_str in final_widgets)
        return f"{prose}\n\n{widget_blocks}"
    elif prose:
        return prose
    elif final_widgets:
        widget_blocks = "\n\n".join(f"```widget:{w_type}\n{j_str}\n```" for w_type, j_str in final_widgets)
        return widget_blocks
    else:
        # If everything stripped, return original prose stripped (could be empty)
        return prose
