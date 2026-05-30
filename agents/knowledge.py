"""Dental knowledge retriever — RAG over the consolidated knowledge corpus.

Two responsibilities:

1. **Grounding lookup** (`is_grounded`, `ground_terms`) — fast O(1) set
   membership for the validator. Knows inflectional variants so "scaled"
   matches "scale" and "carious" matches "caries".

2. **Semantic search** (`search`) — returns relevant knowledge snippets for
   injection into NER / SOAP / CDT prompts. Hybrid backend:
     * Token-overlap scoring — always available, deterministic, no LLM.
     * Embedding search via OpenAI — used when key is set. Cached to disk.

Also exposes:
   * `find_cdt_candidates(text, top_n)` — knowledge-driven CDT candidate
     selection (replaces the brittle KEYWORD_MAP regex match).
   * `tooth_words_to_numbers(text)` — normalizes "tooth number nine" → "tooth 9".
"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Iterable

import numpy as np


DATA = Path(__file__).resolve().parent.parent / "data" / "dental_knowledge.json"
CDT = Path(__file__).resolve().parent.parent / "data" / "cdt_codes_2026.json"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".runtime"

# Cheap inflectional normalizer — strip common English suffixes back to a
# canonical stem. Not a full lemmatizer; we just want "scaled" → "scale".
_SUFFIXES = (
    # Order matters: longer suffixes first so "soreness" tries "ness" before
    # falling through to "s".
    "iest", "ingly", "edly", "ness", "ment", "tion", "sion", "able", "ible",
    "ation", "ition", "ing", "ied", "ies", "ous", "ive", "ed", "es", "er",
    "ly", "al", "ic", "s", "y",
)
def _stem(word: str) -> str:
    w = word.lower()
    for suf in _SUFFIXES:
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[:-len(suf)]
    return w


# Tokenize for token-overlap retrieval.
_TOK = re.compile(r"[a-zA-Z][a-zA-Z\-]{1,}")
def _tokens(text: str) -> List[str]:
    return [t.lower() for t in _TOK.findall(text)]


class DentalKnowledge:
    """Singleton-ish retriever. Construct once and pass into agents.

    Construction is cheap when embeddings are disabled or already cached.
    The validator hits `is_grounded` on every SOAP word, so set membership
    must be O(1).
    """

    def __init__(self, openai_client=None, embedding_model: str = "text-embedding-3-small"):
        with open(DATA) as f:
            self.kb = json.load(f)
        with open(CDT) as f:
            cdt = json.load(f)
        self.cdt_codes = cdt["codes"]
        self.cdt_by_code = {c["code"]: c for c in self.cdt_codes}

        # Flat grounded-term set: original + stem + de-hyphenated variants.
        self._grounded: set[str] = set()
        for term in self.kb.get("terms", []):
            self._index_term(term)
        # Add CDT nomenclature words AND the code IDs themselves
        # (so the validator accepts "D0461" if a clinician dictates the code).
        for c in self.cdt_codes:
            self._grounded.add(c["code"].lower())
            for tok in _tokens(c["nomenclature"]):
                self._index_term(tok)
        # Abbreviations + their expansions.
        for abbr, expansion in self.kb.get("abbreviations", {}).items():
            self._index_term(abbr.lower())
            for tok in _tokens(expansion):
                self._index_term(tok)

        # Word-number → digit mapping for tooth normalization.
        self._word_to_num: Dict[str, int] = self.kb.get("tooth_word_to_number", {})

        # Chunks for semantic search.
        self.chunks = self.kb.get("chunks", [])
        for c in self.chunks:
            c["_tokens"] = set(_tokens(c["text"]))

        # Optional embeddings.
        self._openai = openai_client
        self._emb_model = embedding_model
        self._chunk_embeddings: Optional[np.ndarray] = None
        if self._openai is not None and self.chunks:
            self._load_or_compute_embeddings()

    # ------------------------------------------------------------------
    # grounding
    # ------------------------------------------------------------------
    def _index_term(self, term: str) -> None:
        t = term.lower().strip()
        if not t:
            return
        self._grounded.add(t)
        # de-hyphenated form ("night-guard" → "nightguard")
        if "-" in t:
            self._grounded.add(t.replace("-", ""))
            self._grounded.add(t.replace("-", " "))
            for part in t.split("-"):
                self._grounded.add(part)
        # stem
        self._grounded.add(_stem(t))

    def is_grounded(self, term: str) -> bool:
        """True if a token (or its stem) is in the knowledge corpus."""
        t = term.lower().strip()
        if not t:
            return True
        if t in self._grounded:
            return True
        if _stem(t) in self._grounded:
            return True
        # de-hyphenated
        if "-" in t and t.replace("-", "") in self._grounded:
            return True
        return False

    def ground_terms(self, tokens: Iterable[str]) -> Tuple[List[str], List[str]]:
        """Partition tokens into (grounded, ungrounded)."""
        grounded, ungrounded = [], []
        for t in tokens:
            (grounded if self.is_grounded(t) else ungrounded).append(t)
        return grounded, ungrounded

    # ------------------------------------------------------------------
    # tooth normalization
    # ------------------------------------------------------------------
    _TOOTH_WORD_RE = re.compile(
        r"\btooth\s*(?:number|no\.?|#)?\s*"
        r"((?:thirty-(?:one|two))|twenty-(?:one|two|three|four|five|six|seven|eight|nine)"
        r"|thirty|twenty|nineteen|eighteen|seventeen|sixteen|fifteen|fourteen|thirteen"
        r"|twelve|eleven|ten|nine|eight|seven|six|five|four|three|two|one)\b",
        re.IGNORECASE,
    )

    def tooth_words_to_numbers(self, text: str) -> str:
        """Replace "tooth number nine" → "tooth 9" so downstream regex works."""
        def repl(m):
            word = m.group(1).lower().strip()
            n = self._word_to_num.get(word)
            return f"tooth {n}" if n else m.group(0)
        return self._TOOTH_WORD_RE.sub(repl, text)

    # ------------------------------------------------------------------
    # semantic search
    # ------------------------------------------------------------------
    def search(self, query: str, k: int = 5) -> List[Dict]:
        """Return top-k knowledge chunks most relevant to `query`."""
        if not self.chunks:
            return []
        if self._chunk_embeddings is not None:
            try:
                return self._vector_search(query, k)
            except Exception:
                pass
        return self._token_search(query, k)

    def _token_search(self, query: str, k: int) -> List[Dict]:
        q_tokens = set(_tokens(query))
        if not q_tokens:
            return []
        scored = []
        for chunk in self.chunks:
            overlap = len(q_tokens & chunk["_tokens"])
            if overlap == 0:
                continue
            # length-normalize lightly so short chunks aren't penalized
            score = overlap / (1 + 0.05 * len(chunk["_tokens"]))
            scored.append((score, chunk))
        scored.sort(key=lambda x: -x[0])
        return [_strip(c, score=s) for s, c in scored[:k]]

    def _vector_search(self, query: str, k: int) -> List[Dict]:
        v = self._embed_one(query)
        sims = self._chunk_embeddings @ v
        idx = np.argsort(-sims)[:k]
        return [_strip(self.chunks[i], score=float(sims[i])) for i in idx]

    # ------------------------------------------------------------------
    # CDT candidate selection
    # ------------------------------------------------------------------
    def find_cdt_candidates(self, text: str, top_n: int = 12) -> List[Dict]:
        """Knowledge-driven CDT candidate list.

        Scoring: each CDT code earns points for
          * exact code mention ("D0461")  → strong
          * any nomenclature token present → moderate (token-IDF-ish)
          * tag overlap with retrieved knowledge chunks → light

        Replaces the brittle KEYWORD_MAP regex matching for the LLM-on path.
        Caller can still use KEYWORD_MAP as deterministic fallback.
        """
        low = text.lower()
        text_tokens = set(_tokens(low))

        # Pre-compute IDF-ish weights: rarer nomenclature tokens are more
        # discriminative. (Tokens appearing in many CDT codes are weakly
        # discriminative — e.g. "tooth" appears in many codes.)
        token_doc_count: Dict[str, int] = {}
        for c in self.cdt_codes:
            for tok in set(_tokens(c["nomenclature"])):
                token_doc_count[tok] = token_doc_count.get(tok, 0) + 1
        n_docs = max(len(self.cdt_codes), 1)
        def idf(tok: str) -> float:
            return float(np.log((n_docs + 1) / (token_doc_count.get(tok, 0) + 1)) + 1.0)

        # Retrieved chunks bias the score toward conceptually-relevant codes.
        retrieved_tags = set()
        for ch in self.search(text, k=6):
            retrieved_tags.update(ch.get("tags", []))

        scored = []
        for c in self.cdt_codes:
            code = c["code"]
            score = 0.0

            # 1. Direct code mention.
            if code.lower() in low:
                score += 10.0

            # 2. Nomenclature token overlap, IDF-weighted.
            nom_tokens = set(_tokens(c["nomenclature"]))
            overlap = nom_tokens & text_tokens
            for tok in overlap:
                # Skip very generic tokens; they add noise.
                if tok in {"tooth", "teeth", "or", "of", "and", "the", "per",
                           "with", "to", "additional", "first", "second", "third",
                           "fourth", "each", "treatment", "image", "images"}:
                    continue
                score += idf(tok)

            # 3. Tag/category alignment with retrieved knowledge chunks.
            #    Loose match: category names match tag names.
            category = c.get("category", "").lower()
            for tag in retrieved_tags:
                if tag.lower() in category or category in tag.lower():
                    score += 0.5
                    break

            if score > 0:
                scored.append((score, c))

        scored.sort(key=lambda x: -x[0])
        out = []
        for score, c in scored[:top_n]:
            out.append({
                "code": c["code"],
                "nomenclature": c["nomenclature"],
                "category": c.get("category", ""),
                "score": round(score, 2),
            })
        return out

    # ------------------------------------------------------------------
    # embeddings (lazy)
    # ------------------------------------------------------------------
    def _cache_path(self) -> Path:
        h = hashlib.sha1()
        for c in self.chunks:
            h.update(c["id"].encode())
            h.update(c["text"].encode())
        h.update(self._emb_model.encode())
        CACHE_DIR.mkdir(exist_ok=True)
        return CACHE_DIR / f"kb_embeddings_{h.hexdigest()[:12]}.npz"

    def _load_or_compute_embeddings(self) -> None:
        cache = self._cache_path()
        if cache.exists():
            try:
                with np.load(cache) as data:
                    self._chunk_embeddings = data["emb"]
                return
            except Exception:
                pass
        # compute
        texts = [c["text"] for c in self.chunks]
        try:
            resp = self._openai.embeddings.create(model=self._emb_model, input=texts)
            embs = np.array([d.embedding for d in resp.data], dtype=np.float32)
            # L2 normalize for cosine-as-dot-product
            norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9
            embs = embs / norms
            self._chunk_embeddings = embs
            np.savez(cache, emb=embs)
        except Exception:
            self._chunk_embeddings = None

    def _embed_one(self, text: str) -> np.ndarray:
        resp = self._openai.embeddings.create(model=self._emb_model, input=text)
        v = np.array(resp.data[0].embedding, dtype=np.float32)
        v /= (np.linalg.norm(v) + 1e-9)
        return v


def _strip(chunk: Dict, score: float) -> Dict:
    """Return a chunk shaped for callers (no internal token set)."""
    return {
        "id": chunk["id"],
        "category": chunk.get("category", ""),
        "tags": chunk.get("tags", []),
        "text": chunk["text"],
        "score": round(float(score), 3),
    }
