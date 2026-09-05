# Veritas — the pitch, in plain language

**Purpose.** `CLAUDE.md`, `docs/SLIDE_DECK_BRIEF.md`, and `docs/CAPABILITY_TARGET_AND_GAPS.md`
explain Veritas in engineering language — algorithm names, F1 scores, Catalyst service
tables. That's right for a code review and wrong for convincing an officer this is worth
using. This document says what Veritas *does for a person doing police work*, in their words,
and is honest about what it doesn't do yet. No algorithm names in the main text; where it
helps to know what's running underneath a claim, it's in a small italic note — skip those if
you don't care.

---

## The problem, stated the way an officer would state it

Right now an FIR is a form that mostly stays on a shelf. If you're investigating a theft in
Mandya and the same man committed a theft in Yadgir six months ago under a slightly different
spelling of his name, nothing tells you that. If a district is about to see a spike in
chain-snatching, nobody finds out until it's already happening. If two officers are separately
looking at the same person from two different cases, neither knows the other exists.

The data to answer these questions already exists, spread across thousands of separate FIRs.
Nobody has time to cross-reference it by hand. Everything below is Veritas's answer to one
piece of that problem.

---

## 1. "Has this person done this before, and who does he work with?"

A records system can tell you what's on *this* FIR. It can't tell you "Ramesh Gowda" on this
case and "Ramesha Gouda" three districts over are the same man — as far as the raw records
know, they're two names on two different pieces of paper. So "does he have priors," "who has
he worked with," and "is this a repeat crew" all get "we don't know," even when the truth is
sitting across two files.

**What Veritas does**: reads every accused name across every case and works out, at a measured
99% accuracy, which names are the same person — so "does he have priors" has a real answer,
sourced to case numbers. From there it shows the web of people someone has co-offended with,
flags who's central to a group (the organiser, not just a follower), and traces money moved
between accounts tied to a group. Ask "who are Usha Naika's known associates" and get a real
diagram — click anyone on it to see the actual FIRs connecting them to her.

*Under the hood: probabilistic record linkage (Fellegi-Sunter) to resolve identity, then graph
analysis (PageRank, community detection, betweenness) over the resulting network.*

## 2. "Where and when is crime actually happening, and where is it heading?"

A monthly report tells you what already happened, weeks later, as a table of numbers — not
where things cluster on a map, and not what next month looks like.

**What Veritas does**: shows real crime clusters on an actual map, and projects forward —
"expect roughly 70–75 cases in this district over the next month," consistent from station
level up to the district total, not a number that falls apart when its own parts are added up.
It also watches for a spike diverging from a district's normal pattern and flags it as it
starts.

*Under the hood: density-based hotspot clustering (KDE/DBSCAN), a hierarchically reconciled
time-series forecast (Prophet + MinT), and an Isolation Forest anomaly detector for spikes.*

## 3. "Why is crime concentrated where it is?"

A hotspot map tells you *where*, not *why* — and "why" is what actually informs a resourcing
or prevention decision rather than just a reactive patrol.

**What Veritas does**: connects crime patterns to real, publicly published district statistics
— poverty, literacy, unemployment, density — and states honestly what looks like a
contributing factor versus mere correlation. It's explicit about what it *can't* measure
(police presence per district isn't published anywhere) rather than pretending a clean answer
exists. This is an understanding tool, never a "blame this community" tool — it never uses
caste or religion to explain anything, even though those columns exist in the official format.

*Under the hood: real Census 2011 ground truth joined against crime records, read through a
causal-inference layer (DoWhy) that names its own unmeasured confounders instead of hiding
them.*

## 4. "What kind of offender is this, and what does he tend to do?" — honestly, a gap

**Today**: for a given person, Veritas can say how many cases name him, what fraction ended in
conviction, and rank him against every other offender in a district by how often he's named —
a sourced "who's most active" answer nothing else in this challenge space can give, since it
depends on the identity work in §1.

**Not yet**: an actual behavior profile — "this person tends to strike late at night, near bus
stands, and the seriousness of what he does has been escalating." That's a different question
(*how, when, whether it's getting worse*, not just *how often*), and today asking it returns
nothing more than a case list.

**What we could build**: a "behaviour card" for any resolved person, built entirely from case
records already in the system — no new data. One screen: time of day/day of week pattern,
whether offences cluster in one area or spread out, whether severity is climbing or steady,
and whether methods repeat or vary. This turns a case list into the read a seasoned
investigator builds up over years, on first look, for a new officer or a case with no
institutional memory yet.

## 5. "Is something about to happen, and what should we do before it does?" — honestly, a gap

**Today**: a district-spike alert once the pattern diverges from normal, and a forecast
projecting roughly how many cases are coming. Both real and useful, but both closer to a smoke
detector than to advice — neither says what to do about it.

**Not yet**: anything that turns "a spike is coming" into a recommendation an officer could
act on before it happens.

**What we could build**: a "prevention brief" combining pieces Veritas already computes — the
forecast, the spike alert, the socio-economic context from §3, and how stretched each nearby
station currently is — into one plain-English readout: *"Theft is projected to rise in this
district over the next two weeks. It's tracking the same pattern as the last two spikes here,
both concentrated in the evening near the market area. [Station name] currently carries the
lightest caseload nearby."* Always framed as information for a commander to weigh, never an
instruction the system issues on its own — consistent with how everything else in Veritas
works: it surfaces evidence, a human decides.

---

## The parts that make the above trustworthy, not just clever

- **Every answer points at its proof.** Click any claim and see the actual FIR numbers, case
  details, or records it came from. If it can't find real support, it says so instead of
  guessing.
- **It works in Kannada, by voice, entirely inside the system** — no recording or transcript
  ever leaves the platform to a third-party speech service.
- **It only shows you what your rank and station are cleared to see**, enforced at the point
  the data is fetched, not bolted on afterward.
- **Nothing it does or answers can be quietly edited or deleted later.** Every question and
  answer is chained cryptographically and checked automatically every twelve hours.
- **An investigation survives past one conversation.** Pin evidence, leave a note, mark a lead
  chased down or dead — it's still there tomorrow, for you or whoever picks up the case next.
- **Every prediction is labelled as a prediction** — a model's guess never looks like a fact
  from a real record.

---

## Where this leaves us

Sections 1–3 — pattern discovery, network analysis, socio-demographic insight — are real,
built, and running today. Sections 4–5 — behavioural profiling and proactive prevention — have
honest, useful pieces (offender ranking, spike alerts, forecasting) but not yet the specific
thing each name promises. Both gaps are buildable from data already in the system — no new
dataset, no new external service, no architecture change — so the choice is about time budget,
not feasibility.

**Open question back to you**: build both, one, or neither before the deadline? The behaviour
card (§4) is the smaller lift — mostly organizing data the system already has. The prevention
brief (§5) is a stronger pitch (it directly answers "proactive crime prevention intelligence,"
verbatim from the brief) but touches more moving parts, since it stitches four existing
outputs into one new view.
