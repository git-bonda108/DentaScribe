"""Inject controlled dental vocabulary into prompts.

The Scribe and Coder agents both pull from here so we have a single source of truth.
"""
from __future__ import annotations
import json, pathlib
from functools import lru_cache

ROOT = pathlib.Path(__file__).parent.parent


@lru_cache(maxsize=1)
def load_glossary() -> dict:
    return json.loads((ROOT / "data" / "dental_glossary.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_cdt_allow_list() -> dict:
    return json.loads((ROOT / "data" / "cdt_allow_list.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_visit_templates() -> dict:
    return json.loads((ROOT / "data" / "visit_type_templates.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_blank_template() -> dict:
    return json.loads((ROOT / "data" / "texas_blank_soap_template.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_schema() -> dict:
    return json.loads((ROOT / "data" / "soap_schema.json").read_text(encoding="utf-8"))


def glossary_compact() -> str:
    """Compact glossary string for prompt injection. Avoids burning tokens on metadata."""
    g = load_glossary()
    lines = []
    for category in ["anatomy", "conditions", "procedures", "materials", "anesthetics"]:
        if category not in g:
            continue
        lines.append(f"## {category.upper()}")
        for term, defn in g[category].items():
            lines.append(f"- {term}: {defn}")
    return "\n".join(lines)


def cdt_compact() -> str:
    """Compact CDT list for the Coder prompt. Code + short description only."""
    cdt = load_cdt_allow_list()
    return "\n".join(f"- {c['code']}: {c['description']}" for c in cdt["codes"])


def asr_keywords() -> list[str]:
    """Returns the list of keywords to boost in Deepgram STT."""
    g = load_glossary()
    keywords = set()
    for cat in ["anatomy", "conditions", "procedures", "materials", "anesthetics"]:
        keywords.update(g.get(cat, {}).keys())
    # add ASR corrections (the *correct* forms)
    keywords.update(g.get("asr_corrections", {}).values())
    return sorted(keywords)
