"""QA / Validator Agent — anti-hallucination & completeness checks.

Runs AFTER the SOAP note is generated. It flags:
  * Terms in the note that are not grounded in EITHER the transcript OR the
    dental knowledge corpus (potential hallucination).
  * Required note sections that are empty.
  * Medications mentioned without a dose, frequency, or route.
  * When soap_structured is present: JSON Schema, transcript-span grounding,
    CDT allow-list, and Texas/TSBDE soft rules (core.soap_validator).

Outputs a QualityReport in state.qa.
"""
import re
from agents.base import Agent
from core.soap_validator import SOAPValidator
from core.state import SwarmState, QualityReport
from agents.knowledge import DentalKnowledge, _stem


REQUIRED_SECTIONS = (
    "chief_complaint", "subjective", "objective", "assessment", "plan"
)

# Function words / common English verbs that can never be a clinical hallucination.
# We filter at candidate-extraction time so they don't pollute unconfirmed_terms.
# Clinical synonyms ("caries", "presenting") live in the knowledge corpus, not here.
#
# TODO(p3): replace this list with a proper "common English top-N words"
# filter. Token-level whack-a-mole isn't sustainable, but a real wordlist
# adds a dependency we don't need for MVP signoff.
_STOPWORDS = frozenset({
    # determiners / pronouns / be-verbs
    "this", "that", "these", "those", "there", "here", "they", "them", "their",
    "have", "has", "had", "been", "being", "will", "would", "could", "should",
    "shall", "might", "must", "does", "doing", "done", "into", "onto",
    # prepositions / conjunctions
    "with", "without", "after", "before", "during", "while", "since", "until",
    "above", "below", "between", "among", "across", "through", "around",
    "than", "then", "also", "well", "very", "much", "more", "most", "less",
    "such", "some", "many", "each", "both", "either", "neither", "however",
    "therefore", "because", "though", "although",
    # narrative / connector verbs
    "show", "shows", "showed", "showing", "perform", "performs", "performed",
    "performing", "consider", "considered", "considering", "proceed",
    "proceeded", "proceeding", "report", "reports", "reported", "reporting",
    "indicate", "indicates", "indicated", "indicating", "include", "includes",
    "included", "including", "begin", "begins", "began", "beginning", "start",
    "starts", "started", "starting", "complete", "completes", "completed",
    "completing", "continue", "continues", "continued", "continuing",
    "remain", "remains", "remained", "remaining",
    "advise", "advises", "advised", "advising", "suggest", "suggests",
    "suggested", "suggesting", "appear", "appears", "appeared", "appearing",
    "seem", "seems", "seemed", "make", "makes", "made", "making",
    "take", "takes", "took", "taken", "taking", "look", "looks", "looked",
    "looking", "feel", "feels", "felt", "feeling", "tell", "tells", "told",
    "telling", "ask", "asks", "asked", "asking", "give", "gives", "gave",
    "given", "giving", "want", "wants", "wanted", "wanting", "need", "needs",
    "needed", "needing", "know", "knows", "knew", "known", "knowing",
    "help", "helps", "helped", "helping",
    # adjectives / adverbs / hedges that aren't clinical claims by themselves
    "slight", "slightly", "small", "smaller", "smallest", "large", "larger",
    "largest", "good", "better", "best", "poor", "worse", "worst", "fine",
    "okay", "great", "high", "higher", "low", "lower", "long", "longer",
    "short", "shorter", "wide", "narrow", "deep", "deeper", "shallow",
    "possibly", "probably", "likely", "unlikely", "definitely", "certainly",
    "approximately", "approximate", "roughly", "exactly", "nearly", "almost",
    "around", "about", "around", "surrounding", "near", "nearby", "next-to",
    "general", "generally", "specifically", "particular", "particularly",
    "overall", "additional", "additionally", "further", "another", "other",
    "others", "ongoing", "regular", "routine", "standard", "normal",
    # general filler
    "today", "tomorrow", "yesterday", "next", "last", "first", "second", "third",
    "soon", "later", "again", "still", "even", "just", "only", "really",
    "currently", "previously", "subsequently",
    # hedge words / quantifiers / abstract nouns
    "potential", "potentially", "possible", "possibility", "possibilities",
    "actual", "actually", "necessary", "necessarily", "needed", "needs",
    "important", "importantly", "significant", "significantly", "minor",
    "major", "critical", "key", "main", "primary", "secondary", "various",
    "several", "multiple", "single", "common", "uncommon", "rare", "frequent",
    "infrequent", "occasional", "occasionally", "often", "sometimes", "rarely",
    "always", "never", "extent", "amount", "level", "degree", "type", "kind",
    "form", "way", "ways", "manner", "approach", "method", "presence", "absence",
    "case", "cases", "instance", "instances", "situation", "situations",
    "condition", "conditions", "state", "states", "issue", "issues", "matter",
    "matters", "concern", "concerns", "concerned", "thing", "things",
    # reporting verbs / phrasings the LLM uses to narrate
    "reveal", "reveals", "revealed", "revealing", "confirm", "confirms",
    "confirmed", "confirming", "note", "notes", "noting", "describe",
    "describes", "described", "describing", "discuss", "discusses",
    "discussed", "discussing", "review", "reviews", "reviewed", "reviewing",
    "explain", "explains", "explained", "explaining", "mention", "mentions",
    "mentioned", "mentioning", "observe", "observes", "observed", "observing",
    "recommend", "recommends", "recommended", "recommending", "recommendation",
    "schedule", "schedules", "scheduled", "scheduling", "verify", "verifies",
    "verified", "verifying", "establish", "established", "indicate", "indicates",
    "indicated", "indicating",
    # Additional narrative vocabulary observed in Claude-generated SOAP
    # (gpt-4o uses a different but overlapping set; we union both).
    "order", "orders", "ordered", "ordering", "place", "places", "placed",
    "placing", "find", "finds", "found", "finding", "address", "addresses",
    "addressed", "addressing", "instruct", "instructs", "instructed",
    "instructing", "treat", "treats", "treated", "treating", "treatment",
    "manage", "manages", "managed", "managing", "extend", "extends",
    "extended", "extending", "extension", "determine", "determines",
    "determined", "determining", "associate", "associates", "associated",
    "associating", "association", "affect", "affects", "affected",
    "affecting", "measure", "measures", "measured", "measuring",
    "accumulate", "accumulates", "accumulated", "accumulating",
    "accumulation", "consider", "considers", "considered", "considering",
    "consideration", "assume", "assumes", "assumed", "assuming",
    "assumption", "favor", "favors", "favored", "favorable", "unfavorable",
    "reassess", "reassesses", "reassessed", "reassessing", "reassessment",
    "consistent", "inconsistent", "compatible", "incompatible",
    "visible", "visual", "audible", "tactile", "palpable", "invisible",
    "inspect", "inspects", "inspected", "inspection",
    "detect", "detects", "detected", "detecting", "detection",
    "status", "history", "context", "outcome", "outcomes", "result", "results",
    "same", "different", "similar", "various", "varying", "varied",
    "proximity", "distance", "relation", "relationship",
    "target", "targets", "targeted", "targeting", "counsel", "counsels",
    "counseled", "counseling", "remainder", "encounter", "encounters",
    "encountered", "encountering", "document", "documents", "documented",
    "documenting", "prior", "subsequent", "preceding", "following",
    "ahead", "behind", "upcoming", "imminent",
})


class ValidatorAgent(Agent):
    name = "validator"

    def __init__(self, cfg, llm=None, knowledge: DentalKnowledge = None):
        super().__init__(cfg, llm)
        self.kb = knowledge or DentalKnowledge()
        self._soap_validator = SOAPValidator()

    def run(self, state: SwarmState) -> SwarmState:
        report = QualityReport()
        soap = state.soap
        transcript = (state.raw_transcript or
                      "\n".join(s.text for s in state.segments)).lower()
        transcript_stems = {_stem(t) for t in re.findall(r"[a-zA-Z]{3,}", transcript)}

        # 1) completeness
        present = 0
        for sec in REQUIRED_SECTIONS:
            if getattr(soap, sec, "").strip():
                present += 1
            else:
                report.warnings.append(f"Missing or empty SOAP section: {sec}")
        report.completeness_score = round(present / len(REQUIRED_SECTIONS), 2)

        # 2) hallucination check across the clinically-meaningful sections.
        seen_terms = set()
        for field_name in ("objective", "assessment", "plan", "dental_exam"):
            body = (getattr(soap, field_name, "") or "").lower()
            for token in self._candidate_terms(body):
                if token in seen_terms:
                    continue
                seen_terms.add(token)
                if self._is_grounded(token, transcript, transcript_stems):
                    continue
                report.unconfirmed_terms.append(f"{field_name}: '{token}'")

        report.unconfirmed_terms = report.unconfirmed_terms[:12]

        # 3) medications: require dose+freq if present
        for m in soap.medications:
            low = m.lower()
            has_dose = bool(re.search(r"\d+\s?(mg|mcg|ml|g)\b", low))
            has_freq = any(w in low for w in (
                "daily", "twice", "once", "every", "hours", "as needed", "prn", "bid", "tid"
            ))
            if not (has_dose and has_freq):
                report.warnings.append(f"Medication missing dose/frequency: '{m}'")

        # 4) structured SOAP validation (schema + grounding + CDT allow-list)
        if state.soap_structured:
            lines = [ln.strip() for ln in (state.raw_transcript or "").splitlines() if ln.strip()]
            if state.segments and not lines:
                lines = [f"{s.speaker}: {s.text}" for s in state.segments]
            vrep = self._soap_validator.validate(
                state.soap_structured, lines, raise_on_error=False,
            )
            report.schema_errors = vrep.schema_errors
            report.grounding_errors = vrep.grounding_errors
            report.cdt_errors = vrep.cdt_errors
            report.warnings.extend(vrep.warnings)
            report.signability_score = vrep.signability_score
            for err in vrep.schema_errors + vrep.grounding_errors + vrep.cdt_errors:
                report.warnings.append(f"BLOCK: {err}")
        else:
            halluc_pen = min(len(report.unconfirmed_terms) * 0.05, 0.25)
            report.signability_score = round(
                max(0.0, report.completeness_score - halluc_pen), 3,
            )

        state.qa = report
        state.log(
            self.name,
            f"QA complete — completeness={report.completeness_score}, "
            f"signability={report.signability_score:.2f}, "
            f"warnings={len(report.warnings)}, "
            f"unconfirmed={len(report.unconfirmed_terms)}",
        )
        return state

    # ------------------------------------------------------------------
    _CDT_CODE_RE = re.compile(r"^d\d{4,5}$", re.IGNORECASE)

    def _is_grounded(self, token: str, transcript: str, transcript_stems: set) -> bool:
        """A token is grounded if it's in the transcript (literal or stem) OR
        in the dental knowledge corpus OR it's a known CDT code id.
        """
        if token in transcript:
            return True
        if _stem(token) in transcript_stems:
            return True
        if self.kb.is_grounded(token):
            return True
        if self._CDT_CODE_RE.match(token) and token.upper() in self.kb.cdt_by_code:
            return True
        return False

    @staticmethod
    def _candidate_terms(text: str):
        """Yield candidate domain terms (>=4 chars, alpha, lowercase).

        Filters function words and narrative verbs that can never be a
        clinical hallucination. Also yields CDT code IDs like 'd0461' so
        they can be confirmed against the catalog.
        """
        for w in re.findall(r"[a-zA-Z]{4,}|D\d{4,5}", text, flags=re.IGNORECASE):
            t = w.lower()
            if t in _STOPWORDS:
                continue
            yield t
