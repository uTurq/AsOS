# AsOS (Assist Operating System) — Project Source of Truth

Pronounced "Ay-soh-s". Formerly referred to as "Jarvis" during early
design discussion — renamed before implementation began.

**This document is the durable spec.** Any future session (Claude or
otherwise) working on this project should read this file first and
treat it as binding. The locked v1 scope below does not expand without
the user explicitly re-opening scope — implementation revealing a
genuine architectural blocker is the only valid reason to revisit it.

---

## 1. Vision (context, not scope)

A standalone, persistent local program — not a chatbot wrapper — that
manages the user's entire academic life: Canvas data, course content,
schedule, concept mastery, and study planning. Claude is the reasoning
engine invoked by the program, not the interface itself. Long-term,
this becomes a proactive academic operating system across a semester.
The full vision is intentionally larger than v1 — see Section 3 for
what's deliberately deferred.

## 2. Target environment

- **OS: Windows.** Autostart mechanism, global hotkey capture, and the
  credential vault backend all need to work there — that's the actual
  target, not whatever environment a given Claude session is coding in.
- **Hardware: modern CPU, no dedicated GPU.** Local STT/embedding model
  choices must be CPU-feasible (e.g. whisper.cpp/faster-whisper with a
  small/base model, a small local embedding model like bge-small/
  all-MiniLM) — do not assume GPU acceleration is available.
- **Important caveat for future sessions:** if you are working in an
  Anthropic-provided coding sandbox, that sandbox is *not* the target
  machine. As of this writing it was an ephemeral Ubuntu container
  with 1 vCPU / ~4GB RAM / no GPU — useful for writing and testing
  portable Python, useless for validating anything Windows-specific
  (autostart registration, global hotkeys, actual microphone capture,
  Windows Credential Manager behavior). Those need manual verification
  on the user's real machine and should be called out explicitly when
  built, not assumed to work.

## 3. Locked v1 scope

**In scope:**
- Core background service (Python), with a text/CLI interface that
  remains permanently available (not just for v1 — voice is an
  additional interface, never a replacement).
- **Voice-lite**: global hotkey / push-to-talk → STT → core → TTS.
  *Not* always-listening wake-word detection — that's v1.1.
- Canvas polling sync (courses, assignments, calendar events, grades
  where exposed) with diffing against local state, not blind overwrite.
- Document ingestion pipeline: syllabi, lecture materials, notes, study
  guides → chunked, locally embedded, retrievable. One-time Claude pass
  per syllabus to extract structured facts (exam dates, grading
  breakdown, late policy) with provenance.
- Source-authority-based fact resolution (not "Canvas is always
  truth") — authority is a function of source type, recency, and
  explicitness; genuine conflicts are surfaced to the user, never
  silently resolved.
- Assessment/preparedness model: assessments link to the concepts and
  documents they cover (optionally weighted by importance), and
  preparedness queries are explainable from actual mastery evidence.
- Event-sourced mastery: an append-only ledger of mastery evidence
  (quiz answers, study sessions, self-reports, flagged mistakes); any
  "score" is a derived, recomputable view, never a stored, overwritten
  number.
- Local task tracking (not_started/in_progress/done/skipped/blocked)
  fully independent of Canvas submission state — Canvas status is one
  input signal, never a stand-in for local completion state.
- Notification severity engine (Critical/Notable/Ambient) — pull-based
  via the daily briefing and on-demand queries in v1, not proactive
  interrupts.
- Credential vault via OS-native store (`keyring`; Windows Credential
  Manager on the target machine).

**Explicitly deferred — do not build without re-opening scope:**
- v1.1: always-listening wake-word activation, fully hands-free
  conversation.
- v1.1+: proactive unprompted notifications/interrupts.
- v2: dashboard UI.
- v2: cross-course concept prerequisite modeling.
- Never (unless requested): clap detection — deliberately dropped
  during design as unreliable (false positives from doors, keyboards,
  etc.); hotkey/wake-phrase are the supported activation methods.

## 4. Architectural principles

1. **Claude is a reasoning engine invoked selectively, not the state
   machine.** Retrieval, math, scheduling, diffing, and CRUD happen
   locally in Python. Claude is called for judgment: synthesis,
   natural-language understanding, deciding what to study next,
   generating the briefing narrative. Don't build rule engines trying
   to replicate judgment; don't burn API calls on things local code
   already does correctly.
2. **Local-first, always.** The core service must degrade gracefully
   with no network/API access for anything that doesn't strictly
   require it (health check, task tracking, browsing already-ingested
   facts all still work offline).
3. **Provenance over silent resolution.** Any fact that could be
   wrong, stale, or contested carries its source, explicitness, and
   last-verified time. Conflicting authoritative facts are surfaced to
   the user, never silently picked between.
4. **History over overwrite.** Mastery evidence, fact versions, and
   Canvas sync diffs are append-only / versioned. Anything the system
   currently believes must be explainable by replaying the underlying
   evidence — "why does it think that?" always has a real answer.
5. **Credentials never touch the LLM or logs.** No secret value is
   ever placed in a prompt, a log line, a stack trace, or a `repr()`.
   `asos.credentials` is the only module allowed to call `keyring`
   directly.
6. **No enterprise-pattern overhead for a single-user app.** No
   microservices, no message queues, no plugin frameworks. One process,
   one SQLite database, straightforward modules. Add abstraction only
   when a second concrete case actually needs it.
7. **Schema evolves via migrations, not redesigns.** Alembic from day
   one. Changing the schema means writing a migration and updating the
   decision log below in the same change — never quietly diverging
   model code from what migrations describe.
8. **Text/CLI access is permanent**, not a v1-only debugging shim —
   voice degrades to it, it doesn't get replaced by it.

## 5. Architecture (current, foundation-only — Canvas/Claude/embeddings/voice not yet implemented)

```
Interaction Layer (not yet built beyond the CLI)
  - CLI/text (implemented: asos.cli)
  - Voice-lite: hotkey/PTT -> STT -> core -> TTS   [v1, not yet built]

Core Service (asos.service.core.CoreService)
  - Lifecycle: start / request_stop / run_forever   [implemented]
  - Heartbeat-based health check                    [implemented]
  - Canvas sync worker                              [not yet built]
  - Content ingestion pipeline                      [not yet built]
  - Authority/conflict resolution engine             [not yet built]
  - Mastery engine (derived scoring over the ledger) [not yet built]
  - Assessment/preparedness engine                   [not yet built]
  - Task state tracker                               [schema only]
  - Notification severity engine                     [schema only]
  - Claude API client                                [not yet built]

Local Data Store
  - SQLite via SQLAlchemy models + Alembic migrations [implemented, full v1 schema]
  - Vector index for document chunks                  [not yet built — schema has a placeholder column]
  - OS-native credential vault (asos.credentials)      [implemented]
```

### Concurrency model

Single process, single SQLite connection pool with
`check_same_thread=False` because all DB access is expected to be
serialized through the core service's own logic (the heartbeat loop
today; future workers will tick from the same loop or a small number
of cooperating threads). This is deliberately not a multi-process or
async-everything design — unnecessary for a single-user local app.
Revisit only if a concrete future worker (e.g. STT running
concurrently with a Canvas poll) demonstrates real contention.

## 6. Data model

Full v1 schema (see `src/asos/db/models.py` for authoritative
definitions; this is a summary):

- `courses`, `assignments`, `calendar_events` — Canvas-sourced
  structural data. `assignments.canvas_status` is explicitly documented
  as a raw signal, not the source of completion truth.
- `concepts` — hierarchical (`parent_concept_id`), scoped to a course.
- `mastery_events` — **append-only ledger.** `event_type` (quiz_answer /
  study_session / self_report / mistake_flagged), `outcome`,
  `outcome_score` (0.0–1.0, what any derived-score function will
  consume), optional `self_rating`. No `mastery_score` column exists
  anywhere — it is always computed, never stored.
- `documents`, `document_chunks` — ingested syllabi/lecture
  materials/notes/study guides. `document_chunks.embedding` is a
  reserved nullable `BLOB` column; the actual vector index technology
  is an open decision for the embeddings milestone (see Section 8).
- `sources` — reference table of source *types* (canvas_api,
  canvas_calendar_auto, syllabus, professor_announcement,
  lecture_recording, user_stated, claude_inferred) with a
  `base_authority_weight`.
- `facts` — provenance-carrying facts: `subject`, `value`, `source_id`,
  optional `document_id`, `explicitness` (explicit_statement / inferred
  / default_template), `confidence`, `verified_at`,
  `superseded_by_fact_id`, `conflict_status`. Authority is computed at
  query time from source weight + explicitness + recency — deliberately
  *not* pre-baked into a single stored ranking, since "which fact wins"
  can change as new facts arrive.
- `assessments`, `assessment_concepts` (optional `importance` 1–5),
  `assessment_documents` — the preparedness evidence model.
- `tasks` — `task_type`, `state` (not_started/in_progress/done/
  skipped/blocked), optional `related_assignment_id` (nullable — many
  tasks have no Canvas counterpart at all), `blocked_reason`.
- `notifications` — `severity` (critical/notable/ambient), `delivered`
  flag, links to the course/task/assessment it concerns.
- `study_sessions` + `study_session_concepts` — which concepts a study
  session touched.
- `episodic_notes` — the semantic-memory tier: short, Claude-written,
  structured summaries extracted from conversations ("still confused
  about light reactions despite 3 reviews"), scoped to a course/concept.
  Deliberately not raw chat transcripts.

Migrations live in `migrations/versions/`. The first migration
(`initial v1 schema`) creates all of the above.

## 7. Acceptance criteria for v1

Copied verbatim from the locked design conversation. A criterion is
"done" only when there's a passing automated test (where feasible) or,
for the Windows-only pieces this sandbox can't verify, an explicit
manual check the user has confirmed.

1. Fresh Canvas sync pulls all active courses/assignments/calendar
   events into local DB on first run.
2. Re-sync after a Canvas-side change produces a diff event, not a
   silent overwrite — old value retained in history.
3. Credentials never appear in any log file or Claude API payload.
4. Dropping a syllabus PDF into the watched folder yields chunks in the
   vector index plus provenance-tagged facts for exam dates, grading
   breakdown, and late policy (where present).
5. A study guide can be linked to an assessment and its chunks become
   retrievable when querying preparedness for that assessment.
6. Two conflicting facts about the same subject produce a surfaced
   conflict, not a silently chosen value.
7. Once resolved via voice/text, the resolution is stored as a
   high-authority fact and does not resurface.
8. An assessment with linked concepts returns a preparedness breakdown
   (strong/weak/no-evidence), never a fabricated single aggregate with
   no explanation available.
9. "Why am I weak on X" surfaces actual underlying mastery events, not
   just a restated score.
10. A task with no Canvas counterpart can be created, updated through
    all five states, and persists independent of any Canvas assignment.
11. Marking a Canvas-linked task `done` locally doesn't alter/require a
    Canvas submission, and vice versa.
12. Mastery events accumulate (never overwritten); derived score
    changes appropriately with new evidence.
13. Notification severity classification + delivery bundling/rate
    limiting/quiet hours all behave per the severity engine's rules.
14. Voice-lite hotkey → STT → core → TTS works end-to-end for a
    briefing + one Q&A exchange, no text required.
15. CLI/text path works identically for every feature above (voice is
    an interface, not a separate code path).
16. "Wake up AsOS" (via hotkey) produces a real, DB-traceable briefing
    across ≥2 courses: schedule, one Critical/Notable item, one weak
    concept — no hallucinated content.

## 8. Implementation progress

### Done (this session — foundation milestone)
- Environment inspected: target is Windows, CPU-only, no GPU (user-
  confirmed; the coding sandbox itself is an unrelated ephemeral Linux
  container — see Section 2).
- Project scaffolded under version control (`git`), dependency/env
  management via `uv` + `pyproject.toml`.
- Cross-platform path resolution (`asos.config`, via `platformdirs`),
  overridable with `ASOS_DATA_DIR` / `ASOS_LOG_DIR` for tests.
- Credential vault (`asos.credentials.CredentialVault`) wrapping
  `keyring`, with a `Protocol`-typed backend for dependency injection in
  tests, zero secret-value logging (test-verified), and a CLI that
  fails with a friendly message rather than a stack trace when no OS
  credential store is reachable.
- Full v1 SQLAlchemy schema (17 tables, `src/asos/db/models.py`) +
  first Alembic migration, verified to apply and cleanly reverse.
- `CoreService` skeleton: lifecycle (start/stop), heartbeat-based
  health check, DB engine/session setup. Verified as a real running
  process: started, wrote heartbeats, responded to `SIGINT` with a
  clean shutdown, logged nothing sensitive.
- `asos` CLI (`typer`): `paths`, `init-db`, `run`, `health`,
  `creds set|check|delete`.
- 32 automated tests (`pytest`), all passing, covering credential
  vault behavior (including "secret never logged"), full schema
  behavior (event-sourced mastery, fact provenance/conflict fields,
  Canvas-independent task state, assessment-concept linking), real
  Alembic upgrade/downgrade via subprocess, heartbeat/health logic,
  service lifecycle, and CLI smoke tests.

### Explicitly not started yet (per user instruction for this milestone)
- Canvas API integration
- Claude API integration
- Document ingestion / embeddings / vector index
- Voice pipeline (hotkey capture, STT, TTS)
- Autostart registration (Windows Task Scheduler / Startup folder)
- Dashboard UI

### Open technical decisions for upcoming milestones
- Exact vector index technology for `document_chunks.embedding`
  (candidates: sqlite-vec, a local Chroma instance, or a flat numpy
  index — pick when the ingestion milestone starts; don't pre-decide).
- Exact local embedding model (e.g. bge-small vs all-MiniLM) — pick
  against real CPU latency measurements on the target machine, not
  assumptions made in this sandbox.
- Global hotkey library choice for Windows (e.g. `keyboard` vs
  `pynput` vs a Windows-native approach) — deferred to the voice
  milestone.
- Windows autostart mechanism (Task Scheduler vs Startup-folder
  shortcut vs a Windows service) — deferred; not part of the
  foundation milestone.

## 9. Key technical decisions and why

| Decision | Reasoning |
|---|---|
| `uv` for dependency/env management | Fast, single-file `pyproject.toml`-based, no extra daemon or lockfile ceremony beyond what's needed for a single-user app — simpler than Poetry for this scope. |
| SQLite (not Postgres/etc.) | Single-user, single-machine, local-first by design. No server process to manage; `keyring`-style OS-native tooling exists for everything else this app needs. |
| SQLAlchemy 2.0 + Alembic from the start | User explicitly asked not to treat the schema as disposable. Autogenerated migrations were verified (upgrade + downgrade) against the real schema before any application logic was built on top. |
| Enums stored as validated strings, not native SQL enums | SQLite has no native enum type; native-enum emulation in other DBs makes adding a new value a migration. String + `CHECK` constraint (via `SAEnum(..., native_enum=False)`) gets the same safety with trivial future extension. |
| `platformdirs` for all filesystem paths | The target OS is Windows; `%LOCALAPPDATA%` layout differs from Linux/macOS. Centralizing this in `asos.config` means no other module ever hardcodes an OS assumption. |
| `keyring` for the credential vault | Uses Windows Credential Manager natively on the target machine. `CredentialVault` wraps it behind a `Protocol` so tests never need a real OS credential store — verified with an in-memory fake and, separately, a real (dev-only) file-backed `keyring` backend (`keyrings.alt`) to exercise the actual library end-to-end in this sandbox. |
| Mastery as an append-only ledger (`mastery_events`), no stored score | Locked explicitly by the user: overwriting a single confidence number destroys the evidence trail needed to answer "why does it think that?" and to model decay over time. Derived scores are a query, not a column. |
| `facts` carry `source_id` + `explicitness` + `verified_at` rather than a single trust value | Locked explicitly by the user: Canvas is not universally authoritative (e.g. a professor's explicit announcement can outrank an unedited Canvas calendar entry). Authority must be computed from multiple axes at query time, and genuine conflicts must be surfaced, not silently resolved. |
| `tasks` fully decoupled from `assignments`/Canvas status | Locked explicitly by the user: Canvas submission is one signal among several; many real study behaviors (reading, review, prep) have no Canvas counterpart at all. |
| Heartbeat-file health check instead of process polling | Trivially cross-platform (a JSON file with a timestamp/PID/status), no OS-specific process-inspection code needed for a "is it alive" check. |
| Typer for the CLI | Small, ergonomic, keeps the debugging/admin surface permanently available per the architectural principle that voice never replaces text access. |
| Single-process, threaded (not async) core service | No concrete concurrency need yet justifies asyncio or multiprocessing. Revisit only when a real worker (e.g. STT capture running alongside a Canvas poll) demonstrates contention under the current model. |

---

*Last updated: foundation milestone (project scaffolding, schema,
migrations, credential vault, core service skeleton, health check).
Update this file's Section 8 and, when applicable, Section 9, at the
end of every future implementation milestone.*
