"""Tooth numbering normalization.

Maps colloquial/ASR-error tooth references into the Universal Numbering System (1-32).
Also supports FDI -> Universal conversion for completeness.

The Scribe agent always emits Universal numbers in SOAP output. This module is the gate.
"""
from __future__ import annotations
import re

# Universal Numbering System reference (adult dentition)
UNIVERSAL_TO_NAME = {
    1: "upper right third molar (wisdom)",   2: "upper right second molar",
    3: "upper right first molar",            4: "upper right second premolar",
    5: "upper right first premolar",         6: "upper right canine",
    7: "upper right lateral incisor",        8: "upper right central incisor",
    9: "upper left central incisor",         10: "upper left lateral incisor",
    11: "upper left canine",                 12: "upper left first premolar",
    13: "upper left second premolar",        14: "upper left first molar",
    15: "upper left second molar",           16: "upper left third molar (wisdom)",
    17: "lower left third molar (wisdom)",   18: "lower left second molar",
    19: "lower left first molar",            20: "lower left second premolar",
    21: "lower left first premolar",         22: "lower left canine",
    23: "lower left lateral incisor",        24: "lower left central incisor",
    25: "lower right central incisor",       26: "lower right lateral incisor",
    27: "lower right canine",                28: "lower right first premolar",
    29: "lower right second premolar",       30: "lower right first molar",
    31: "lower right second molar",          32: "lower right third molar (wisdom)",
}

# FDI to Universal (adult)
FDI_TO_UNIVERSAL = {
    "18":1,"17":2,"16":3,"15":4,"14":5,"13":6,"12":7,"11":8,
    "21":9,"22":10,"23":11,"24":12,"25":13,"26":14,"27":15,"28":16,
    "38":17,"37":18,"36":19,"35":20,"34":21,"33":22,"32":23,"31":24,
    "41":25,"42":26,"43":27,"44":28,"45":29,"46":30,"47":31,"48":32,
}

# Common colloquial -> Universal
COLLOQUIAL = {
    "upper right wisdom": 1, "upper left wisdom": 16,
    "lower left wisdom": 17, "lower right wisdom": 32,
    "lower left first molar": 19, "lower right first molar": 30,
    "upper right first molar": 3, "upper left first molar": 14,
    "lower left six year molar": 19, "lower right six year molar": 30,
    "front tooth upper right": 8, "front tooth upper left": 9,
    "front tooth lower right": 25, "front tooth lower left": 24,
}


def normalize_tooth(raw: str) -> str | None:
    """Return canonical Universal number as string ('1'..'32'), or None if unparseable."""
    if raw is None:
        return None
    s = str(raw).strip().lower()

    # Plain integer 1-32
    if s.isdigit():
        n = int(s)
        if 1 <= n <= 32:
            return str(n)
        # Could be FDI
        if s in FDI_TO_UNIVERSAL:
            return str(FDI_TO_UNIVERSAL[s])
        return None

    # "tooth 19", "#19", "no. 19"
    m = re.search(r"(\d{1,2})", s)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 32:
            return str(n)
        if m.group(1) in FDI_TO_UNIVERSAL:
            return str(FDI_TO_UNIVERSAL[m.group(1)])

    # Colloquial phrase match
    for phrase, num in COLLOQUIAL.items():
        if phrase in s:
            return str(num)

    return None


def describe_tooth(num: str | int) -> str:
    try:
        n = int(num)
        return UNIVERSAL_TO_NAME.get(n, f"tooth {n}")
    except (TypeError, ValueError):
        return str(num)


if __name__ == "__main__":
    # quick self-test
    cases = ["19", "#19", "tooth 19", "lower left first molar", "36", "FDI 36", "garbage"]
    for c in cases:
        print(f"{c!r:35s} -> {normalize_tooth(c)}")
