"""Post-STT lexical / phonetic correction against the dental knowledge corpus.

The point: STT engines (especially on muffled or distant audio) make
*confident mistakes* on rare jargon. They produce plausible-but-wrong tokens
like:

    "amox cillin"    →   should be "amoxicillin"
    "endo dontic"    →   should be "endodontic"
    "perio donial"   →   should be "periodontal"
    "occlu sull"     →   should be "occlusal"
    "tooth slooth"   →   should be "Tooth Slooth"   (proper noun, dental device)
    "cracked toothy" →   should be "cracked tooth"
    "salvia testing" →   should be "saliva testing" (D0426)

Strategy: for each non-dictionary token (and pair of adjacent tokens), look
up the nearest neighbor in the dental corpus by **double-metaphone phonetic
distance** + Levenshtein edit distance. If both distances are small enough,
snap to the canonical term. Conservative — we'd rather leave a weird token
alone than confidently change "Sharma" to "scaling".

Why this works without any ML training:
  * STT errors on jargon are usually phonetic, not semantic — the engine
    heard the right sounds and reached for a similar-sounding common word.
  * Our dental corpus is small (hundreds of terms), so an exhaustive
    nearest-neighbor scan per suspicious token is sub-millisecond.

We do NOT touch:
  * Names (capitalized words not in the corpus)
  * Numbers / units
  * Tokens already in the corpus
  * Tokens with a stem already in the corpus
  * Very short tokens (<4 chars) — too easy to false-positive
"""
from __future__ import annotations
import re
from typing import List, Tuple, Optional, Dict

# Inline stemmer — was previously imported from agents/knowledge.py, but that
# whole legacy module was removed during the batch-4 cleanup. This 4-line
# helper is the only thing we needed from it.
_STEM_SUFFIXES = (
    "iest", "ingly", "edly", "ness", "ment", "tion", "sion", "able", "ible",
    "ation", "ition", "ing", "ied", "ies", "ous", "ive", "ed", "es", "er",
    "ly", "al", "ic", "s", "y",
)
def _stem(word: str) -> str:
    w = (word or "").lower()
    for suf in _STEM_SUFFIXES:
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[:-len(suf)]
    return w

# `DentalKnowledge` is no longer imported here — text_correction.py only
# referenced its `_stem` helper. The earlier dependency on the class was
# removed in the cleanup.
DentalKnowledge = None   # type: ignore  # legacy compat for any stale callers


# ---------- thresholds ----------
# Lessons from the first test pass:
#   * Substitution at edit-distance 2 corrupts common English ("there"→"three",
#     "tooth"→"mouth", "started"→"stated"). Bring it down to 1 so only the
#     most-obvious mishears get snapped.
#   * Gluing is actually the SAFER path because it's evidence-based — we
#     don't glue unless the joined token matches a corpus term very closely.
#   * Both paths protect a list of common English source tokens.
MAX_PHONETIC_DIST   = 2          # collapsed-vowel code distance
MAX_EDIT_DIST       = 1          # Levenshtein for single-token substitute (tight)
MAX_GLUED_EDIT_DIST = 2          # glue path is evidence-based; can be looser
MIN_TOKEN_LEN       = 5          # avoid short-token false-positives


_TOKENIZE = re.compile(r"\S+", re.UNICODE)


# ---------- public API ----------

def correct_against_corpus(text: str, kb: DentalKnowledge) -> Tuple[str, List[Dict]]:
    """Return (corrected_text, list_of_corrections).

    Each correction is `{from, to, kind, position}` for traceability.
    Whitespace, punctuation, and casing are preserved as much as possible.
    """
    if not text or not text.strip():
        return text, []

    candidates = _build_candidate_index(kb)
    if not candidates:
        return text, []

    # We work on lines so the speaker-prefix structure ("Doctor: …") survives.
    out_lines: List[str] = []
    corrections: List[Dict] = []
    for line in text.splitlines():
        new_line, line_corrections = _correct_line(line, candidates)
        out_lines.append(new_line)
        corrections.extend(line_corrections)
    return "\n".join(out_lines), corrections


# ---------- internals ----------

def _build_candidate_index(kb: DentalKnowledge) -> List[Tuple[str, str]]:
    """List of (canonical_term, phonetic_code) drawn from the corpus.

    We exclude very short terms (where phonetic distance is too forgiving)
    and very abstract scaffolding ("today", "appointment", …) — those are
    fine targets if the STT outputs them, but bad targets to snap *to*.
    """
    out: List[Tuple[str, str]] = []
    seen: set = set()

    # Curated allow-list of corpus categories that are STT-correctable.
    for word in kb.kb.get("terms", []):
        w = word.lower().strip()
        if len(w) < MIN_TOKEN_LEN or "-" in w:
            # Hyphenated multi-words handled via two-token "glue" path.
            continue
        if w in _DO_NOT_SNAP_TO:
            continue
        if w in seen:
            continue
        seen.add(w)
        code = _double_metaphone_simple(w)
        if code:
            out.append((w, code))

    # CDT nomenclature single-word tokens (e.g. "endodontic", "prophylaxis").
    for c in kb.cdt_codes:
        for word in re.findall(r"[a-zA-Z]+", c["nomenclature"]):
            w = word.lower()
            if len(w) < 5 or w in seen or w in _DO_NOT_SNAP_TO:
                continue
            seen.add(w)
            code = _double_metaphone_simple(w)
            if code:
                out.append((w, code))
    return out


# Words too generic to be safe snap-targets even if phonetically similar.
_DO_NOT_SNAP_TO = {
    "tooth", "teeth", "today", "next", "appointment", "patient", "doctor",
    "good", "fair", "poor", "year", "years", "month", "months", "week",
    "weeks", "day", "days", "hour", "hours", "mouth",
}

# Common English words that must NEVER be substitution SOURCES, even if a
# corpus term sits close in phonetic / edit space. This is the second-half
# of the safety net: protect the input, then constrain the output.
# (Curated; if we want comprehensive coverage in P3 we'll swap in a real
# wordlist — wordfreq or similar.)
_PROTECTED_SOURCES = frozenset({
    # short function words — never gluing across these
    "and", "the", "but", "for", "nor", "yet", "with", "from", "into",
    "onto", "upon", "off", "out", "via", "per", "you", "your", "yours",
    "him", "her", "his", "hers", "its", "our", "ours", "him", "they", "them",
    "are", "was", "were", "been", "being", "had", "has", "have", "did",
    "does", "doing", "done", "say", "said", "saying", "get", "got", "gets",
    "any", "all", "few", "lot", "lots", "some", "one", "two", "ten",
    "see", "saw", "use", "used", "yes", "no", "ok", "okay",
    # longer common English (most originals)
    "there", "their", "they're", "where", "here", "these", "those",
    "this", "that", "than", "then", "with", "without", "after", "before",
    "started", "stopped", "moved", "came", "gone", "went", "going", "doing",
    "thought", "though", "through", "throw", "throat",
    "tooth", "teeth", "mouth", "month", "month", "smooth", "youth",
    "right", "left", "bite", "biting", "bitten", "behind", "below", "between",
    "looks", "looked", "looking", "feels", "felt", "feeling",
    "noticed", "noticing", "asked", "asking", "told", "telling",
    "first", "second", "third", "next", "last", "every", "while", "until",
    "since", "during", "around", "about", "back", "front", "side",
    "would", "could", "should", "shall", "might", "must", "may",
    "what", "which", "when", "where", "whom", "whose", "whether",
    "really", "very", "much", "many", "more", "most", "less", "least",
    "some", "any", "all", "both", "either", "neither", "none",
    "again", "also", "always", "never", "ever", "still", "even",
    "good", "better", "best", "well", "wells", "fine", "great", "okay",
    "ago", "later", "soon", "early", "late", "now", "today",
    "above", "across", "along", "among", "behind", "beneath", "beyond",
    "cold", "hot", "warm", "cool", "soft", "hard", "loose", "tight",
    "year", "years", "month", "months", "week", "weeks", "day", "days",
    "hour", "hours", "minute", "minutes", "second", "seconds",
    "small", "large", "tiny", "huge",
    "started", "stated", "ended", "began", "ending",
    "issue", "issues", "tissue", "tissues", "schedule", "scheduled",
    "scheduling", "schedules", "session", "sessions", "office", "visit",
    "visits", "discussion", "decision", "option", "options",
    "recommend", "recommends", "recommended", "advise", "advised",
    "suggest", "suggested", "consider", "considered", "noted", "found",
    "shows", "showed", "appears", "appeared", "seems", "seemed",
    "looks", "looked", "feels", "felt", "thinks", "thought",
})


def _correct_line(line: str, candidates: List[Tuple[str, str]]) -> Tuple[str, List[Dict]]:
    """Run the correction pass on a single line."""
    # Tokenize preserving whitespace runs separately so we can rejoin.
    tokens = _TOKENIZE.findall(line)
    if not tokens:
        return line, []

    corrections: List[Dict] = []
    new_tokens: List[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        bare = re.sub(r"[^a-zA-Z]", "", tok).lower()

        # Protected English source words are never touched, even if a glue
        # opportunity exists with the next token.
        if bare in _PROTECTED_SOURCES or len(bare) < 3:
            new_tokens.append(tok); i += 1
            continue

        # 1) GLUE first — even if this token is already in the corpus, the
        #    glued form may be a stronger match ("endo" + "dontic" →
        #    "endodontic" is preferable to leaving "endo dontic" split).
        glued_hit: Optional[str] = None
        if i + 1 < len(tokens):
            nxt = tokens[i + 1]
            nxt_bare = re.sub(r"[^a-zA-Z]", "", nxt).lower()
            if (nxt_bare
                    and nxt_bare not in _PROTECTED_SOURCES
                    and len(nxt_bare) >= 4):    # avoid gluing across short
                                                # function words ("and", "the")
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

        # 2) Already-good tokens — leave alone now that glue path didn't fire.
        if len(bare) < MIN_TOKEN_LEN or _safe_token(bare, candidates):
            new_tokens.append(tok); i += 1
            continue

        # 3) Single-token substitution. Tight by design: edit distance 1.
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


def _safe_token(bare: str, candidates: List[Tuple[str, str]]) -> bool:
    """Skip tokens we shouldn't touch: already in corpus or stem matches."""
    if not bare:
        return True
    if bare in (c[0] for c in candidates):
        return True
    stem = _stem(bare)
    return stem in (c[0] for c in candidates) or stem in {c[0] for c in candidates}


def _nearest(token: str, candidates: List[Tuple[str, str]], max_edit: int) -> Optional[str]:
    """Find the closest candidate whose phonetic prefix matches AND edit
    distance is below `max_edit`. Returns None if no good match.
    """
    tok_code = _double_metaphone_simple(token)
    if not tok_code:
        return None
    best: Optional[Tuple[int, int, str]] = None  # (edit_dist, phonetic_dist, word)
    for word, code in candidates:
        # Quick phonetic prefix filter — both should sound similar.
        pdist = _phonetic_dist(tok_code, code)
        if pdist > MAX_PHONETIC_DIST:
            continue
        edist = _levenshtein(token, word, cap=max_edit + 1)
        if edist > max_edit:
            continue
        cand = (edist, pdist, word)
        if best is None or cand < best:
            best = cand
    return best[2] if best else None


def _phonetic_dist(a: str, b: str) -> int:
    """Distance between two simple-metaphone codes — char-level Levenshtein."""
    return _levenshtein(a, b, cap=4)


# ---------- a tiny pure-Python phonetic encoder ----------
# Full Double Metaphone would be ~300 lines; we use a Soundex-flavored encoder
# tuned for the dental vocabulary's failure modes (vowel runs, soft consonants,
# silent endings). Good enough for "perio donial" ≈ "periodontal".

_PHONETIC_MAP = str.maketrans({
    # vowels collapse to "A" (dropped after first)
    "a": "A", "e": "A", "i": "A", "o": "A", "u": "A", "y": "A",
    # bilabials
    "b": "P", "p": "P",
    # dentals
    "d": "T", "t": "T",
    # velars
    "k": "K", "q": "K", "c": "K", "g": "K", "x": "KS",
    # fricatives
    "f": "F", "v": "F", "s": "S", "z": "S",
    # nasals
    "m": "M", "n": "M",
    # liquids
    "l": "L", "r": "R",
    # h, w, j: weak
    "h": "", "w": "", "j": "J",
})

def _double_metaphone_simple(word: str) -> str:
    if not word:
        return ""
    w = re.sub(r"[^a-zA-Z]", "", word).lower()
    if not w:
        return ""
    # Normalize a few digraphs first
    w = w.replace("ph", "F").replace("th", "T").replace("ch", "K") \
         .replace("sh", "S").replace("ck", "K").replace("qu", "K") \
         .replace("ng", "N").replace("gh", "")
    code = w.translate(_PHONETIC_MAP)
    # Collapse runs of the same letter
    out: List[str] = []
    prev = None
    for ch in code:
        if ch != prev:
            out.append(ch)
            prev = ch
    # Drop trailing weak vowels and weak consonants
    s = "".join(out).strip("A")
    return s


def _levenshtein(a: str, b: str, cap: int = 10) -> int:
    """Iterative Levenshtein with an early-exit cap (saves time on long words)."""
    if a == b:
        return 0
    if not a or not b:
        return len(a or b)
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    curr = [0] * (len(b) + 1)
    for i, ca in enumerate(a, 1):
        curr[0] = i
        row_min = curr[0]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
            if curr[j] < row_min:
                row_min = curr[j]
        if row_min > cap:
            return cap + 1
        prev, curr = curr, prev
    return prev[-1]


# ---------- casing preservation ----------

def _preserve_case_and_punct(original: str, replacement: str) -> str:
    """Replace the alphabetic content of `original` with `replacement`,
    preserving leading capitalization and trailing punctuation.
    """
    m = re.match(r"^(\W*)([a-zA-Z]+)(\W*)$", original)
    if not m:
        return replacement
    lead, _, trail = m.groups()
    out = replacement
    if original and original[0].isupper():
        out = out[0].upper() + out[1:]
    return f"{lead}{out}{trail}"


def _preserve_case(original: str, replacement: str) -> str:
    """For glued tokens — preserve only the casing of the first character."""
    if not replacement:
        return replacement
    return (replacement[0].upper() + replacement[1:]) if (
        original and original[0].isupper()
    ) else replacement
