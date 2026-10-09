---
class: feature        # feature | task | bug | bootstrap
size: small           # small | medium | large (large = too big for one loop)
title: Short imperative title, used as the PR title
---
# Requirements — <title>

## Problem
Who needs what and why, in 2–4 sentences. Plain language, no solution design.

## Requirements
EARS style, one behaviour per line:
- R1. When <trigger>, the system shall <response>.
- R2. While <state>, the system shall <response>.
- R3. If <unwanted condition>, then the system shall <response>.

## Acceptance criteria
Numbered AC-n, each one checkable by a test or by reading code. These ids are
used by every later stage (tests, verification, PR).
- AC-1: <observable outcome with concrete inputs and outputs>
- AC-2: …

For a **bug**: AC for the reproduction (fails today), the fix, and the
behaviour that must not change.

## Out of scope
- Adjacent things this change does not do.

## Assumptions
- Anything assumed that the input did not say.

## Suggested split
(Only when size is large: 2–5 smaller requirements, each shippable alone.)

## Open questions
- Questions only the human can answer, or "none".
