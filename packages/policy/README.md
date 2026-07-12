# Policy (`packages/policy/`)

**What this is**: the single, versioned, unit-tested definition of every RBAC rule in the system. Not a track of its own — a small shared library that `apps/api` and `packages/rag_agent` both import, because role-based access control is a cross-cutting concern that can't be owned by exactly one track without either duplicating the rules (and letting them drift) or leaving a masking gap. See root [`CLAUDE.md`](../../CLAUDE.md) Repository Structure for why this is the one deliberate exception to "no shared files between tracks."

Owns Layer 8's policy rules (not its transport/middleware wiring — that's `apps/api`).

## Why this exists (don't skip this if you're touching auth/RBAC)
Masking a field or capping graph-traversal depth **after** a query already ran is too late — you can't un-traverse a graph, and you can't reliably redact a name out of already-generated prose. So the rules have to be enforceable in two different places at two different times:
- **Post-hoc, on structured responses** (`/fir/{id}`, `/person/{id}`) — `apps/api` applies this as middleware.
- **At query-construction time** — `packages/rag_agent`'s Graph/SQL Agents apply this before running a query, so a restricted field or an over-deep traversal is never retrieved in the first place.

Both call into this package so there's exactly one definition of what each role can see.

## Rules
- IO sees only FIRs filed at their own PS (`officer.ps_code` match).
- Victim identity is masked below DSP rank.
- Graph traversal depth is capped by role: IO/SHO get depth ≤2, DSP+ get depth ≤4 (matches the financial-crime `TRANSFERRED_TO*1..4` bound in `data/README.md`).

## Functions this package exposes

```python
def can_view_fir(officer_role: str, officer_ps_code: str, fir_ps_code: str) -> bool: ...
def mask_person_fields(officer_role: str, person: dict) -> dict: ...      # returns a copy with victim-identifying fields nulled below DSP
def max_traversal_depth(officer_role: str) -> int: ...                     # 2 for IO/SHO, 4 for DSP and above
```

## Suggested structure
```
packages/policy/
  rules.py             # the three functions above, plus the role hierarchy constant
  tests/               # one test per rule, per role — this package has no runtime effect without these
```

## Provides / Consumes
- **Provides to `apps/api`**: `can_view_fir`, `mask_person_fields` — applied as middleware on `/fir/{id}` and `/person/{id}`.
- **Provides to `packages/rag_agent`**: `max_traversal_depth`, `can_view_fir` — applied inside the Graph/SQL Agents before traversal/query execution.
- **Consumes**: nothing — pure functions over the role/PS-code strings callers already have (`officer.role`/`officer.ps_code` come from `data/`'s `officer` table via whichever caller looked them up).

## Non-goals
- No JWT verification (that's `apps/api/auth/`), no audit logging, no query execution — this package only answers "is this allowed," it never performs the allowed/disallowed action itself.
