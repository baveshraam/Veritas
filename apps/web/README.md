# Frontend — Command Console (`apps/web/`)

**What this is**: the entire officer-facing UI. A Next.js app deployed on Vercel (project `veritas`). Talks to `apps/api` only — no direct DB, graph, or model access from here. Implements Layer 9 of root [`CLAUDE.md`](../../CLAUDE.md).

## Visual language
Futuristic minimalist glassmorphism, rendered in **dark glass**: frosted dark-acrylic panels with subtle blur, soft elevation shadows, floating components (not hard-edged panels), over a restrained gradient-mesh background. Generous spacing, light depth layering, smooth natural-easing microinteractions. Modern, crisp, highly legible typography. Soft neon/pastel accents (amber/rose) used sparingly and only for severity signaling — never decoratively. Calm, premium, spatial — next-gen Apple-style with a subtle sci-fi undertone. Dark glass specifically (not light-glass-on-white) because this is dense command-console work: map/graph data needs contrast that a light theme washes out.

## Layout — three floating panes
- **Left — Chat**: SSE-streamed conversation, EN/KN toggle, voice push-to-talk with a live waveform.
- **Center — Context view**: driven entirely by the final SSE event's `visualization.kind` — never inferred client-side from the query text:
  - `"map"` → Deck.gl + MapLibre (self-hosted OSM tiles): KDE heatmap polygons + FIR scatter points, from `visualization.data.polygons`/`.fir_points`.
  - `"network"` → Sigma.js or Cytoscape.js, force-directed, from `visualization.data.nodes`/`.edges`.
  - `"sankey"` → Apache ECharts Sankey, from `visualization.data.nodes`/`.links` (ECharts' native Sankey shape).
  - `"trend"` → Apache ECharts line + confidence band, from `visualization.data.series`.
  - `"none"` → keep whatever view was last showing (or an empty state on the first turn); plain-text answers don't force a view change.
  Each view transition is a soft cross-fade/morph, never a hard cut. Exact per-`kind` shapes are canonically defined in `packages/rag_agent/README.md`.
- **Right — Case/evidence rail**: pinned current FIR/person; every citation chip (`[FIR-1234]`, `[Community 47]`) opens a floating glass drawer showing the matching `EvidenceItem` from the final SSE event's `evidence_items` array (matched by `citation.evidence_id`) — no separate fetch, the content ships with the answer.
- **Reasoning Trace panel** (collapsible, off by default): renders the `agent_trace` stream in plain language, e.g. *"Orchestrator → HippoRAG retrieval (0.4s) → ToG deep-dive (low confidence) → Evidence Evaluator: 3 corroborating records → Synthesis."* This is the strongest 30-second differentiator in a live demo — make it visually clear, not an afterthought log dump.

**Color language**: one consistent severity/threat palette (soft neon amber/rose on dark glass) reused identically across map markers, graph nodes, citation chips, and Sankey flow colors — the product should read as one instrument, not stitched-together widgets.

## Investigation Copilot workspace
A separate route from the chat, backed by `GET /copilot/{fir_id}`: case file panel, drag-and-drop evidence board, auto-generated timeline (`CopilotBrief.timeline`), "these cases may be linked" suggestions (`.similar_cases`, `.leads`), one-click charge-sheet-support report generation from `.draft_summary`. Same glass visual language, denser information layout for working investigators.

## Other requirements
- **PDF export**: a button that calls `POST /export/pdf` on `apps/api`; the actual headless-Chrome render happens server-side (of the full stored conversation history, not just what's currently on screen), this app just triggers it and downloads the result.
- **i18n**: EN/KN throughout — every label, button, and error state, not just chat content.
- **Voice**: push-to-talk records audio, sends it as part of the same `POST /chat` request (`audio` field instead of `query`) — there is no separate voice endpoint. If the user has voice-response enabled, the request also sets `respond_with_voice: true` and the SSE stream includes a `type: "audio"` event to play back.

## API contract (canonical shape owned by `apps/api/README.md` — mirrored here, don't fork it)

```
POST /chat
  body: { session_id, officer_id, officer_role, language, query }  // or `audio` (base64) instead of `query`, + respond_with_voice?: bool
  response: SSE stream of
    { type: "trace",  step, detail, duration_ms, confidence }                       # render into Reasoning Trace panel, live
    { type: "final",  final_answer, citations, evidence_items, visualization }      # citations open the evidence rail; evidence_items are its content; visualization drives the center pane
    { type: "audio",  data: <base64> }                                              # only if respond_with_voice was set

GET /fir/{fir_id}        -> FIR record (policy-filtered server-side)
GET /person/{person_id}  -> Person record (victim identity masked below DSP rank — trust the API's response, don't re-filter client-side)
GET /copilot/{fir_id}    -> CopilotBrief (timeline, similar_cases, leads, draft_summary) — powers the Investigation Copilot workspace
POST /export/pdf         -> { session_id } -> PDF bytes
WS /alerts               -> live AnomalyAlert pushes, render as a toast/notification
```

## Suggested structure
```
apps/web/
  app/                 # Next.js App Router routes: chat, copilot workspace
  components/          # chat pane, context-view switcher (map/graph/sankey/trend), evidence rail, reasoning trace panel
  lib/                 # API client, SSE/WebSocket handling, citation-chip resolution
  styles/              # glass design tokens — blur radius, elevation shadows, gradient-mesh, severity palette
```

## Non-goals
- No business logic, no direct database/graph/model calls, no auth/policy decisions (the API has already filtered what you're allowed to see) — this folder renders what `apps/api` sends and nothing more.
