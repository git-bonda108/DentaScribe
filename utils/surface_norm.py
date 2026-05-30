"""utils/surface_norm.py — spoken surface -> code (M/D/O/I/B/F/L/P, MO/DO/MOD ...)"""
import re
from typing import Optional
SURF = {"mesial":"M","distal":"D","occlusal":"O","incisal":"I","buccal":"B","facial":"F","labial":"F","lingual":"L","palatal":"P"}
COMBOS = {"mo":"MO","do":"DO","mod":"MOD","mid":"MID","did":"DID",
 "mesio occlusal":"MO","disto occlusal":"DO","mesio occluso distal":"MOD",
 "mesial occlusal":"MO","distal occlusal":"DO","mesial occlusal distal":"MOD",
 "mesial incisal":"MI","distal incisal":"DI","mesial incisal distal":"MID"}
def normalize_surface(text: str) -> Optional[str]:
    if not text: return None
    s = re.sub(r"\s+"," ",re.sub(r"[^a-z\s]"," ",text.lower())).strip()
    if s in COMBOS: return COMBOS[s]
    letters = [SURF[w] for w in s.split() if w in SURF]
    if not letters: return None
    order = {"M":0,"D":1,"O":2,"I":2,"B":3,"F":3,"L":4,"P":4}
    return "".join(sorted(set(letters), key=lambda c: order.get(c,9)))
