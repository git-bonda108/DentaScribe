"""Normalize spoken tooth/surface references in transcript text."""
from __future__ import annotations

import re
from typing import List, Tuple

from utils.tooth_norm import normalize_tooth
from utils.surface_norm import normalize_surface

_TOOTH_PHRASE = re.compile(
    r"(?i)\b(?:tooth|teeth|#)\s*(?:number|no\.?|#)?\s*"
    r"([a-z0-9\s\-]+?)(?=\s+(?:with|has|is|was|and|,|\.|$)|$)"
)
_ANATOMICAL_CHUNK = re.compile(
    r"(?i)\b((?:upper|lower)\s+(?:right|left)\s+"
    r"(?:third|second|first)?\s*(?:molar|premolar|bicuspid|canine|cuspid|incisor|wisdom tooth)[s]?)\b"
)
_SURFACE_PHRASE = re.compile(
    r"(?i)\b((?:mesial|distal|occlusal|incisal|buccal|facial|labial|lingual|palatal)"
    r"(?:\s+(?:occlusal|incisal|distal|mesial)){0,2})\b"
)


def normalize_transcript(text: str) -> Tuple[str, List[str]]:
    """Return normalized transcript + log of replacements."""
    if not text:
        return text, []
    log: List[str] = []
    out = text

    def _replace_tooth(match: re.Match) -> str:
        chunk = match.group(0)
        n = normalize_tooth(chunk)
        if n:
            repl = f"tooth {n}"
            if repl.lower() != chunk.lower():
                log.append(f"{chunk.strip()} → #{n}")
            return repl
        return chunk

    out = _TOOTH_PHRASE.sub(_replace_tooth, out)

    def _replace_anatomical(match: re.Match) -> str:
        chunk = match.group(1)
        n = normalize_tooth(chunk)
        if n:
            log.append(f"{chunk} → tooth {n}")
            return f"tooth {n}"
        return chunk

    out = _ANATOMICAL_CHUNK.sub(_replace_anatomical, out)

    def _replace_surface(match: re.Match) -> str:
        chunk = match.group(1)
        code = normalize_surface(chunk)
        if code:
            log.append(f"{chunk} → {code}")
            return code
        return chunk

    out = _SURFACE_PHRASE.sub(_replace_surface, out)
    return out, log
