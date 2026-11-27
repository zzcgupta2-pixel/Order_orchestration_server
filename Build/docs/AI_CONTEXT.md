
# AI CONTEXT

Read this entire document before proposing
code changes.

Current replenishment logic:

- Colour 16-20 uses two-pass execution.

PASS 1:
Parent allocation only.

PASS 2:
GIT and alternatives.

ZFMO 16:
- Credit block ignored
- No safety stock deduction anywhere
- ZFMO scoring

ZMSO 16:
- Credit block enforced
- Parent no safety stock deduction
- Alternative safety stock deducted
- ZMSO colour-16 scoring

ZFMO 17-20:
- Credit block ignored
- Parent no safety stock deduction
- Alternative safety stock deducted

ZMSO 17-20:
- Credit block enforced
- Parent no safety stock deduction
- Alternative safety stock deducted

Missing Route:
- TransportMode.SURFACE
- SLA = 5

Missing SLA:
- SLA = 5

Missing RLT:
- RLT = 5

Current focus:
Replenishment execution,
two-pass orchestration,
MOQ allocation,
GIT allocation,
safety-stock handling,
and KPI reporting.
