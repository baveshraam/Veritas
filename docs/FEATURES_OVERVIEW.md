# Veritas — Features Overview

Plain-language index of what Veritas does, one or two lines each, tagged with the
underlying technique. Excludes the Statistics dashboard and analytics tabs (reporting
surfaces, not distinct capabilities). See `CLAUDE.md` for architecture/rationale and
`docs/WORK_LOG.md` for the pass-by-pass build history.

## Talking to it

- **Ask in English or Kannada, typed or spoken.** Talk to it like a person; it answers
  like one. `[Conversational AI / Speech-to-Text (ASR) / Machine Translation]`
- **Spoken answers in Kannada.** Not just text back. `[Text-to-Speech (TTS)]`
- **Never invents facts.** Answers only from real records; says "not found" rather than
  guessing. `[RAG — Retrieval-Augmented Generation]`
- **Every claim links to proof.** Click any sentence, see the exact case file behind it.
  `[Citation grounding / Provenance chain]`

## Understanding messy human phrasing

- **Understands intent, not just keywords.** Differently worded versions of the same
  question route the same way. `[NLU — Natural Language Understanding]`
- **Follows the conversation.** Remembers what "he" or "that case" means from earlier
  turns. `[Coreference resolution / Conversational memory]`
- **Handles multi-step questions.** Breaks a compound ask into steps and answers each.
  `[Task planning / Agentic reasoning]`
- **Takes mid-conversation corrections.** "No, I meant the Kolar case" gets applied.
  `[Semantic correction handling]`
- **Asks instead of guessing.** Two suspects share a name → it asks which one.
  `[Entity disambiguation]`

## Trust and self-checking

- **Fact-checks its own answer before showing it.** A second pass grades whether the
  retrieved evidence is actually good enough. `[CRAG — Corrective-RAG]`
- **"Why is this here?" on anything.** Any person/link/number explains its own reasoning
  and source records on click. `[Explainable AI (XAI)]`
- **"Challenge this finding."** Actively looks for reasons its own prior answer could be
  wrong. `[Adversarial self-critique]`
- **States when an answer is incomplete.** Distinguishes "5 sample cases" from "all of
  them." `[Result-set honesty / calibration]`

## Knowing who's who

- **Links differently-spelled names to the same person.** The raw records treat every
  case as a stranger; this stitches identity back together. `[Probabilistic record
  linkage — Fellegi-Sunter, 1969]`
- **Maps who's connected to who.** Shared cases, shared accounts, money transfers.
  `[Knowledge graph]`
- **Ranks who's central to a network.** Same idea as ranking web pages, applied to
  criminal association. `[Graph algorithms — PageRank, Louvain community detection,
  betweenness centrality]`

## Spotting patterns nobody asked about

- **Notices unrelated-looking cases are one offender.** Cross-station, cross-time
  matches nobody queried for. `[Unsupervised pattern detection — series linkage]`
- **Builds a behavioral profile.** Recurring method, timing, geographic range — never
  demographic. `[Behavioral analytics]`
- **Flags suspicious money movement.** Structuring (many small transfers) and
  coordinated multi-account laundering. `[Rule-based detection + Graph Neural Network]`

## Investigator's assistant tools

- **Interrogation prep.** Priors, associates, case gaps assembled before questioning a
  suspect. `[Retrieval + summarization]`
- **Similar-case watch.** Surfaces past cases like this one and their outcomes.
  `[Similarity search / embeddings]`
- **Case handoff briefing.** Auto-written "catch me up" when a case changes officers.
  `[Automated summarization]`
- **Pre-filing check.** Flags case weaknesses before it's sent up the chain.
  `[Structured rule-checking]`
- **Cross-station linkage alerts.** Flags a suspect also named at another station.
  `[Cross-record matching]`
- **Persistent case board.** Pinned evidence/notes/findings survive across sessions.
  `[Stateful memory / persistence]`
- **Cross-entity timeline.** One chronological view across a case, its people, and its
  locations. `[Data fusion]`

## Guardrails

- **Decision support only.** No prediction ever auto-triggers an action.
  `[Human-in-the-loop]`
- **No caste/religion reaches a model.** Stored (schema requires it), never scored on.
  `[Fairness-by-design]`
- **Tamper-proof activity log.** Every Q&A is chained so past entries can't be silently
  edited. `[Hash chain / audit trail]`
- **Role-based visibility.** Access enforced at the database query level, not just
  hidden in the UI. `[RBAC — Role-Based Access Control]`
