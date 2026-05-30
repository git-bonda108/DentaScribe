"""Transcription Agent — audio bytes → cleaned, dental-corrected transcript.

The agent runs *out of band* via `transcribe_bytes()` BEFORE the deterministic
agent pipeline. Inside the pipeline `.run()` is a near no-op: it logs whether
a transcript is present and validates length.

STT stack (executed in `transcribe_bytes`):

  audio_bytes
      │
      ▼ 1. Audio preprocessing  (utils.audio.preprocess_wav)
      │        VAD-implicit · high-pass · denoise · loudness norm
      │        emits an AudioQuality report (logged to state via the caller)
      │
      ▼ 2. STT engine
      │        Deepgram Nova-3 Medical  (+ dental keyterm boost) ← preferred
      │        OpenAI Whisper API                                ← fallback
      │
      ▼ 3. Post-STT phonetic / lexical correction
      │        utils.text_correction.correct_against_corpus()
      │
      ▼
  cleaned dental transcript

Preprocessing is skipped if the bytes don't look like WAV (raw original bytes
pass straight to the STT engine). Phonetic correction is conservative — it
only snaps to known dental terms when the phonetic distance is small.
"""
from typing import Optional, List
from agents.base import Agent
from agents.knowledge import DentalKnowledge
from core.state import SwarmState


class TranscriptionAgent(Agent):
    name = "transcription"

    def __init__(self, cfg, llm=None, knowledge: Optional[DentalKnowledge] = None):
        super().__init__(cfg, llm)
        self.kb = knowledge
        # Keyterms are computed once. The list of dental procedure names and
        # CDT nomenclature words gives Deepgram a sharp prior over our vocab.
        self._keyterms: List[str] = self._compute_keyterms()
        # Track the most-recent quality report so callers (UI / app.py) can
        # surface a warning without having to pipe extra return values.
        self.last_quality: Optional[dict] = None
        self.last_correction_report: Optional[dict] = None

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------
    def transcribe_bytes(self, audio_bytes: bytes,
                         language: Optional[str] = None,
                         preprocess: bool = True,
                         post_correct: bool = True) -> str:
        # 1) preprocessing (defensive — never fails the call)
        processed = audio_bytes
        if preprocess:
            try:
                from utils.audio import preprocess_wav
                result = preprocess_wav(audio_bytes)
                processed = result.wav_bytes
                self.last_quality = {
                    "before": result.quality_before.to_dict(),
                    "after":  result.quality_after.to_dict(),
                    "stages": result.stages_applied,
                }
            except Exception as e:
                # Likely non-WAV format (webm/ogg). Skip preprocessing.
                self.last_quality = {"error": f"preprocessing skipped: {e}"}

        # 2) STT
        if self.cfg.stt_provider == "deepgram" and self.cfg.deepgram_api_key:
            raw = self._deepgram(processed, language)
            engine = "deepgram-nova3-medical"
        elif self.cfg.openai_api_key:
            raw = self._openai_whisper(processed, language)
            engine = f"openai-{self.cfg.whisper_model}"
        else:
            raise RuntimeError("No STT provider configured. Set OPENAI_API_KEY or DEEPGRAM_API_KEY.")

        # 3) phonetic / lexical correction
        if post_correct and self.kb is not None:
            try:
                from utils.text_correction import correct_against_corpus
                corrected, report = correct_against_corpus(raw, self.kb)
                self.last_correction_report = {
                    "engine": engine, "corrections": report,
                    "count": len(report),
                }
                return corrected
            except Exception as e:
                self.last_correction_report = {"engine": engine, "error": str(e)}
        else:
            self.last_correction_report = {"engine": engine, "corrections": [], "count": 0}
        return raw

    # ------------------------------------------------------------------
    # STT providers
    # ------------------------------------------------------------------
    def _openai_whisper(self, wav_bytes: bytes, language: Optional[str]) -> str:
        from openai import OpenAI
        import io
        client = OpenAI(api_key=self.cfg.openai_api_key)
        bio = io.BytesIO(wav_bytes); bio.name = "audio.wav"
        kwargs = {"model": self.cfg.whisper_model, "file": bio}
        # Anti-hallucination prompt: bias Whisper toward dental vocabulary
        # without telling it what to find. The 'prompt' field acts as a
        # style/vocab hint, not as a transcript prefix to echo.
        kwargs["prompt"] = (
            "Dental consultation between doctor and patient. Vocabulary: "
            "caries, composite, periodontal, scaling, root canal, crown, "
            "Tooth numbers 1 through 32, periapical radiograph, occlusal, "
            "buccal, lingual, mesial, distal, fluoride, prophylaxis, "
            "amoxicillin, ibuprofen, lidocaine."
        )
        if language:
            kwargs["language"] = language
        resp = client.audio.transcriptions.create(**kwargs)
        return resp.text

    def _deepgram(self, wav_bytes: bytes, language: Optional[str]) -> str:
        import httpx
        url = "https://api.deepgram.com/v1/listen"
        # Build the param list. `keyterm` is a Deepgram Nova-3 feature: each
        # term gets a boost in the language model. For dental, this is THE
        # biggest accuracy lever — without it, Nova-3 Medical still does well
        # on common medical vocab but misses CDT-specific terms.
        params: list[tuple[str, str]] = [
            ("model",        self.cfg.deepgram_model),
            ("smart_format", "true"),
            ("punctuate",    "true"),
            ("diarize",      "true"),
            ("paragraphs",   "true"),
            ("filler_words", "false"),
        ]
        if language:
            params.append(("language", language))
        # Deepgram accepts up to ~100 keyterms; we send a curated list.
        for term in self._keyterms[:100]:
            params.append(("keyterm", term))

        headers = {
            "Authorization": f"Token {self.cfg.deepgram_api_key}",
            "Content-Type":  "audio/wav",
        }
        with httpx.Client(timeout=120) as c:
            r = c.post(url, params=params, headers=headers, content=wav_bytes)
            r.raise_for_status()
            data = r.json()

        try:
            alts = data["results"]["channels"][0]["alternatives"][0]
            paragraphs = (alts.get("paragraphs") or {}).get("paragraphs") or []
            if paragraphs:
                lines: list[str] = []
                for p in paragraphs:
                    sp = p.get("speaker", 0)
                    text = " ".join(s["text"] for s in p.get("sentences", []))
                    # Map Deepgram speaker indices to "Doctor"/"Patient" labels
                    # based on a simple heuristic: first speaker is usually
                    # the doctor (who opens the consultation). Diarization
                    # agent will re-attribute if needed.
                    label = "Doctor" if sp == 0 else ("Patient" if sp == 1 else f"Speaker {sp}")
                    lines.append(f"{label}: {text}")
                return "\n".join(lines)
            return alts.get("transcript", "")
        except Exception:
            return data.get("results", {}).get("channels", [{}])[0].get(
                "alternatives", [{}])[0].get("transcript", "")

    # ------------------------------------------------------------------
    # keyterm sourcing
    # ------------------------------------------------------------------
    def _compute_keyterms(self) -> List[str]:
        """Curate a list of dental keyterms for Deepgram boosting.

        Strategy: pick the *hard* terms — CDT procedure names, less-common
        anatomy, conditions, medications. We deliberately avoid common words
        that don't need a boost (e.g. "tooth", "doctor").
        """
        if self.kb is None:
            return _DEFAULT_KEYTERMS
        terms: list[str] = []
        seen: set[str] = set()

        # 1. CDT nomenclature — the words STT engines mangle most.
        for code in self.kb.cdt_codes:
            for word in code["nomenclature"].split():
                w = word.strip("().,;–-").lower()
                if len(w) >= 5 and w not in seen and w not in _COMMON_WORDS:
                    seen.add(w); terms.append(w)
                if len(terms) >= 40:
                    break
            if len(terms) >= 40:
                break

        # 2. Abbreviations expanded — engines hear them as words.
        for abbr in (self.kb.kb.get("abbreviations") or {}):
            w = abbr.lower()
            if w not in seen:
                seen.add(w); terms.append(w)

        # 3. A hand-picked tier of high-value terms (CDT-2026 new codes etc.)
        for w in (
            "periapical", "endodontic", "periodontal", "prophylaxis",
            "amalgam", "composite", "occlusal", "buccal", "lingual",
            "mesial", "distal", "fluoride", "varnish", "panoramic",
            "bitewing", "gingivitis", "periodontitis", "pulpitis",
            "calculus", "abscess", "operculum", "pericoronitis",
            "cracked-tooth testing", "saliva testing",
            "scaling and root planing", "periodontal maintenance",
            "amoxicillin", "clindamycin", "azithromycin",
            "ibuprofen", "acetaminophen", "lidocaine", "articaine",
            "chlorhexidine",
        ):
            if w not in seen:
                seen.add(w); terms.append(w)
        return terms

    # ------------------------------------------------------------------
    # pipeline step (post-STT, just logs whether transcript is present)
    # ------------------------------------------------------------------
    def run(self, state: SwarmState) -> SwarmState:
        if state.raw_transcript:
            state.log(self.name, f"Transcript loaded ({len(state.raw_transcript)} chars)")
            if self.last_quality:
                state.log(self.name, f"Audio quality: {self.last_quality}", level="info")
            if self.last_correction_report:
                n = self.last_correction_report.get("count", 0)
                if n:
                    state.log(self.name, f"Post-STT corrections applied: {n}", level="info")
        else:
            state.log(self.name, "No transcript supplied — skipping", level="warn")
        return state


# Fallback keyterms when no knowledge instance is wired in (shouldn't happen
# under the current orchestrator, but defensive).
_DEFAULT_KEYTERMS = [
    "periapical", "endodontic", "periodontal", "prophylaxis", "amalgam",
    "composite", "occlusal", "buccal", "lingual", "mesial", "distal",
    "amoxicillin", "ibuprofen", "lidocaine",
]

# Common words we DON'T waste keyterm slots on.
_COMMON_WORDS = {
    "tooth", "teeth", "first", "second", "third", "fourth", "additional",
    "each", "image", "images", "or", "of", "and", "the", "to", "for", "with",
    "per", "one", "two", "three", "four", "five", "six",
}
