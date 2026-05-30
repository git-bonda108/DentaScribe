"""Regression smoke test for the emergency endo sample SOAP + validator."""
from __future__ import annotations

import json
from pathlib import Path

from core.soap_validator import SOAPValidator

DATA = Path(__file__).resolve().parent.parent / "data"
SAMPLE = DATA / "sample_filled_soap_emergency_endo.json"
TRANSCRIPT = DATA / "sample_emergency_endo_transcript.txt"


def main() -> int:
    with open(SAMPLE, encoding="utf-8") as f:
        soap = json.load(f)
    lines = TRANSCRIPT.read_text(encoding="utf-8").splitlines()
    report = SOAPValidator().validate(soap, lines, raise_on_error=False)
    ok = report.ok and report.signability_score >= 0.95
    if not ok:
        print(json.dumps(report.as_dict(), indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
