"""utils/tooth_norm.py — spoken form -> Universal #1-32"""
import re
from typing import Optional

ANATOMICAL = {
 "upper right third molar":1,"upper right wisdom tooth":1,
 "upper right second molar":2,"upper right first molar":3,
 "upper right second premolar":4,"upper right second bicuspid":4,
 "upper right first premolar":5,"upper right first bicuspid":5,
 "upper right canine":6,"upper right cuspid":6,
 "upper right lateral incisor":7,"upper right central incisor":8,
 "upper left central incisor":9,"upper left lateral incisor":10,
 "upper left canine":11,"upper left cuspid":11,
 "upper left first premolar":12,"upper left first bicuspid":12,
 "upper left second premolar":13,"upper left second bicuspid":13,
 "upper left first molar":14,"upper left second molar":15,
 "upper left third molar":16,"upper left wisdom tooth":16,
 "lower left third molar":17,"lower left wisdom tooth":17,
 "lower left second molar":18,"lower left first molar":19,
 "lower left second premolar":20,"lower left second bicuspid":20,
 "lower left first premolar":21,"lower left first bicuspid":21,
 "lower left canine":22,"lower left cuspid":22,
 "lower left lateral incisor":23,"lower left central incisor":24,
 "lower right central incisor":25,"lower right lateral incisor":26,
 "lower right canine":27,"lower right cuspid":27,
 "lower right first premolar":28,"lower right first bicuspid":28,
 "lower right second premolar":29,"lower right second bicuspid":29,
 "lower right first molar":30,"lower right second molar":31,
 "lower right third molar":32,"lower right wisdom tooth":32,
}
NUM_WORDS = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,
 "nine":9,"ten":10,"eleven":11,"twelve":12,"thirteen":13,"fourteen":14,"fifteen":15,
 "sixteen":16,"seventeen":17,"eighteen":18,"nineteen":19,"twenty":20,"twenty one":21,
 "twenty two":22,"twenty three":23,"twenty four":24,"twenty five":25,"twenty six":26,
 "twenty seven":27,"twenty eight":28,"twenty nine":29,"thirty":30,"thirty one":31,"thirty two":32}
PALMER = {"UR8":1,"UR7":2,"UR6":3,"UR5":4,"UR4":5,"UR3":6,"UR2":7,"UR1":8,
 "UL1":9,"UL2":10,"UL3":11,"UL4":12,"UL5":13,"UL6":14,"UL7":15,"UL8":16,
 "LL8":17,"LL7":18,"LL6":19,"LL5":20,"LL4":21,"LL3":22,"LL2":23,"LL1":24,
 "LR1":25,"LR2":26,"LR3":27,"LR4":28,"LR5":29,"LR6":30,"LR7":31,"LR8":32}
FDI = {"18":1,"17":2,"16":3,"15":4,"14":5,"13":6,"12":7,"11":8,
 "21":9,"22":10,"23":11,"24":12,"25":13,"26":14,"27":15,"28":16,
 "38":17,"37":18,"36":19,"35":20,"34":21,"33":22,"32":23,"31":24,
 "41":25,"42":26,"43":27,"44":28,"45":29,"46":30,"47":31,"48":32}

def normalize_tooth(text: str) -> Optional[int]:
    if not text: return None
    s = re.sub(r"\s+"," ",re.sub(r"[^a-z0-9\s]"," ",text.lower())).strip()
    m = re.fullmatch(r"(\d{1,2})", s)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 32: return n
        if s in FDI: return FDI[s]
    if s in FDI: return FDI[s]
    up = s.upper().replace(" ","")
    if up in PALMER: return PALMER[up]
    if s in ANATOMICAL: return ANATOMICAL[s]
    for k,v in ANATOMICAL.items():
        if k in s: return v
    m = re.search(r"tooth\s+([a-z\s]+)", s)
    if m:
        w = m.group(1).strip()
        if w in NUM_WORDS: return NUM_WORDS[w]
    m = re.search(r"(?:number|no|#)\s*(\d{1,2})", s)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 32: return n
    return None
