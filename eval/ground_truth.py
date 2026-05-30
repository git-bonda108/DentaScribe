"""Ground-truth annotations for the demo fixtures.

Authored by reading each transcript carefully and writing down what a
dentist would expect a *signable* note to capture. Keyed by fixture id so
adding fixtures later doesn't disturb the existing keys.

Coverage philosophy:
  * `required=True` entities/codes are the clinical must-haves — missing them
    means the note isn't signable.
  * `required=False` are nice-to-haves that contribute to precision but not
    recall.
  * `forbidden_cdt` is for adversarial cases (e.g. doctor mentions but defers
    a procedure). Empty for the three clean baseline fixtures.
"""
from typing import Dict
from eval.schema import GroundTruth, ExpectedEntity, ExpectedCdt


GROUND_TRUTH: Dict[str, GroundTruth] = {
    # ------------------------------------------------------------------
    # Riya Sharma — UR first molar with deep caries; periapical + composite,
    # contingent endo + crown. Ibuprofen 400mg q6h PRN. PCN allergy noted.
    # ------------------------------------------------------------------
    "demo-001": GroundTruth(
        fixture_id="demo-001",
        expected_entities=[
            ExpectedEntity("tooth", "Tooth 3",
                           aliases=["upper right first molar", "tooth number three", "tooth 3"]),
            ExpectedEntity("condition", "cavity",
                           aliases=["caries", "deep cavity"]),
            ExpectedEntity("condition", "inflammation", required=False),
            ExpectedEntity("procedure", "composite restoration",
                           aliases=["composite", "restoration"]),
            ExpectedEntity("procedure", "root canal",
                           aliases=["endodontic", "endodontic therapy"], required=False),
            ExpectedEntity("procedure", "crown", required=False),
            ExpectedEntity("procedure", "periapical x-ray",
                           aliases=["periapical", "radiograph", "x-ray"]),
            ExpectedEntity("medication", "ibuprofen"),
            ExpectedEntity("anatomy", "buccal cusp", required=False),
            ExpectedEntity("anatomy", "dentin", required=False),
            ExpectedEntity("anatomy", "pulp", required=False),
            ExpectedEntity("symptom", "sharp pain", required=False),
            ExpectedEntity("symptom", "cold sensitivity",
                           aliases=["sensitive to cold", "cold"], required=False),
        ],
        expected_cdt=[
            ExpectedCdt("D0220"),               # periapical first
            ExpectedCdt("D2391", rank_within=8, required=False),   # post composite 1S
            ExpectedCdt("D2392", rank_within=8, required=False),   # post composite 2S
            ExpectedCdt("D3330", required=False),    # endo molar (contingent)
            ExpectedCdt("D2740", required=False),    # crown (contingent)
            ExpectedCdt("D2750", required=False),
        ],
        forbidden_cdt=[],
        required_soap_keywords={
            "chief_complaint": ["pain"],
            "objective": ["tooth"],
            "plan": ["composite"],
        },
        expected_medications=["ibuprofen"],
        max_hallucinations=5,   # cross-provider tolerance; tighten to 0-2
                                # after P3 validator refactor (task #12)    # template fallback emits some scaffolding;
                                 # tighten to 0 once LLM SOAP is on (P2).
        notes="Clean restorative case. PCN allergy is critical — must surface "
              "somewhere in the note or notes_for_doctor.",
    ),

    # ------------------------------------------------------------------
    # Marcus Lee — recall + gingivitis trending peridontitis; scaling +
    # 3-mo perio maintenance; partially-erupted LL third molar → ext referral.
    # ------------------------------------------------------------------
    "demo-002": GroundTruth(
        fixture_id="demo-002",
        expected_entities=[
            ExpectedEntity("condition", "gingivitis"),
            ExpectedEntity("condition", "periodontitis", required=False),
            ExpectedEntity("condition", "calculus"),
            ExpectedEntity("condition", "gingival inflammation",
                           aliases=["inflammation"], required=False),
            ExpectedEntity("procedure", "scaling"),
            ExpectedEntity("procedure", "periodontal maintenance"),
            ExpectedEntity("procedure", "cleaning",
                           aliases=["prophylaxis"]),
            ExpectedEntity("procedure", "extraction"),
            ExpectedEntity("anatomy", "gums",
                           aliases=["gingiva"], required=False),
            ExpectedEntity("anatomy", "third molar",
                           aliases=["wisdom tooth"]),
            ExpectedEntity("symptom", "bleeding gums",
                           aliases=["bleeding"], required=False),
        ],
        expected_cdt=[
            # Doctor diagnoses "early-stage gingivitis trending toward periodontitis"
            # and explicitly says "we'll do a scaling today" — that's D4346 (scaling
            # in presence of generalized inflammation), NOT D1110 (routine prophy).
            # An LLM that codes D1110 here is clinically wrong; D4346 is the right
            # code. D4341 SRP is plausible if perio dx is confirmed.
            ExpectedCdt("D4346"),     # scaling w/ moderate-severe inflammation
            ExpectedCdt("D4341", required=False),    # SRP 4+ teeth/quad (alt)
            ExpectedCdt("D4910"),     # perio maintenance in 3 months
            ExpectedCdt("D1110", required=False),    # patient mentioned cleaning,
                                                     # but scaling was actually performed
            ExpectedCdt("D7220", required=False),    # impacted soft-tissue (referred ext)
            ExpectedCdt("D7230", required=False),
        ],
        forbidden_cdt=[],
        required_soap_keywords={
            "objective": ["calculus"],
            "plan": ["scaling"],
        },
        expected_medications=[],
        max_hallucinations=5,   # cross-provider tolerance; tighten to 0-2
                                # after P3 validator refactor (task #12)
        notes="Hygiene-heavy fixture. Tests the prophy-vs-scaling distinction: "
              "patient said 'cleaning', doctor diagnosed gingival inflammation "
              "and performed scaling (D4346). A clinically-aware model should "
              "NOT code D1110 (routine prophy) here.",
    ),

    # ------------------------------------------------------------------
    # Sofia Garcia — fractured #9 (UL central incisor). Cracked-tooth testing
    # (NEW 2026 D0461) + anterior composite build-up; conditional veneer/crown.
    # Night guard for bruxism.
    # ------------------------------------------------------------------
    "demo-003": GroundTruth(
        fixture_id="demo-003",
        expected_entities=[
            ExpectedEntity("tooth", "Tooth 9",
                           aliases=["upper left central incisor", "tooth number nine"]),
            ExpectedEntity("condition", "fracture",
                           aliases=["crack", "cracked"]),
            ExpectedEntity("procedure", "cracked-tooth testing",
                           aliases=["cracked tooth test", "cracked-tooth test"]),
            ExpectedEntity("procedure", "composite",
                           aliases=["composite build-up", "composite buildup"]),
            ExpectedEntity("procedure", "veneer", required=False),
            ExpectedEntity("procedure", "crown", required=False),
            ExpectedEntity("procedure", "night guard",
                           aliases=["occlusal guard"]),
            ExpectedEntity("anatomy", "incisal edge", required=False),
            ExpectedEntity("symptom", "sensitivity", required=False),
        ],
        expected_cdt=[
            ExpectedCdt("D0461"),     # cracked-tooth testing (CDT 2026 NEW)
            ExpectedCdt("D2330", required=False),    # anterior composite 1S
            ExpectedCdt("D2331", required=False),    # anterior composite 2S
            ExpectedCdt("D2960", required=False),    # veneer chairside
            ExpectedCdt("D2962", required=False),
            ExpectedCdt("D2740", required=False),
            ExpectedCdt("D9944", required=False),    # occlusal guard hard
            ExpectedCdt("D9945", required=False),
        ],
        forbidden_cdt=[],
        required_soap_keywords={
            "plan": ["composite"],
        },
        expected_medications=[],
        max_hallucinations=5,   # cross-provider tolerance; tighten to 0-2
                                # after P3 validator refactor (task #12)
        notes="Exercises CDT 2026 NEW code D0461 (cracked-tooth testing). "
              "Tests that contingent procedures (veneer/crown) are captured "
              "as candidates without being marked high-confidence.",
    ),
}


def get(fixture_id: str) -> GroundTruth:
    if fixture_id not in GROUND_TRUTH:
        raise KeyError(f"No ground truth for fixture {fixture_id!r}")
    return GROUND_TRUTH[fixture_id]
