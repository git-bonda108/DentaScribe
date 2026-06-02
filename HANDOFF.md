# DentaScribe — Production Handoff

> AI-assisted clinical scribe for the Dallas, TX dental market.
> Records doctor↔patient consultations, drafts a Texas-compliant SOAP note,
> runs a second-opinion safety review, and lets the provider attest and
> sign — before the patient leaves the operatory.

---

## 1. Executive Summary

**Problem.** Dentists spend 25–40% of clinical time on charting. Manual SOAP
notes are slow, error-prone on CDT codes, and miss safety considerations
(drug interactions, missing TSBDE-required fields). Existing scribe tools
(Suki, Abridge) are medical-focused, not dental-specialized.

**Solution.** A 6-agent AI scribe specialized for dental encounters:

- **Captures** transcripts via live mic (WebRTC + Deepgram Nova-3 Medical),
  uploaded audio, paste, or TTS-synthesized samples.
- **Drafts** a Texas-compliant SOAP that quotes the transcript verbatim
  (no hallucinations).
- **Codes** CDT 2026 procedures from a sealed allow-list (no invention).
- **Reviews** the note for safety (drug interactions, allergy conflicts),
  documentation gaps, and billing misses.
- **Coaches** the provider live during the consultation — flagging
  history gaps, diagnostic tests to consider, codes accumulating.
- **Exports** signable DOCX + PDF with attestation block, AI-disclosure,
  and audit footer.

**Status.** MVP. 102 unit tests passing. End-to-end live recording proven
on real audio. Single-tenant; runs locally. Ready for pilot deployment
behind a TURN server with HIPAA-eligible backends.

**Pricing model.** ≈ $0.05–0.10 per consultation in LLM tokens
(Anthropic Claude Sonnet 4.5 + Deepgram). Coach mode adds $0.10–0.20.
Total per-encounter compute cost: ~$0.15–0.30.

---

## 2. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Type hints, structural pattern matching, modern stdlib |
| UI | Streamlit 1.57 | Rapid clinical UX iteration; native `chat_message`, `fragment` for live updates |
| LLM (primary) | Anthropic Claude Sonnet 4.5 (`claude-sonnet-4-5`) | Strong clinical reasoning, native tool-use, HIPAA-eligible on Enterprise |
| LLM (fallback / cost) | OpenAI GPT-4o-mini | TTS path + non-clinical utility |
| STT (live) | Deepgram Nova-3 Medical via WebSocket | Medical-tuned, sub-second interim transcripts, diarization, BAA on paid plans |
| STT (batch) | Deepgram REST | Uploaded audio path |
| TTS (demo) | ElevenLabs Turbo v2.5 | Two-voice (doctor/patient) realism; falls back to OpenAI TTS |
| Audio plumbing | streamlit-webrtc, aiortc, PyAV | WebRTC mic in, frame resampling |
| Audio DSP | scipy, noisereduce, numpy | Pre-STT spectral gating + loudness norm |
| Schema | JSON Schema (Draft-07) | Validates every LLM SOAP output |
| Exports | python-docx, reportlab | Clinical-grade DOCX + PDF |
| Storage | SQLite (MVP) | Encounters, transcripts, SOAP notes, audit log, attestations |
| Compliance | Deterministic Python rules | TSBDE 22 TAC §108.8 anchor checklist; no LLM trust |
| Testing | pytest 9 | 102 unit tests across foundation, agents, audio, exports, coach |

---

## 3. Architecture

### High-level data flow

```
              ┌─────────────────────────────────────────────┐
  Mic ─►──►── │  WebRTC (streamlit-webrtc)                  │
              │           │ 48 kHz stereo float frames      │
              │           ▼                                 │
              │  PyAV AudioResampler  → 16-bit mono 16 kHz  │
              │           │                                 │
              │           ▼                                 │
              │  Deepgram Nova-3 Medical (WebSocket)        │
              │   • interim + final transcripts             │
              │   • diarization across full session         │
              │           │                                 │
              │           ▼                                 │
              │  LiveDeepgramSession (thread-safe state)    │
              │           │                                 │
              └───────────┼─────────────────────────────────┘
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
  Live transcript    Coach agent    On STOP:
  (st.fragment      (turn-change   full transcript
   1s refresh)       + 15s ceil)   → agent swarm
                                       │
                                       ▼
   ┌───────────────────────────────────────────────────────┐
   │  Orchestrator (agents/swarm.py)                       │
   │                                                       │
   │  1. ScribeAgent       → SOAP JSON (grounded)          │
   │  2. ComplianceAgent   → TSBDE checklist (det.)        │
   │  3. CoderAgent        → CDT codes (allow-list)        │
   │  4. SOAPValidator     → structural + grounding +      │
   │                          CDT + Texas rules            │
   │  5. SecondOpinionAgent → safety / billing flags       │
   │                                                       │
   │  Output: SwarmRun {soap, validation, results,         │
   │                    audit_records, duration_ms}        │
   └─────────────┬─────────────────────────────────────────┘
                 │
                 ▼
   ┌─────────────────────────────────────────────────────┐
   │  UI tabs (Streamlit)                                │
   │   • Conversation   (st.chat_message)                │
   │   • SOAP note      (S/O/A/P/Billing/Compliance)     │
   │   • Recommendations  (doctor-facing summary)        │
   │   • Second-Opinion   (peer-review flags)            │
   │   • Tooth chart    (SVG 1-32 highlight)             │
   │   • Audit & Cost   (per-agent breakdown)            │
   │                                                     │
   │  Attestation gate → DOCX / PDF / JSON export        │
   └─────────────────────────────────────────────────────┘
```

### Agent contracts

Each agent has a single job and a strict contract:

| # | Agent | Kind | Inputs | Outputs |
|---|---|---|---|---|
| 1 | **Scribe** | Claude | transcript, visit_type | structured SOAP JSON; every claim quotes a transcript span |
| 2 | **Compliance** | Deterministic | SOAP, clinic env, patient | TSBDE 22 TAC §108.8 checklist booleans |
| 3 | **Coder** | Claude (constrained) | SOAP plan + procedures | CDT 2026 codes from `cdt_allow_list.json`; never invents codes |
| 4 | **Validator** | Deterministic | full SOAP + transcript + schema | 4-layer report: structural, grounding, CDT allow-list, Texas; signability 0–100 |
| 5 | **Second-Opinion** | Claude | SOAP, transcript, codes | bounded peer-review flags (6 categories) with severity + evidence |
| 6 | **Dental Coach** (live only) | Claude + 6 tools | rolling transcript | ≤3 recommendations per call, deduped, grounded |

### Coach tools (Claude tool-use)

| Tool | Purpose |
|---|---|
| `check_drug_interaction(d1, d2)` | Watch-list lookup over `drugs_common`; class-based (lisinopril → ACE inhibitor → flags NSAID interaction) |
| `lookup_dental_term(term)` | Glossary definition by category |
| `cdt_candidates_for(procedure_text)` | IDF-weighted top-3 CDT codes from the allow-list |
| `assess_pulpal_status(symptoms)` | Heuristic: maps symptoms to pulpal differential + recommended tests |
| `required_objective_for(visit_type)` | Visit-type required fields + CDT allow-list |
| `check_tsbde_anchor_block(soap)` | Which TSBDE fields are still missing |

---

## 4. Workflow

### 6 steps from patient walk-in to signed chart

1. **Capture** — Click "🎤 Live mic" → START. WebRTC streams audio; Deepgram returns words within ~500ms with diarization.
2. **Swarm** — Click "🛑 Stop & finalize". Five agents run in sequence on the recorded transcript.
3. **Coach (live)** — During the recording, the Dental Coach watches the rolling transcript and surfaces recommendations on speaker-turn change or every 15s.
4. **Review** — 6 result tabs populate. Every clinical claim is grounded in a transcript quote (hover to see).
5. **Attest & Sign** — Signability gates sign-off (≥85 score + zero errors). Provider types name; AI-assisted disclosure auto-marks.
6. **Export** — Download printable DOCX, PDF, or raw JSON. Audit log persists in SQLite.

### Input modes

| Mode | Path | LLM mode |
|---|---|---|
| 📝 **Paste** | Type or paste transcript | Demo if matches locked sample, else Live |
| 📁 **Upload** | Drop .wav/.mp3/.m4a | Always Live |
| 🎤 **Live mic** | WebRTC streaming | Always Live |
| 🔊 **Synthesize** | TTS-generate then run STT roundtrip | Live or Demo |

---

## 5. Repository Layout

```
DentaScribe/
├── app.py                          # Streamlit entrypoint, sidebar
├── pyproject.toml                  # uv-managed deps; deepgram-sdk pinned <4
├── requirements.txt                # pip-compatible
├── CLAUDE.md                       # Master instructions for Claude Code sessions
├── README.md
├── HANDOFF.md                      # ← this file
├── .env.example                    # template; never commit .env
│
├── agents/                         # 6 specialized agents
│   ├── base.py                     # BaseAgent + AgentResult contract
│   ├── clinical_agents.py          # Scribe + Coder runners
│   ├── compliance_agent.py         # TSBDE checklist (deterministic)
│   ├── second_opinion_agent.py     # Peer-review flags
│   ├── coach_agent.py              # Live coach with 6 tools
│   └── swarm.py                    # Orchestrator + SwarmRun
│
├── audio/                          # STT pipeline
│   ├── deepgram_stt.py             # REST (batch + uploaded) STT
│   ├── live_streaming.py           # LiveDeepgramSession (WebSocket)
│   ├── transcript_types.py         # Transcript / TranscriptSegment
│   ├── diarization.py              # Speaker role assignment
│   ├── post_correction.py          # ASR dict + phonetic fuzzy match
│   └── tts_synthesis.py            # ElevenLabs + OpenAI TTS fallback
│
├── core/
│   ├── config.py                   # .env → Config dataclass
│   ├── cost.py                     # Token → USD math
│   ├── llm_client.py               # Single Anthropic wrapper (demo + live)
│   ├── glossary_loader.py          # Cached corpus + CDT loaders
│   ├── soap_schema.py              # Path constants
│   └── soap_validator.py           # 4-layer validator
│
├── data/                           # Curated corpus + schemas
│   ├── soap_schema.json            # JSON Schema (Draft-07), TSBDE-compliant
│   ├── texas_blank_soap_template.json
│   ├── visit_type_templates.json   # Required fields + CDT allow-list per visit
│   ├── cdt_codes_2026.json         # Subset; license full ADA for prod
│   ├── cdt_allow_list.json         # 38-code curated subset
│   ├── dental_glossary.json        # Anatomy, conditions, procedures, drugs, ASR
│   ├── dental_knowledge.json       # Track-A RAG corpus (P2 work)
│   ├── tooth_norm.py               # Universal/FDI/Palmer normalizer
│   ├── surface_norm.py             # M/O/D/B/L/F/I normalizer
│   └── samples/                    # Reference transcripts + filled SOAPs
│
├── exports/
│   ├── soap_docx_template.py       # python-docx — printable SOAP
│   └── soap_pdf_template.py        # reportlab — paginated PDF
│
├── prompts/
│   ├── soap_prompt.py              # Scribe agent system + user
│   └── clinical_prompts.py         # Coder + Second-Opinion prompts
│
├── storage/
│   ├── db.py                       # SQLite — encounters/SOAP/audit/attestations
│   └── retention.py                # Texas 5-yr / minor+5-yr sweep
│
├── ui/
│   ├── theme.py                    # Light clinical design system
│   ├── styles.py
│   ├── components/
│   │   ├── transcript_panel.py
│   │   ├── agent_swarm.py
│   │   ├── tooth_chart.py
│   │   ├── review_panel.py
│   │   ├── validator_panel.py
│   │   ├── attestation.py
│   │   ├── export_buttons.py
│   │   ├── recommendations.py      # Doctor-facing summary
│   │   └── live_recording.py       # WebRTC + 2-pane Coach/Transcript
│   └── pages/
│       ├── record_page.py          # Main capture + run flow
│       ├── audit_page.py           # Per-encounter agent log
│       ├── admin_page.py           # Texas retention sweep
│       └── how_it_works_page.py    # Workflow explainer
│
├── utils/
│   ├── audio.py                    # Spectral preprocess (high-pass + denoise + normalize)
│   ├── llm.py                      # Legacy LLM client
│   ├── text_correction.py          # Phonetic + edit-distance correction
│   ├── fixtures.py                 # Demo transcripts
│   └── tooth_norm.py / surface_norm.py / transcript_normalize.py
│
├── eval/                           # Regression harness (Track A)
│   ├── schema.py                   # GroundTruth + MetricResult dataclasses
│   ├── metrics.py                  # 8 metrics + signability composite
│   ├── runner.py                   # CLI: python -m eval
│   ├── ground_truth.py             # Annotations per fixture
│   ├── stt_smoke.py                # TTS-roundtrip STT test
│   └── reports/baseline.json       # Captured baseline (0.982 signability)
│
└── tests/                          # pytest suite — 102 tests
    ├── test_smoke.py / test_batch[2-6].py
    ├── test_soap_exports.py        # DOCX + PDF generators
    ├── test_coach_agent.py         # 23 tests (6 tools + dedupe + demo coach)
    ├── test_post_correction.py     # 8 tests (dict + fuzzy + protected)
    ├── test_tts_synthesis.py       # 9 tests (parse + stitch + resample)
    └── test_cost.py                # 6 tests (token math + format)
```

---

## 6. Setup

### Local development

```bash
git clone https://github.com/git-bonda108/DentaScribe.git
cd DentaScribe

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — at minimum: ANTHROPIC_API_KEY + DEEPGRAM_API_KEY
# Optional: ELEVENLABS_API_KEY (for two-voice TTS),
#           OPENAI_API_KEY (for fallback TTS / chat)

streamlit run app.py
# open http://localhost:8501
```

### Env vars

| Var | Required for | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Live mode swarm + coach | Required for Live; Demo runs without it |
| `DEEPGRAM_API_KEY` | All STT (live + upload) | Required for any audio |
| `DEEPGRAM_MODEL` | STT | Default `nova-3-medical` |
| `ELEVENLABS_API_KEY` | Two-voice TTS in Synthesize tab | Optional; falls back to OpenAI TTS |
| `OPENAI_API_KEY` | TTS fallback / additional verification | Optional |
| `DENTASCRIBE_DEMO_MODE` | Force `true` / `false` / `auto` | Default auto |
| `DENTASCRIBE_DB_PATH` | SQLite location | Default `dentascribe.db` |

### Running tests

```bash
pytest tests/ -v                    # 102 unit tests
python -m eval                       # regression harness
python -m eval.stt_smoke             # TTS-roundtrip STT smoke
```

---

## 7. Compliance (TSBDE 22 TAC §108.8)

The Texas State Board of Dental Examiners requires every patient record to
include:

| Field | Enforced by |
|---|---|
| Patient identification | Compliance agent + Validator |
| Provider name + TSBDE license # | Compliance + attestation block |
| Date of service | Encounter anchor |
| Chief complaint + history | Scribe SOAP `subjective.chief_complaint` |
| Diagnosis + plan | Scribe SOAP `assessment.diagnoses` + `plan.procedures_today` |
| Treatment, materials, medications | Plan procedures + prescriptions |
| Informed consent flag | Compliance agent (`patient.consent_on_file`) |
| Radiograph reference | Validator warning if rads taken without findings |
| Anesthetic record | Compliance + Validator |
| Provider signature | Attestation gate (signability ≥ 85) |

**Retention.** Adult 5 years from last DOS; minor → age of majority + 5 years.
Enforced by `storage/retention.py` (admin-confirmed two-step purge — never
auto-deletes).

**AI-assisted disclosure.** Every SOAP export carries the disclosure footer:
"This SOAP note was drafted by DentaScribe (an AI-assisted clinical scribe)
and reviewed by the signing provider before signature."

---

## 8. Production Deployment Checklist

### Critical (blocks PHI workloads)

- [ ] **HIPAA backend.** SQLite is fine for MVP; production needs
      SQLCipher OR Postgres on a BAA-covered host (AWS RDS / GCP CloudSQL with BAA).
- [ ] **BAA from every PHI-touching vendor.**
      - Anthropic: Claude on Enterprise has a BAA path
      - Deepgram: BAA available on paid plans
      - OpenAI: ChatGPT Enterprise has BAA; API access requires separate BAA
      - ElevenLabs: confirm BAA before any real PHI synthesis
- [ ] **TURN server for WebRTC.** Google STUN works on home networks but
      most clinical Wi-Fi sits behind corporate NAT. Use Twilio, Cloudflare
      TURN, or self-hosted coturn.
- [ ] **TLS everywhere.** Streamlit Community Cloud is fine for dev; for
      production deploy behind a reverse proxy with valid certs.
- [ ] **PHI de-identification pre-LLM (optional, recommended).** Presidio
      or a regex layer to strip patient names before tokens leave your VPC.
- [ ] **Audit log on every state mutation.** Already wired in
      `storage/db.py` — just needs frontend hooks on each Save/Sign/Export.
- [ ] **Encryption at rest** for audio + SOAP + DB.

### Operational

- [ ] **Cost telemetry per consultation.** Already shown in UI; add a
      monthly aggregate to the admin page.
- [ ] **Token budgets** per encounter (hard cap so a runaway prompt can't
      cost $5).
- [ ] **Multi-tenancy** — per-practice isolated data; SQLite needs to move
      to per-practice schemas or a tenant-id column.
- [ ] **Auth.** OIDC with doctor / hygienist / admin roles. Sign-off
      restricted to doctors.
- [ ] **Monitoring + alerting** — error rates, p95 latency on the swarm,
      Deepgram WS connection drops.
- [ ] **Backup + DR** — daily DB snapshots; weekly cold backup.

### Differentiation (post-launch)

- [ ] **Real diarization with pyannote 3.1** before Deepgram, for more
      reliable speaker separation on noisy operatory audio.
- [ ] **Full ADA CDT 2026 catalog** via licensed embeddings index;
      keep the deterministic keyword fallback for offline.
- [ ] **Per-practice fine-tuning** of the Coach agent's recommendation
      style.
- [ ] **Insurance code cross-walk** (CDT ↔ CPT for sleep apnea, etc.).

---

## 9. What's Done vs Known Gaps

### ✓ Done

- 6-agent swarm (Scribe + Compliance + Coder + Validator + Second-Opinion + live Coach)
- JSON Schema with 4-layer validator (structural + grounding + CDT allow-list + Texas)
- TSBDE 22 TAC §108.8 compliance checklist (deterministic)
- Live audio: WebRTC mic → Deepgram WebSocket → real-time transcript with interim text
- Per-tab input flows (Paste / Upload / Live mic / Synthesize) — each owns its Run
- DOCX + PDF SOAP generators (printable, signable, branded)
- Attestation block with signability gate
- Anti-hallucination: every clinical claim quotes a transcript span; CDT codes from sealed allow-list
- Coach agent with 6 tool calls (drug interaction, pulpal status, CDT candidates, TSBDE check, glossary, visit-type requirements)
- Cost telemetry per agent and per consultation
- SQLite persistence for encounters, transcripts, SOAP versions, audit log, attestations
- Texas retention sweep (admin page)
- 102 unit tests passing
- Dental-tuned design system (Arini-inspired light clinical theme; Oswald display headlines)

### ⚠ Known gaps (P3+)

- **TURN server config** (currently uses Google STUN only — fine for dev)
- **HIPAA layer** (encrypted DB, BAA-covered hosts, PHI de-id)
- **OIDC auth + roles** (currently no auth)
- **pyannote 3.1 diarization** (Deepgram diarization is good but pyannote on raw audio is the gold standard for clinical audio)
- **Validator's stopword approach** — works but is whack-a-mole; needs corpus-first refactor (tracked as task #12)
- **Real audio fixtures + WER metric** in the eval harness (currently text-only)
- **Token budgets** per encounter — implemented in spirit, not enforced as a hard cap
- **Per-practice tenancy + auth-aware retention**

---

## 10. Cost Model

Per-encounter compute cost (live mode, Anthropic Claude Sonnet 4.5):

| Agent | Tokens (in/out) | Cost |
|---|---|---|
| Scribe | ~2,500 / 1,500 | $0.030 |
| Compliance | 0 / 0 (deterministic) | $0 |
| Coder | ~600 / 400 | $0.008 |
| Validator | 0 / 0 (deterministic) | $0 |
| Second-Opinion | ~2,500 / 1,200 | $0.026 |
| **Subtotal** | **~5,500 / 3,100** | **~$0.06** |

Coach mode (live recording only) adds ~5–8 calls at $0.01–0.025 each
= **+$0.10–0.20** per consultation.

Deepgram Nova-3 Medical: $0.0095/min via API → ~$0.05 for a 5-minute visit.

**Total per live consultation: ~$0.15–0.30.**

---

## 11. Demo Script (5-minute pitch)

1. Open http://localhost:8501 → **🩺 Record**.
2. Sidebar: confirm **Live (Claude)** mode + **🩺 Coach mode ON**.
3. **🎤 Live mic** tab → click START → grant mic permission.
4. Diagnostic strip turns teal: "● Live — words arrive as you speak".
5. Speak a realistic dental exchange (30–60 sec):
   - "Hi, what brings you in?"
   - "Severe pain on lower left tooth 19 for three days, throbs at night."
   - "Let me take a periapical X-ray. That looks like irreversible pulpitis."
   - "I'm on lisinopril."
   - "For pain, take ibuprofen 400mg every 6 hours."
6. The **left pane (Live coaching)** lights up with safety + differential cards:
   - 🚨 **Safety: Ibuprofen + lisinopril** — suggests acetaminophen
   - 🩺 **Differential**: lingering nocturnal pain → cold test for irreversible pulpitis
7. Right pane fills with diarized bubbles in real time.
8. Click **🛑 Stop & finalize**.
9. Five agents progress in `st.status`. Result tabs populate:
   - **SOAP** — your actual conversation, not a demo
   - **Recommendations** — clinical summary
   - **Second-Opinion** — drug interaction flag with verbatim evidence quote
   - **Tooth chart** — #19 lit up
   - **Audit & Cost** — ~$0.10 with per-agent breakdown
10. **📤 Export** → **📄 Clinical SOAP (DOCX)** — provider signs, exports.

---

## 12. Contact

- Repo: <https://github.com/git-bonda108/DentaScribe>
- Author: see CLAUDE.md
- Build provenance: every commit message documents what changed, what
  tests passed, and what the regression-eval baseline was at that
  snapshot.

---

*This handoff doc reflects the state of the repo at commit time. Run
`git log --oneline` for the live commit history and `pytest tests/ -q`
to verify the current test count.*
