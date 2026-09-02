# Alternate UI options

Standalone HTML/CSS, full visual fidelity — no build step, no dependency on
`apps/web`. Open any `index.html` directly in a browser. These are finished-look
alternates for the Command Console, built against the live console's actual
design tokens (`apps/web/app/globals.css`: the warm off-white ground, navy text,
ochre identity accent, provenance glyphs, hairline dividers). **Nothing here
changes the shipped UI** — they exist to compare real options, not to replace
what's live.

| Folder | Direction |
|---|---|
| [01-chat-focused](01-chat-focused/index.html) | The conversational AI is the primary surface — one wide chat column, with the map/graph/evidence collapsed into an on-demand side drawer instead of a permanent three-column split. |
| [02-command-deck](02-command-deck/index.html) | A dashboard-style command deck — chat is one panel among several always-visible ones (map, network, alerts, board), for an operator who watches many things at once rather than holding one conversation. |
| [03-mobile-first](03-mobile-first/index.html) | A single stacked column for a phone/tablet in the field — chat, then a swipeable card for whatever the last answer produced, with evidence one tap away. |
