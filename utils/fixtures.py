"""Curated dental conversation fixtures used in demo mode.

These were authored against real CDT 2026 codes and dental terminology so the
end-to-end demo path is realistic without any external API calls.
"""
from typing import Dict, List

DEMO_TRANSCRIPTS: List[Dict] = [
    {
        "id": "demo-001",
        "patient_name": "Riya Sharma",
        "doctor_name": "Dr. Patel",
        "visit_type": "emergency_limited",
        "language": "en",
        "transcript": (
            "Doctor: Good morning Riya, what brings you in today?\n"
            "Patient: Hi doctor, I've been having sharp pain in my upper right back tooth "
            "for about a week now. It's worse when I drink something cold.\n"
            "Doctor: I see — sensitivity to cold. Any pain with hot drinks or when you bite down?\n"
            "Patient: A little when biting, especially on hard food. No issue with hot.\n"
            "Doctor: Got it. Let me take a look. Open wide please... I can see a deep cavity "
            "on tooth number three — that's your upper right first molar. There's also a small "
            "chip on the buccal cusp. The gums around it look slightly inflamed but no pus.\n"
            "Patient: Is it bad?\n"
            "Doctor: It's reached the dentin and may be approaching the pulp. We'll take a "
            "periapical X-ray to confirm. Most likely we need a composite restoration; if "
            "the pulp is involved we may need a root canal followed by a crown. Any allergies?\n"
            "Patient: I'm allergic to penicillin.\n"
            "Doctor: Noted. For pain I'll recommend ibuprofen 400 milligrams every 6 hours "
            "as needed. Let's schedule the radiograph today and the restoration next week. "
            "Please avoid chewing on the right side until then.\n"
            "Patient: Thank you, doctor."
        ),
    },
    {
        "id": "demo-002",
        "patient_name": "Marcus Lee",
        "doctor_name": "Dr. Chen",
        "visit_type": "periodontal_hygiene",
        "language": "en",
        "transcript": (
            "Doctor: Hello Marcus, here for your six-month cleaning?\n"
            "Patient: Yes, and my gums have been bleeding when I brush.\n"
            "Doctor: How long has that been happening?\n"
            "Patient: About a month. Mostly on the lower front teeth.\n"
            "Doctor: Let me check. I can see moderate calculus build-up on the lingual surfaces "
            "of the lower anteriors and some gingival inflammation. Pocket depths look "
            "around four millimeters in that region — early-stage gingivitis trending toward "
            "periodontitis. We'll do a scaling today and I'd like to schedule a periodontal "
            "maintenance visit in three months. Also recommend an electric toothbrush and "
            "daily flossing. Any other concerns?\n"
            "Patient: My wisdom tooth on the lower left has been sore.\n"
            "Doctor: Let me check — yes, the lower left third molar is partially erupted with "
            "an operculum. We should consider extraction; I'll refer you to an oral surgeon."
        ),
    },
    {
        "id": "demo-003",
        "patient_name": "Sofia Garcia",
        "doctor_name": "Dr. Patel",
        "visit_type": "restorative_direct",
        "language": "en",
        "transcript": (
            "Doctor: Hi Sofia, you mentioned a broken tooth on the phone?\n"
            "Patient: Yes, I cracked my front tooth on a popcorn kernel last night.\n"
            "Doctor: Which one — can you point?\n"
            "Patient: This one — upper left, right next to the middle.\n"
            "Doctor: Tooth number nine, the upper left central incisor. I can see a clear "
            "diagonal fracture line across the incisal edge involving about a third of the "
            "crown. No pulp exposure. Any pain or sensitivity?\n"
            "Patient: A little sensitive to air, no real pain.\n"
            "Doctor: Good — that suggests the pulp is intact. We'll do cracked-tooth testing "
            "first to confirm there's no deeper fracture, then a composite build-up today. "
            "If symptoms persist we may need a veneer or crown. I'll also recommend a "
            "night guard since you mentioned grinding."
        ),
    },
]


def get_demo_transcript(idx: int = 0) -> Dict:
    return DEMO_TRANSCRIPTS[idx % len(DEMO_TRANSCRIPTS)]
