"""Tooth surface normalization.

Surfaces in Universal notation:
    M = Mesial, O = Occlusal, D = Distal, B = Buccal, L = Lingual,
    F = Facial (anterior), I = Incisal (anterior)

Coder agent uses these surfaces to pick correct CDT (D2391/2/3/4 = 1/2/3/4+ surfaces).
"""
from __future__ import annotations

WORD_TO_CODE = {
    "mesial": "M", "messeal": "M",
    "occlusal": "O", "okeysol": "O", "occulsal": "O",
    "distal": "D", "destal": "D",
    "buccal": "B", "buckle": "B",
    "lingual": "L", "lingwall": "L",
    "facial": "F",
    "incisal": "I",
}


def normalize_surfaces(raw) -> list[str]:
    """Accept str ('MO', 'mesial-occlusal') or list and return canonical letter codes."""
    if raw is None:
        return []
    if isinstance(raw, list):
        out = []
        for item in raw:
            out.extend(normalize_surfaces(item))
        # de-dup preserving order
        seen = set(); uniq = []
        for s in out:
            if s not in seen:
                seen.add(s); uniq.append(s)
        return uniq

    s = str(raw).strip().lower()
    if not s:
        return []

    # phrase like "mesial occlusal" or "mesial-occlusal distal"
    out = []
    for word, code in WORD_TO_CODE.items():
        if word in s:
            out.append(code)
    if out:
        seen = set(); uniq = []
        for c in out:
            if c not in seen:
                seen.add(c); uniq.append(c)
        return uniq

    # compact code like "MOD" or "mod"
    valid = set("MODBLFI")
    upper = s.upper()
    if all(ch in valid for ch in upper):
        seen = set(); uniq = []
        for ch in upper:
            if ch not in seen:
                seen.add(ch); uniq.append(ch)
        return uniq

    return []


def surface_count(surfaces: list[str]) -> int:
    return len(normalize_surfaces(surfaces))


# Alias — batch 4's clinical_agents.py imports `count_surfaces` (verb-noun order).
# Same function; keep both names so cross-batch imports work in either direction.
count_surfaces = surface_count


if __name__ == "__main__":
    for c in ["MOD", "mesial occlusal", "mo", "lingual", "messeal-okeysol", "junk"]:
        print(f"{c!r:25s} -> {normalize_surfaces(c)}")
