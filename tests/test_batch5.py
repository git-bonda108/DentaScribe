"""Batch 5 — audio + persistence smoke tests (no Deepgram key needed)."""
from __future__ import annotations
import json, pathlib, sys, tempfile
from datetime import datetime, timezone, timedelta

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from audio.transcript_types import Transcript, TranscriptSegment
from audio.diarization import assign_roles
from audio.deepgram_stt import transcribe_demo, _selected_keywords, is_available
from storage import db as sdb
from storage.retention import flag_due_for_purge, purge_flagged


# ---------- audio ----------

def test_transcript_from_plain_text_assigns_speakers():
    raw = "Doctor: open wide.\nPatient: ouch."
    t = Transcript.from_plain_text(raw)
    assert [s.speaker for s in t.segments] == ["provider", "patient"]
    assert t.segments[0].text == "open wide."


def test_transcribe_demo_passthrough():
    t = transcribe_demo("Doctor: hi.\nPatient: hello.")
    assert len(t.segments) == 2
    assert t.plain_text().startswith("Provider: hi.")


def test_keyword_boost_list_is_bounded_and_includes_priority():
    kw = _selected_keywords()
    assert "lidocaine" in kw and "mesial" in kw and "occlusal" in kw
    assert len(kw) <= 50


def test_is_available_returns_bool():
    # Should not raise regardless of env / sdk presence
    assert isinstance(is_available(), bool)


def test_diarization_assigns_roles_from_speaker_labels():
    segs = [
        TranscriptSegment(speaker="unknown", text="let me take a look at tooth nineteen, I'll use lidocaine",
                          start_s=0, end_s=2, speaker_label="spk_0"),
        TranscriptSegment(speaker="unknown", text="it hurts, my tooth has been throbbing",
                          start_s=2, end_s=4, speaker_label="spk_1"),
        TranscriptSegment(speaker="unknown", text="the PA shows a dark spot, we'll do the root canal",
                          start_s=4, end_s=6, speaker_label="spk_0"),
    ]
    t = Transcript(segments=segs)
    assign_roles(t)
    roles = [s.speaker for s in t.segments]
    assert roles[0] == "provider"
    assert roles[1] == "patient"
    assert roles[2] == "provider"


# ---------- persistence ----------

def _tmpdb():
    fd, p = tempfile.mkstemp(suffix=".db")
    return p


def test_db_init_and_basic_encounter_lifecycle():
    p = _tmpdb()
    sdb.init_db(p)
    eid = sdb.create_encounter(
        patient_id="P-1", provider_name="Dr Test", provider_license="TX-1",
        visit_type="emergency", date_of_service="2026-05-31", db_path=p,
    )
    assert eid
    rows = sdb.list_encounters(db_path=p)
    assert len(rows) == 1 and rows[0]["encounter_id"] == eid


def test_db_save_and_retrieve_soap_and_validation():
    p = _tmpdb()
    sdb.init_db(p)
    eid = sdb.create_encounter(patient_id="P-2", provider_name="Dr X",
                               provider_license="TX-2", visit_type="recall",
                               date_of_service="2026-05-31", db_path=p)
    soap = {"metadata": {"encounter_id": eid}, "billing": {"cdt_codes": []}}
    sdb.save_soap_note(eid, soap, validation={"signability_score": 92, "issues": []},
                       signability_score=92, db_path=p)
    current = sdb.get_current_soap(eid, db_path=p)
    assert current["signability_score"] == 92
    assert current["version"] == 1

    # Saving again bumps version and supersedes previous
    sdb.save_soap_note(eid, {"metadata": {"encounter_id": eid}, "billing": {"cdt_codes": []}},
                       signability_score=95, db_path=p)
    current2 = sdb.get_current_soap(eid, db_path=p)
    assert current2["version"] == 2 and current2["signability_score"] == 95


def test_db_audit_log_round_trip():
    p = _tmpdb()
    sdb.init_db(p)
    eid = sdb.create_encounter(patient_id="P-3", provider_name="Dr Y",
                               provider_license="TX-3", visit_type="emergency",
                               date_of_service="2026-05-31", db_path=p)
    recs = [
        {"run_id": "r1", "agent": "Scribe", "model": "claude-sonnet-4-5",
         "status": "ok", "llm_status": "demo", "input_tokens": 100, "output_tokens": 200,
         "latency_ms": 800, "duration_ms": 900, "status_message": "ok",
         "prompt_hash": "abc123"},
        {"run_id": "r1", "agent": "Coder", "model": "claude-sonnet-4-5",
         "status": "ok", "llm_status": "demo", "input_tokens": 50, "output_tokens": 80,
         "latency_ms": 300, "duration_ms": 350, "status_message": "ok",
         "prompt_hash": "def456"},
    ]
    sdb.append_audit_records(recs, encounter_id=eid, db_path=p)
    rows = sdb.audit_log_for_encounter(eid, db_path=p)
    assert len(rows) == 2
    assert {r["agent"] for r in rows} == {"Scribe", "Coder"}


def test_db_attestation_with_signature_hash():
    p = _tmpdb()
    sdb.init_db(p)
    eid = sdb.create_encounter(patient_id="P-4", provider_name="Dr Z",
                               provider_license="TX-4", visit_type="emergency",
                               date_of_service="2026-05-31", db_path=p)
    sid = sdb.save_soap_note(eid, {"x": 1}, signability_score=90, db_path=p)
    att = sdb.save_attestation(encounter_id=eid, soap_id=sid, provider_name="Dr Z",
                               provider_license="TX-4",
                               signed_text="I attest the above is accurate.",
                               db_path=p)
    assert len(att["signature_hash"]) == 64  # sha256 hex


def test_retention_flags_adult_past_5_years_and_purges_dry_then_hard():
    p = _tmpdb()
    sdb.init_db(p)
    old_date = (datetime.now(timezone.utc) - timedelta(days=365 * 6)).date().isoformat()
    new_date = datetime.now(timezone.utc).date().isoformat()
    eid_old = sdb.create_encounter(patient_id="P-old", provider_name="Dr",
                                   provider_license="TX-5", visit_type="recall",
                                   date_of_service=old_date, db_path=p)
    eid_new = sdb.create_encounter(patient_id="P-new", provider_name="Dr",
                                   provider_license="TX-5", visit_type="recall",
                                   date_of_service=new_date, db_path=p)
    due = flag_due_for_purge(db_path=p)
    ids = {r["encounter_id"] for r in due}
    assert eid_old in ids and eid_new not in ids

    dry = purge_flagged([eid_old], dry_run=True, db_path=p)
    assert dry["dry_run"] is True and dry["would_delete"] == 1

    hard = purge_flagged([eid_old], dry_run=False, db_path=p)
    assert hard["deleted"] == 1
    assert eid_old not in {r["encounter_id"] for r in sdb.list_encounters(db_path=p)}


def test_retention_keeps_minor_until_majority_plus_5():
    p = _tmpdb()
    sdb.init_db(p)
    # Minor encounter 6 years ago — adult rule would purge, minor rule should NOT
    eid = sdb.create_encounter(
        patient_id="P-minor", provider_name="Dr", provider_license="TX-6",
        visit_type="recall",
        date_of_service=(datetime.now(timezone.utc) - timedelta(days=365 * 6)).date().isoformat(),
        is_minor=True, db_path=p,
    )
    # Plant a SOAP with DOB that makes patient currently 16 (still a minor)
    dob = (datetime.now(timezone.utc) - timedelta(days=365 * 16)).date().isoformat()
    soap = {"metadata": {"patient": {"dob": dob}}}
    sdb.save_soap_note(eid, soap, signability_score=80, db_path=p)
    due = flag_due_for_purge(db_path=p)
    assert eid not in {r["encounter_id"] for r in due}
