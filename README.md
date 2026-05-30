# 🦷 DentaScribe — AI Dental Scribe (Streamlit MVP)

> A focused **agent swarm** that listens to a doctor–patient conversation,
> transcribes it, and produces a sign-ready SOAP note with **CDT 2026**
> procedure codes — runnable on any phone or laptop browser.

DentaScribe is the dental-clinical counterpart to your front-desk Dentsi
agent. Same brand, same palette, opposite end of the workflow: where Dentsi
talks **to** the patient, DentaScribe listens **between** the doctor and the
patient.

---

## Highlights

| | |
|---|---|
| **Cross-platform** | Web app via Streamlit → works on Android Chrome, iOS Safari, and desktop. No native app required. |
| **Live mic** | `streamlit-mic-recorder` uses the browser Media-API to capture audio directly. |
| **Best-in-class STT** | Whisper by default; one env var swaps to **Deepgram Nova-3 Medical** (93% accuracy on medical vocabulary). |
| **No hallucinations** | Validator agent flags any term in the note that isn't grounded in the transcript. |
| **CDT 2026 codes** | Maps procedures to current ADA codes — including new 2026 codes like D0426 (saliva testing) and D0461 (cracked-tooth testing). |
| **Demo mode** | Runs end-to-end with **zero API keys** against curated dental conversations. |
| **Export** | PDF + DOCX, both styled in clinical layout. |
| **Records** | SQLite store with search and re-open. |

---

## Agent swarm

```
            ┌──────────────────────────────────────────────────────────┐
 audio ───▶ │  Transcription   Whisper / Deepgram Nova-3 Medical       │
            │  Diarization     prefix-parse → LLM attribution → fallback│
            │  Dental NER      dictionary + grounded LLM enrichment    │
            │  SOAP Note       grounded prompt → template fallback     │
            │  CDT Coder       keyword candidates → LLM re-rank        │
            │  Validator       completeness + hallucination + Rx check │
            └────────────────────────────┬─────────────────────────────┘
                                         ▼
                            SQLite ◀── SwarmState ──▶ PDF / DOCX / JSON
```

Each agent is a small class in `agents/`. The orchestrator is a deterministic
pipeline — no surprise loops, every step logs to the trace.

**Why a swarm and not one big LLM call?**
- **Auditability** — every agent logs to the trace tab.
- **Graceful degradation** — when the LLM is down, the dictionary pass still produces a usable note.
- **Composability** — swap the diarization step for pyannote 3.1 without touching the rest.
- **Grounding** — the validator catches drift before the doctor signs.

---

## Quick start

```bash
# 1. clone / unzip into a folder, then:
cd DentaScribe
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. (optional) drop API keys in .env — without them, demo mode still runs.
cp .env.example .env
$EDITOR .env

# 3. run
streamlit run app.py
# open http://localhost:8501 on your laptop, or your laptop's LAN IP on your phone
```

---

## Configuration

`.env` (see `.env.example`):

| Variable | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude for diarization, NER enrichment, SOAP, CDT re-rank | _(unset → demo)_ |
| `ANTHROPIC_MODEL` | Claude model id | `claude-sonnet-4-6` |
| `OPENAI_API_KEY` | Fallback LLM **and** Whisper STT | _(unset)_ |
| `OPENAI_MODEL` | OpenAI chat model | `gpt-4o` |
| `STT_PROVIDER` | `openai` or `deepgram` | `openai` |
| `WHISPER_MODEL` | OpenAI STT model | `whisper-1` |
| `DEEPGRAM_API_KEY` | Nova-3 Medical key | _(unset)_ |
| `DEEPGRAM_MODEL` | Deepgram model | `nova-3-medical` |
| `DENTASCRIBE_DEMO_MODE` | `auto` / `true` / `false` | `auto` |
| `DENTASCRIBE_DB_PATH` | SQLite file | `dentascribe.db` |

Resolution order: Anthropic → OpenAI → demo (deterministic templates).

---

## Project layout

```
DentaScribe/
├── app.py                      # Streamlit entry point
├── requirements.txt
├── .env.example
├── .streamlit/config.toml      # theme tokens
├── core/
│   ├── config.py               # env → typed Config
│   ├── state.py                # SwarmState dataclass
│   └── db.py                   # SQLite store
├── agents/
│   ├── base.py
│   ├── transcription.py        # Whisper / Deepgram
│   ├── diarization.py          # speaker labelling
│   ├── dental_ner.py           # dictionary + LLM NER (grounded)
│   ├── soap_note.py            # SOAP generator
│   ├── cdt_coder.py            # CDT 2026 mapping
│   ├── validator.py            # QA / anti-hallucination
│   └── orchestrator.py
├── data/
│   ├── cdt_codes_2026.json     # representative subset of CDT 2026
│   └── dental_terms.json       # terminology bank (teeth, conditions, …)
├── exporters/
│   ├── pdf_export.py           # ReportLab
│   └── docx_export.py          # python-docx
├── ui/
│   ├── theme.py                # color tokens
│   ├── styles.py               # custom CSS
│   └── components.py           # hero, card, badge, bubble, chip
└── utils/
    ├── llm.py                  # Anthropic + OpenAI unified client
    └── fixtures.py             # curated dental demo transcripts
```

---

## Design system

Anchored on the Dentsi palette `#1E2327` (text), with a dental-clean
teal/mint primary and a navy depth accent:

| Token | Hex | Use |
|---|---|---|
| `primary` | `#0EA5A4` | Main actions, doctor bubbles, CTAs |
| `primary_dark` | `#067A79` | Hover / pressed |
| `mint` | `#6FE4D6` | Subtle accents |
| `navy` | `#0B2A4A` | Headings, depth, secondary actions |
| `bg` | `#F7FBFC` | App background |
| `surface` | `#FFFFFF` | Cards |
| `amber` | `#F59E0B` | Warnings, unverified terms |
| `red` | `#DC2626` | Critical / errors |
| `green` | `#16A34A` | Success / validated |

The same tokens are used in the PDF and DOCX exports for visual continuity.

---

## What the doctor sees (one consultation, one screen)

1. **SOAP Note** — Chief Complaint • Subjective • Objective • Assessment • Plan • Dental Exam Findings • Medications • Follow-up • *Notes for Doctor* (flags).
2. **CDT Codes** — code chips + table with confidence and rationale.
3. **Transcript** — speaker-bubble view (Doctor in teal, Patient in slate).
4. **Entities** — teeth, conditions, procedures, medications, anatomy, symptoms.
5. **Quality** — completeness score, warnings, unconfirmed terms.
6. **Swarm Trace** — timestamped log of every agent.
7. **Export** — PDF, DOCX, raw JSON.

---

## Anti-hallucination strategy

Three independent layers, any one of which will catch drift:

1. **Prompts are explicit about grounding.** Every LLM call says "use only facts in the transcript."
2. **NER spans are verified.** The LLM returns a `span` for each extracted entity; we drop entities whose span doesn't appear verbatim in the transcript.
3. **Validator agent** scans the final note for noun phrases that aren't in the transcript and surfaces them as *Unverified terms*. The doctor sees them before signing.

CDT codes are additionally **constrained** to a known catalog — the LLM can re-rank and explain, but cannot invent new codes.

---

## Production upgrade path

| Layer | MVP | Production |
|---|---|---|
| STT | Whisper API | **Deepgram Nova-3 Medical** with HIPAA BAA + streaming |
| Diarization | Prefix parsing + LLM | **pyannote 3.1** segmentation, then per-turn Whisper |
| CDT catalog | Bundled subset | Licensed full ADA CDT 2026 dataset, embedding search |
| Storage | SQLite | Encrypted Postgres / Supabase + audit log |
| Auth | None | OIDC + role-based access (doctor, hygienist, admin) |
| Hosting | Streamlit Community Cloud | Containerized, behind reverse proxy, with TLS |

---

## Sources & references

- ADA — [Code on Dental Procedures and Nomenclature (CDT)](https://www.ada.org/publications/cdt)
- ADA News — [New CDT codes you should know for 2026](https://adanews.ada.org/ada-news/2025/september/new-cdt-codes-you-should-know-for-2026/) (60 changes incl. D0426 saliva testing, D0461 cracked-tooth testing)
- Deepgram — [Nova-3 Medical announcement](https://deepgram.com/learn/introducing-nova-3-speech-to-text-api) and [STT comparison 2026](https://deepgram.com/learn/best-speech-to-text-apis-2026)
- pyannoteAI — [Speaker-attributed transcription](https://www.pyannote.ai/blog/stt-orchestration)
- WhisperX — [github.com/m-bain/whisperX](https://github.com/m-bain/whisperX) (transcription + word-level diarization)
- streamlit-mic-recorder — [PyPI](https://pypi.org/project/streamlit-mic-recorder/) (browser Media-API)
- Multi-agent framework landscape — [LangGraph vs CrewAI vs AutoGen 2026](https://www.datacamp.com/tutorial/crewai-vs-langgraph-vs-autogen)
- Dentsi (front-desk counterpart) — [github.com/git-bonda108/Dentsi](https://github.com/git-bonda108/Dentsi)

---

## Disclaimer

DentaScribe is a clinical *scribe*, not a clinical *decision*. Every note
must be reviewed and signed by a licensed dentist before becoming part of
the patient record. CDT codes © American Dental Association.
