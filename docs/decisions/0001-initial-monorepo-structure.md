# 0001: Initial Monorepo Structure

## Status

Accepted

## Context

The project needs a clean starting structure for a PEPEPOW community pool MVP. The initial deployment target is a single low-resource ARM64 host, and early work should remain understandable, easy to change, and safe to operate.

## Decision

- Use a single monorepo to keep documentation, application code, configuration, and operations assets versioned together.
- Start with a single-coin, single-machine structure focused on PEPEPOW only.
- Keep pool core, API, frontend, configuration, and ops artifacts in separate top-level areas to reduce unnecessary coupling.
- Do not allow the frontend to read daemon RPC directly; expose only controlled application-facing interfaces.
- Prioritize stability and maintainability over early support for multi-coin logic or complex runtime features.

## Rationale

- A monorepo is simpler to manage during the MVP stage and reduces coordination overhead across tightly related components.
- Single-coin and single-host scope keeps resource usage, operational complexity, and failure modes easier to reason about.
- Low-coupling boundaries make later replacement or refinement of API, frontend, and ops layers more manageable.
- Keeping daemon RPC behind internal boundaries reduces security risk and avoids binding the public UI directly to wallet or node internals.
- Delaying multi-coin and other advanced features avoids premature abstractions that would slow down early validation.

## Consequences

- The repository can evolve incrementally without immediate reorganization.
- Some future restructuring may be needed if the project grows beyond the initial MVP assumptions.
- Near-term work should stay disciplined about not bypassing the intended component boundaries.
