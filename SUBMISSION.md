# Submission — KSP Datathon 2026, Challenge 01

Everything the form asks for, ready to paste. Deck: `Veritas_KSP_Datathon_2026_Prototype_Deck.pptx`
(PDF export beside it, 440 KB, under the 5 MB limit).

## 1. Challenge
Intelligent Conversational AI for KSP Crime Database

## 2. Prototype Brief  (1018 / 1024 characters)

Veritas is a conversational crime-intelligence console for the Karnataka State Police. An officer asks in English or Kannada; the answer returns with every claim cited to a specific FIR record.

The organizers' ER has no person: an Accused row belongs to one case, so "does he have priors?" has no answer in the raw schema. Veritas reconstructs people from those rows with Fellegi-Sunter record linkage (F1 0.989), and priors, co-offender networks, hotspots, money trails and risk scores all build on that pass.

Retrieval is HippoRAG (Personalized PageRank over a graph built from the records) with Think-on-Graph for deep multi-hop questions, and a CRAG evaluator that refuses when the records do not support an answer rather than returning the nearest case. Access control is applied at query-construction time; the audit log is a SHA-256 hash chain re-verified by Cron.

On Catalyst: AppSail, Data Store (37 tables, 10,000 FIRs), File Store, Cache, QuickML GLM-4.7-Flash, Cron, Web Client Hosting. 200 tests green.

## 3. GitHub public repository
https://github.com/baveshraam/Veritas

## 4. Prototype deployed link (Catalyst)
https://veritas-60077763394.development.catalystserverless.in/app/index.html

API health, if an evaluator wants the numbers directly:
https://veritas-api-50043864344.development.catalystappsail.in/health

Append `?as=DSP` to the console link to sign in at that rank without credentials; `?as=IO`
shows the same questions answered under a single station's access.

## 5. Demo video (public / unlisted, 3 minutes)
<PASTE LINK>

Suggested run of show, in this order — it is the argument the deck makes, demonstrated:
1. Ask "What is the status of FIR 100222201202600022?" — exact record, cited, confidence 0.97.
2. Ask the same about a FIR number that does not exist — it refuses. (This is the moment that
   separates the system from a search box; do not cut it.)
3. "Summarise the criminal history of <accused>" — two spellings, one resolved person, priors.
4. Open the network view — Louvain communities over co-offending.
5. Kannada question by voice — "ಮಂಡ್ಯ ಜಿಲ್ಲೆಯಲ್ಲಿ ಎಷ್ಟು ಕಳವು ಪ್ರಕರಣಗಳಿವೆ?"
6. Sign in as IO, repeat a district-wide question — 81 cases / 1 station instead of 500 / 76.
7. Expand the reasoning trace, and click a citation to draw the evidence thread.

## 6. Before submitting
- [ ] Slide 1: team name, leader, size.
- [ ] Slide 11: replace the six frames with live screenshots (labels say which).
- [ ] Slide 13: paste the demo video link.
- [ ] Re-export the PDF and upload that (the form takes PDF only).
