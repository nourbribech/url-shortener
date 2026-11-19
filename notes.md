## Phase 1: The backend
**What I built:** A 132-line FastAPI URL shortener with /health, /metrics, /shorten, /{code} (307) and /stats/{code}, plus 7 pytest tests.
**Why it exists:** The pipeline needs something real to test, package and monitor. The app is the payload; the automation is the project.
**What broke and how I fixed it:** [e.g. /stats/{code} shadowed by /{code} until I moved the catch-all last]
**What I would explain in the Q&A:** Route templates in metric labels keep cardinality bounded; secrets.choice because codes are public identifiers; 307 preserves the method; state is in-memory, so it dies with the process.
**Evidence saved:** pytest output (7 passed), sample JSON log line