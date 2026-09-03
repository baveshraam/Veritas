# Veritas — the pitch, in plain language

**Purpose of this document.** Every other doc in this repo (`CLAUDE.md`,
`docs/SLIDE_DECK_BRIEF.md`, `docs/CAPABILITY_TARGET_AND_GAPS.md`) explains Veritas in
engineering language — algorithm names, F1 scores, Catalyst service tables. That's the right
language for a code review and the wrong language for convincing a police officer this is
worth using. This document has one job: say what Veritas actually *does for a person doing
police work*, in the words that person would use, and be honest about what it doesn't do yet.

No algorithm names appear in the main text. Where it's useful to know what's running
underneath a claim, it's in a small italic note — skip those if you don't care.

---

## The problem, stated the way an officer would state it

Right now, an FIR is a form. It goes into a system, and it mostly stays there — a fact on a
shelf. If you're investigating a theft in Mandya and the same man committed a theft in
Yadgir six months ago under a slightly different spelling of his name, nothing tells you
that. If a district is about to see a spike in chain-snatching, nobody finds out until it's
already happening. If two officers are separately looking at the same person from two
different cases, neither knows the other exists.

The data to answer these questions already exists, spread across thousands of separate FIRs.
Nobody has the time to cross-reference it by hand. That's the actual problem. Everything
below is Veritas's answer to one piece of it.

---

## 1. "Has this person done this before, and who does he work with?"

Today, a records system can tell you what's on *this* FIR. It can't tell you that "Ramesh
Gowda" on this case and "Ramesha Gouda" on a case three districts over are the same man —
because as far as the raw records are concerned, they're two different names on two
different pieces of paper. So nobody's system can currently answer "does this person have
priors," "who has he worked with before," or "is this a repeat crew" — the honest answer on
a plain records system is always "we don't know," even when the truth is sitting right there
across two files.

**What Veritas does**: it reads every accused name across every case and works out, with a
measured 99% accuracy, which names are actually the same person — so "does he have priors"
finally has a real answer, sourced to the actual case numbers. Once that's done, it can show
you the web of people someone has co-offended with, flag who's central to a group (the
organiser, not just a follower), and trace where money moved between accounts tied to a
group. Ask "who are Usha Naika's known associates" and you get a real diagram, not a guess —
click anyone on it and see the actual FIRs that connect them to her.

*Under the hood: probabilistic record linkage (Fellegi-Sunter) to resolve identity, then
graph analysis (PageRank, community detection, betweenness) over the resulting network of
real people.*

---

## 2. "Where and when is crime actually happening, and where is it heading?"

A monthly crime report tells you what already happened, weeks after it happened, as a table
of numbers. It doesn't tell you where things are actually clustering on a map, and it
certainly doesn't tell you what next month looks like.

**What Veritas does**: shows real crime clusters on an actual map (not a spreadsheet), and
projects forward — "expect roughly 70–75 cases in this district over the next month,"
consistent all the way from the station level up to the district total, not a number that
falls apart when you add up its own parts. It also watches for a sudden spike that doesn't
match the normal pattern for a district and flags it as it starts.

*Under the hood: density-based hotspot clustering (KDE/DBSCAN) and a hierarchically
reconciled time-series forecast (Prophet + MinT), with an anomaly detector (Isolation
Forest) on top for spike alerts.*

---

## 3. "Why is crime concentrated where it is?"

A hotspot map tells you *where*. It doesn't tell you *why*, and "why" is what actually
informs a resourcing or a prevention decision rather than just a reactive patrol.

**What Veritas does**: connects crime patterns to real, publicly published district
statistics — poverty, literacy, unemployment, population density — and states honestly what
looks like a contributing factor versus what's just correlation. It's built to be explicit
about what it *can't* measure (like how much police presence a district already has, which
isn't published data anywhere) rather than quietly pretending a clean answer exists where one
doesn't. This is a *understanding* tool, never a "blame this community" tool — it never uses
caste or religion to explain anything, even though those columns exist in the official
records format.

*Under the hood: real Census 2011 ground truth joined against crime records, read through a
causal-inference layer (DoWhy) that names its own unmeasured confounders instead of hiding
them.*

---

## 4. "What kind of offender is this, and what does he tend to do?" — honestly, a gap

Here's where we should be straight with you rather than talk around it.

**What Veritas has today**: for a given person, it can tell you how many cases name him, what
fraction ended in conviction, and rank him against every other offender in a district by how
often he's named — a real, sourced "who's most active" answer nothing else in this challenge
space can currently give, because it depends on the identity work in §1.

**What it does *not* have yet**: an actual behavior profile. Today it can't tell you "this
person tends to strike late at night, near bus stands, and the seriousness of what he does
has been escalating over the last two years." That's a genuinely different question — not
*how often*, but *how, when, and whether it's getting worse* — and right now nobody asks
Veritas that question and gets more than a case list back.

**What we could build, in plain terms**: a "behaviour card" for any resolved person, built
entirely from case records already in the system — no new data needed. It would read across
everything he's known to have done and answer, in one screen: what time of day and day of
week he tends to act, whether his offences cluster in one area or spread out, whether the
severity of what he's doing is climbing or steady, and whether his methods repeat (the same
approach on multiple cases) or vary. This turns a case list into the kind of read a seasoned
investigator builds up in their head over years, but on the first look, for a new officer or
a case with no institutional memory attached to it yet.

---

## 5. "Is something about to happen, and what should we do before it does?" — honestly, a gap

**What Veritas has today**: a district-spike alert that fires once the pattern starts
diverging from normal, and a forecast that projects roughly how many cases are coming. Both
are real and both are useful — but both are closer to a smoke detector than to advice. One
tells you something is already going wrong; the other tells you a number. Neither one tells
you *what to do about it*.

**What it does *not* have yet**: anything that turns "a spike is coming" into an actual
recommendation an officer could act on before it happens — nothing today says "this looks
like it's coming, here's why, and here's what's worth doing about it."

**What we could build, in plain terms**: a "prevention brief" that combines pieces Veritas
already computes — the forecast, the spike alert, the socio-economic context from §3, and how
stretched each station currently is — into one plain-English readout: *"Theft is projected to
rise in this district over the next two weeks. It's tracking the same pattern as the last two
spikes here, both of which concentrated in the evening near the market area. [Station name]
is currently carrying the lightest caseload nearby."* It would always be framed as
information for a commander to weigh, never an instruction the system issues on its own —
consistent with how everything else in Veritas already works: it surfaces evidence, a human
decides.

---

## The parts that make the above trustworthy, not just clever

None of the above is worth anything to a police officer if it can be wrong and nobody can
tell. So, in plain terms:

- **Every answer points at its proof.** Click any claim and see the actual FIR numbers,
  case details, or records it came from — not a description of "the AI did some analysis."
  If it can't find real support for something, it says so out loud instead of guessing.
- **It works in Kannada, by voice, entirely inside the system.** No recording or transcript
  ever leaves the platform to a third-party speech service.
- **It only shows you what your rank and station are cleared to see.** A station officer sees
  their station's cases; a DSP sees across stations; nobody sees more than their role allows,
  enforced at the point the data is fetched, not bolted on afterward.
- **Nothing it does or answers can be quietly edited or deleted later.** Every question and
  answer is chained together cryptographically, checked automatically every twelve hours, so
  tampering with the record would be detectable, not just discouraged.
- **An investigation survives past one conversation.** Pin evidence, leave a note, mark a lead
  as chased down or a dead end — and it's still there tomorrow, for you or for whoever picks
  up the case next, instead of starting over from zero every time someone opens a chat.
- **Every prediction is labelled as a prediction.** A model's guess is never shown the same
  way as a fact from a real record — an officer always knows which is which at a glance.

---

## Where this leaves us

Sections 1, 2, and 3 of the brief — pattern discovery, network analysis, socio-demographic
insight — are real, built, and running today, not a slide of intentions. Sections 4 and 5 —
behavioural profiling and proactive prevention — have honest, useful pieces today (offender
ranking, spike alerts, forecasting) but not yet the specific thing each name promises. Both
gap items above are buildable from data already in the system — no new dataset, no new
external service, no architecture change — which means the choice is about time budget, not
feasibility.

**Open question back to you**: build both, one, or neither before the deadline? The behaviour
card (§4) is the smaller lift — it's mostly organizing data the system already has. The
prevention brief (§5) is more valuable as a pitch (it directly answers "proactive crime
prevention intelligence," verbatim from the brief) but touches more moving parts since it
stitches together four existing outputs into one new view.
