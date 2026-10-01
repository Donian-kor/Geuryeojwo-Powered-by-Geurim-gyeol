# Project Architecture

## GUI

- `app/gui/pages/` — screen-level features
- `app/gui/widgets/` — reusable UI components
- `app/gui/controllers/` — UI-to-engine coordination
- `app/gui/workers/` — non-blocking/background work
- `app/gui/theme/` — appearance
- `app/gui/resources/` — static resources

## Engine

- `app/engine/comfy/` — all ComfyUI HTTP/WebSocket/process integration
- `app/engine/workflow/` — workflow parsing and parameter resolution
- `app/engine/generation/` — generation orchestration
- `app/engine/storage/` — outputs and sessions

`main_window.py` should assemble the UI rather than contain generation logic.

## Current Position (v0.7 PHASE 2, 2026-10-01)

The target layout above is **not yet reached**. Current state:

| Target | Actual |
|---|---|
| `app/engine/comfy/` | `app/comfy/` (client, config, workflow) |
| `app/engine/generation/` | `app/engine/comfy_engine.py` + `comfy_engine.py` |
| `app/engine/storage/` | `app/engine/output/`, `app/engine/session/` |

**The move is deliberately deferred.** Reason: `comfy_engine.py`,
`output/manager.py` and `client.py` each own one of the PHASE 2 bug fixes
(B3, B5, B2). Moving them while the fixes are still fresh would make it
impossible to tell whether a regression came from the fix or from the move.

Planned order once approved:

1. `app/comfy/` → `app/engine/comfy/`
2. collapse the 13 `asyncio.run` call sites into one engine-owned loop (B7)
3. split `main_window.py` into `pages / controllers / workers`
4. output/session layout migration (needs a browser update + data move)

Steps 2-4 are not yet approved. `app/gui/pages/`, `widgets/`,
`controllers/`, `workers/` currently contain placeholder files only —
they are intentionally left out of commits until they hold real code.
