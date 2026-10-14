---
type: llm
---

PASS if the final message says the task stopped because it is too large and passes on the suggested split (several smaller requirements), without claiming any code was written.
FAIL if it claims the feature was built, or does not mention splitting.
