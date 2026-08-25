# Veritas — demo script

Record the narration to this, then screen-record the console and cut the video to the audio.

- **Console**: `https://veritas-60077763394.development.catalystserverless.in/app/index.html`
- **Runtime**: ~3 min 30 s of narration. All latencies below were measured against the live
  deployment on 26 Jul 2026 — they are what the app actually does, not estimates.

**Measured turn latency** (this is why the script is paced the way it is):

| Turn | Time |
|---|---|
| Network, hotspot, FIR lookup, refusal, forecast | **under 2.5 s** |
| Kannada | **~20 s, every time** |

Everything is fast except Kannada, which runs NLLB translation twice — in and out — on CPU
inside our own container. That is not a cold start; it does not warm up. Section 5 is written
to fill exactly that gap with something worth saying. **Do not cut Kannada for being slow —
narrate the reason it is slow, because the reason is the point.**

### Before you record

1. Open the console at `?as=IG` and run one throwaway Kannada query. This does not make the
   next one faster, but it confirms the container is up so you don't discover it on take three.
2. Have a second browser window open at `?as=IO`, already signed in, for section 6.
3. Reasoning Trace panel: **closed**. You open it once, deliberately, in section 4.

---

## 1 — Cold open (0:00–0:25)

> **[ON SCREEN]** Sign-in gate. Don't click yet.

"Every police force in India is sitting on more records than any officer can read.

The problem isn't storage. It's that the question an investigator actually wants to ask —
*has this man done this before, and who does he do it with* — isn't a question a case file
can answer. Case files are written one case at a time.

This is Veritas. You ask in English or Kannada, and every claim in the answer carries the
record it came from."

> **[ON SCREEN]** Click **IG — Shivakumar Kamath**. Console loads.

"Ten thousand FIRs. Sixteen thousand nine hundred and eighteen nodes in the graph. Thirteen
thousand eight hundred documents indexed. That readout is live — it's the scope of what any
answer can be drawn from."

---

## 2 — The idea the whole system rests on (0:25–1:05)

> **[ON SCREEN]** Type: `Who are the associates of Usha Naika?`
> Answers in ~1.5 s. Network graph fades in. Let it breathe for three seconds.

"Here is what makes that graph unusual: **none of those links exist in the records.**

An FIR names an accused against the case in hand. The person on case 412 and the person on
case 908 are two separate entries, written by two different officers, sometimes spelled two
different ways. That's faithful record-keeping — and it means the raw data says every
offender is a first-timer and nobody has an accomplice.

So before Veritas answers anything, it reconstructs people from those entries — probabilistic
record linkage, F1 of point nine eight nine against a held-out answer key.

Usha Naika: twenty-four direct co-accused, across eighteen cases. That network is *derived
evidence*, and it's the thing a team writing plain SQL against the schema cannot reach."

---

## 3 — Geography (1:05–1:30)

> **[ON SCREEN]** Type: `Show me theft hotspots in Bengaluru Urban`
> ~1 s. Map cross-fades in — 600 incident points under the density polygons.

"Kernel density and DBSCAN over six hundred incidents, with the scatter underneath — because
a polygon with no points beneath it is an assertion, not a hotspot.

And the basemap is drawn by us, not fetched. No FIR coordinate ever leaves the network inside
a request to a third-party tile server."

---

## 4 — The part that matters most (1:30–2:20)

> **[ON SCREEN]** Type: `What is the status of FIR 100222201202699999?`
> ~0.7 s. Refusal. **No citations, no visualization.**

"That FIR doesn't exist. Watch what it does.

It says so. It doesn't guess, it doesn't offer me the nearest similar case, and it shows zero
citations.

That sounds like a small thing. It is the hardest thing. Retrieval will *always* return
something — ask for a record that isn't there and a semantic search hands you five real
records about a different crime, cited, and confident. We measured exactly that failure and
fixed it: a named record identifier is a yes-or-no claim about one row, so a missed lookup is
refused outright, whatever the confidence score says."

> **[ON SCREEN]** Open the **Reasoning Trace** panel now, on the refusal.

"And you can see it decide. Orchestrator, retrieval, evidence evaluator — reject."

> **[ON SCREEN]** Type: `What is the status of FIR 100222201202600022?`
> ~0.6 s. Six citations.

"The real one comes back in under a second. Mandya district, station 2201, hurt, filed the
thirtieth of June. Six records behind it."

> **[ON SCREEN]** Click a citation chip — the evidence thread draws to the claim.

"Click any claim and it draws a line to the record it rests on."

---

## 5 — Kannada (2:20–2:55)

> **[ON SCREEN]** Press **ಕನ್ನಡ**. Type the Kannada query.
> **This takes about twenty seconds.** The narration below is written to cover it — keep
> talking, don't cut to black, don't speed up the footage.

"Now in Kannada.

This one is slower, and it's worth saying why. The translation is NLLB-200, and it is running
on CPU inside our own container on Catalyst — in, and back out again.

We could make this instant by calling a translation API. We deliberately don't. A Kannada
query about an FIR is an operational police question, and sending it to a third-party
endpoint means it leaves the network. Twenty seconds is what it costs to keep it inside, and
that is the correct trade for a police system.

The model also never sees Kannada. The query is translated to English inside the container
before the language model is called, and the answer is translated back."

> **[ON SCREEN]** Answer arrives in Kannada with 5 citations.

"Same records. Same citations. Kannada in, Kannada out."

---

## 6 — Who is asking (2:55–3:20)

> **[ON SCREEN]** Switch to the second window — the one already signed in as **IO**.
> Put the two windows side by side.

"Last thing. Same console, same question, two ranks.

The Investigating Officer sees eighty-one cases, from one station. The Inspector General sees
five hundred, across seventy-six.

And that isn't a filter applied to the answer afterwards. You cannot un-traverse a graph, and
you cannot reliably redact a name out of generated prose — so the officer's scope is a
condition inside the query, and the traversal depth cap bounds the walk before it runs."

---

## 7 — Close (3:20–3:35)

> **[ON SCREEN]** Back to the IG window, evidence rail visible.

"Every answer traces to a record. Where the records don't support one, it says so.

No protected attribute reaches any model. The audit log is hash-chained, and a scheduled job
re-verifies the chain every twelve hours — because a tamper check nobody runs isn't a tamper
check.

Veritas. Running on Catalyst, live."

---

## Two honest warnings

**Do not type `Show me the co-offender network` or `Show me the money trail`.** Both return
zero citations and draw nothing. That is correct behaviour — neither names a subject to
traverse from, and picking one would be invention — but on camera it reads as broken. Always
name the person: `Who are the associates of Usha Naika?`

**Prefer naming the district.** `Show me crime hotspots` works now, but it silently falls back
to the busiest district without telling you which. `...in Bengaluru Urban` shows the console
understood the place.

## Backup queries, all verified live

| Query | Returns |
|---|---|
| `What is the forecast for Mysuru?` | trend, 30-day band, 6 citations, ~2.4 s |
| `ಬೆಂಗಳೂರಿನಲ್ಲಿ ಕಳವು ಹಾಟ್ಸ್ಪಾಟ್ಗಳನ್ನು ತೋರಿಸಿ` | map, 600 points, Kannada answer |
| Case index → **Ask about this case** | fires the FIR lookup without typing 18 digits |
