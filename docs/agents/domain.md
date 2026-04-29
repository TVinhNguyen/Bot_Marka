# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Layout

This is a single-context repo.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root, if it exists.
- **`docs/adr/`**, if it exists. Read ADRs that touch the area you're about to work in.
- The root Markdown documentation set for the current AI MT5 multi-model trading system domain.
- The PRD index at `prds/README.md`, if working from product requirements.

If `CONTEXT.md` or `docs/adr/` do not exist, proceed silently. Do not flag their absence or suggest creating them upfront. Producer skills can create them lazily when terms or decisions actually get resolved.

## Use the glossary's vocabulary

When your output names a domain concept in an issue title, refactor proposal, hypothesis, test name, or PRD, use the term as defined in `CONTEXT.md` when present.

If the concept you need is not in the glossary yet, either reconsider whether the project already uses a better term, or note the gap for a later docs pass.

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding it.

