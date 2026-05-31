"""Post-STT lexical correction against the new dental glossary + CDT catalog.

Runs immediately after Deepgram (or demo passthrough) returns a transcript.
Two passes, in this order — explicit first, fuzzy second:

  1. **Dictionary pass** — looks each token up in
     `glossary["asr_corrections"]` and replaces verbatim ("okeysol" →
     "occlusal"). Deterministic and safe; this is the architect-curated
     list of known dental mishears.

  2. **Phonetic + edit-distance fuzzy pass** — for tokens NOT covered by
     the dictionary, snap to the nearest dental term (glossary keys + CDT
     nomenclature) when phonetic-code distance ≤ 2 AND Levenshtein ≤ 1.
     Includes a glue path that joins a misheard split word back together
     ("amox cillin" → "amoxicillin"). Protected English source words
     bypass this pass entirely.

Why two layers:
  - The dictionary handles the cases the architect already knew about.
  - The fuzzy pass catches the long tail (variant mishears, accents, drift)
    without manual upkeep — *but* only against known dental vocabulary,
    so it can't drift into general English.

Conservative by design: when in doubt, leave the token alone.
"""
from __future__ import annotations
import re
from functools import lru_cache
from typing import List, Tuple, Dict, Optional, Iterable

from core.glossary_loader import load_glossary, load_cdt_allow_list

# Reuse the phonetic machinery and protected-source list from the earlier
# correction module. They're battle-tested via the STT smoke test.
from utils.text_correction import (
    _double_metaphone_simple,
    _levenshtein,
    _preserve_case_and_punct,
    _preserve_case,
    _PROTECTED_SOURCES,
    _DO_NOT_SNAP_TO,
    MAX_EDIT_DIST,
    MAX_PHONETIC_DIST,
    MAX_GLUED_EDIT_DIST,
    MIN_TOKEN_LEN,
)


_TOKENIZE = re.compile(r"\S+", re.UNICODE)


# ---------- public API ----------

def correct_transcript(text: str) -> Tuple[str, List[Dict]]:
    """Apply both passes to a full transcript blob.

    Returns (corrected_text, corrections_audit) where each correction is
    `{from, to, kind, position}` for the audit log / UI hover.
    """
    if not text or not text.strip():
        return text, []

    corrections: List[Dict] = []
    out_lines: List[str] = []
    for line in text.splitlines():
        # Pass 1 — dictionary
        line1, fixed = _dict_pass(line)
        corrections.extend(fixed)
        # Pass 2 — fuzzy
        line2, fuzzy = _fuzzy_pass(line1)
        corrections.extend(fuzzy)
        out_lines.append(line2)
    return "\n".join(out_lines), corrections


# Convenience for segment-level correction (used by transcribe_file).
def correct_segments(segments: Iterable[object]) -> List[Dict]:
    """Run correction on each TranscriptSegment.text in place.

    Each segment is expected to expose a `.text` attribute (TranscriptSegment
    dataclass from audio/transcript_types.py). Returns the aggregated
    corrections audit so the caller can attach it to the Transcript.
    """
    audit: List[Dict] = []
    for seg in segments:
        original = getattr(seg, "text", "")
        if not original:
            continue
        fixed, corr = correct_transcript(original)
        if fixed != original:
            seg.text = fixed
        for c in corr:
            audit.append({**c, "segment": getattr(seg, "speaker", "?")})
    return audit


# ---------- pass 1: dictionary ----------

def _dict_pass(line: str) -> Tuple[str, List[Dict]]:
    """Replace any token whose lowercase bare form is a key in asr_corrections."""
    asr = _asr_corrections_lower()
    if not asr:
        return line, []
    tokens = _TOKENIZE.findall(line)
    if not tokens:
        return line, []
    new_tokens: List[str] = []
    fixed: List[Dict] = []
    for tok in tokens:
        bare = re.sub(r"[^a-zA-Z\-]", "", tok).lower()
        if bare and bare in asr:
            replacement = asr[bare]
            new_tokens.append(_preserve_case_and_punct(tok, replacement))
            fixed.append({
                "from": tok, "to": replacement,
                "kind": "dictionary", "position": len(new_tokens) - 1,
            })
        else:
            new_tokens.append(tok)
    return " ".join(new_tokens), fixed


# ---------- pass 2: phonetic + edit-distance fuzzy ----------

def _fuzzy_pass(line: str) -> Tuple[str, List[Dict]]:
    """Snap suspicious tokens to the nearest dental term in glossary+CDT.

    Mirror of utils.text_correction._correct_line but sources its candidate
    index from the new architecture (glossary keys + CDT nomenclature words)
    instead of the legacy DentalKnowledge corpus.
    """
    candidates = _candidate_index()
    if not candidates:
        return line, []

    tokens = _TOKENIZE.findall(line)
    if not tokens:
        return line, []

    new_tokens: List[str] = []
    corrections: List[Dict] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        bare = re.sub(r"[^a-zA-Z]", "", tok).lower()

        # Protected English source words — never substitute or glue across.
        if bare in _PROTECTED_SOURCES or len(bare) < 3:
            new_tokens.append(tok); i += 1
            continue

        # 1) GLUE first — "amox cillin" → "amoxicillin"
        glued_hit: Optional[str] = None
        if i + 1 < len(tokens):
            nxt = tokens[i + 1]
            nxt_bare = re.sub(r"[^a-zA-Z]", "", nxt).lower()
            if (nxt_bare
                    and nxt_bare not in _PROTECTED_SOURCES
                    and len(nxt_bare) >= 4):
                bare_glued = bare + nxt_bare
                if len(bare_glued) >= 7:
                    glued_hit = _nearest(bare_glued, candidates,
                                         max_edit=MAX_GLUED_EDIT_DIST)
        if glued_hit:
            new_tokens.append(_preserve_case(tok + tokens[i + 1], glued_hit))
            corrections.append({
                "from": f"{tok} {tokens[i + 1]}", "to": glued_hit,
                "kind": "glue", "position": len(new_tokens) - 1,
            })
            i += 2
            continue

        # 2) Already-good tokens — leave alone
        if len(bare) < MIN_TOKEN_LEN or _is_known_term(bare, candidates):
            new_tokens.append(tok); i += 1
            continue

        # 3) Single-token substitution. Tight: edit-distance 1.
        hit = _nearest(bare, candidates, max_edit=MAX_EDIT_DIST)
        if hit and hit != bare:
            new_tokens.append(_preserve_case_and_punct(tok, hit))
            corrections.append({
                "from": tok, "to": hit,
                "kind": "substitute", "position": len(new_tokens) - 1,
            })
        else:
            new_tokens.append(tok)
        i += 1

    return " ".join(new_tokens), corrections


def _nearest(token: str, candidates: List[Tuple[str, str]], max_edit: int) -> Optional[str]:
    tok_code = _double_metaphone_simple(token)
    if not tok_code:
        return None
    best: Optional[Tuple[int, int, str]] = None
    for word, code in candidates:
        pdist = _levenshtein(tok_code, code, cap=MAX_PHONETIC_DIST + 1)
        if pdist > MAX_PHONETIC_DIST:
            continue
        edist = _levenshtein(token, word, cap=max_edit + 1)
        if edist > max_edit:
            continue
        cand = (edist, pdist, word)
        if best is None or cand < best:
            best = cand
    return best[2] if best else None


def _is_known_term(bare: str, candidates: List[Tuple[str, str]]) -> bool:
    return any(bare == w for w, _ in candidates)


# ---------- candidate index (cached) ----------

@lru_cache(maxsize=1)
def _asr_corrections_lower() -> Dict[str, str]:
    g = load_glossary()
    return {k.lower(): v for k, v in (g.get("asr_corrections") or {}).items()}


@lru_cache(maxsize=1)
def _candidate_index() -> List[Tuple[str, str]]:
    """Flat list of (canonical_term, phonetic_code).

    Drawn from:
      - glossary keys in clinically-meaningful categories
      - glossary asr_corrections values (the canonical forms)
      - CDT nomenclature single-word tokens (5+ chars)
    Skips short tokens and the do-not-snap-to allow-list.
    """
    out: List[Tuple[str, str]] = []
    seen: set = set()

    g = load_glossary()
    for cat in ("anatomy", "conditions", "procedures", "materials",
                "anesthetics", "drugs_common"):
        for term in (g.get(cat) or {}).keys():
            w = term.lower().strip()
            if len(w) < MIN_TOKEN_LEN or "_" in w or w in _DO_NOT_SNAP_TO:
                continue
            if w in seen:
                continue
            seen.add(w)
            code = _double_metaphone_simple(w)
            if code:
                out.append((w, code))

    # Canonical forms from asr_corrections (e.g. "occlusal" via "okeysol→occlusal")
    for v in (g.get("asr_corrections") or {}).values():
        w = v.lower().strip()
        if len(w) < MIN_TOKEN_LEN or w in seen or w in _DO_NOT_SNAP_TO:
            continue
        seen.add(w)
        code = _double_metaphone_simple(w)
        if code:
            out.append((w, code))

    # CDT nomenclature single-word tokens
    cdt = load_cdt_allow_list()
    for c in cdt.get("codes", []):
        for word in re.findall(r"[a-zA-Z]+", c.get("description", "")):
            w = word.lower()
            if len(w) < 5 or w in seen or w in _DO_NOT_SNAP_TO:
                continue
            seen.add(w)
            code = _double_metaphone_simple(w)
            if code:
                out.append((w, code))
    return out
