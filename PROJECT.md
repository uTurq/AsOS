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
  - Canvas sync worker                              [implemented as a standalone module + CLI command;
                                                       NOT yet wired into CoreService's own loop for
                                                       periodic/automatic polling — currently a manual
                                                       `asos canvas sync` invocation only]
  - Content ingestion pipeline                      [implemented as standalone modules
                                                       (asos.documents.*) + CLI commands
                                                       (`asos docs ingest`/`search`/`extract-facts`);
                                                       uses a placeholder (non-semantic) embedding —
                                                       see open decisions. NOT yet wired into a
                                                       watched-folder auto-ingestion worker.]
  - Authority/conflict resolution engine             [implemented as a
                                                       standalone module (asos.facts.authority) + CLI
                                                       commands (`asos facts conflicts`/`resolve`);
                                                       now fed real data by syllabus extraction, but
                                                       Canvas sync still doesn't write to `facts`]
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
   events into local DB on first run. **[Verified against mocked Canvas
   API responses; NOT yet verified against a real Canvas account —
   this sandbox cannot reach Canvas's network. Needs a real-world check
   once credentials are set on the target machine.]**
2. Re-sync after a Canvas-side change produces a diff event, not a
   silent overwrite — old value retained in history. **[Verified,
   including a dedicated regression test for a datetime-reload edge
   case found during development.]**
3. Credentials never appear in any log file or Claude API payload.
   **[Verified for the credential vault and the Canvas client
   specifically — token is sent only via the Authorization header and
   confirmed absent from exception messages.]**
4. Dropping a syllabus PDF into the watched folder yields chunks in the
   vector index plus provenance-tagged facts for exam dates, grading
   breakdown, and late policy (where present). **[Partially verified:
   `asos docs ingest` does the parse/chunk/embed/store part end-to-end
   on real PDFs, and `extract_syllabus_facts` is fully tested against a
   fake Claude client producing exactly these fact categories with
   correct provenance. NOT yet verified: (a) a real Claude call doing
   real extraction from real syllabus text — untested live, see above
   — and (b) there's no watched-folder automation yet, ingestion is a
   manual CLI command.]**
5. A study guide can be linked to an assessment and its chunks become
   retrievable when querying preparedness for that assessment.
   **[Retrieval scoped to a document-id set is implemented and tested
   (`search_chunks(..., document_ids=[...])`,
   `get_documents_for_assessment`); the actual UI/flow for confirming
   which documents cover which assessment doesn't exist yet — that's
   the assessment-linking milestone, next in the roadmap.]**
6. Two conflicting facts about the same subject produce a surfaced
   conflict, not a silently chosen value. **[Verified — a mixed-signal
   case (higher authority but staler vs. lower authority but fresher)
   correctly surfaces via `resolve_fact`/`find_all_conflicts`, and a
   clear-dominance case correctly auto-resolves instead.]**
7. Once resolved via voice/text, the resolution is stored as a
   high-authority fact and does not resurface. **[Verified via text
   (`asos facts resolve`); voice path doesn't exist yet, but shares the
   same underlying `resolve_conflict_with_user_statement()` call per
   architectural principle 1/8, so it inherits this once voice-lite is
   built.]**
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

### Done (this session — document ingestion / embeddings / Claude extraction milestone)
- `asos/documents/parsing.py`: extracts text from PDF (per-page),
  DOCX (paragraph groups), PPTX (per-slide), and plain text/Markdown.
  Verified against real generated fixture files for every format, not
  just mocks (a real PDF via `fpdf2`, real DOCX/PPTX via
  `python-docx`/`python-pptx`).
- `asos/documents/chunking.py`: packs parsed text into ~400-word
  chunks (500 max); an oversized single paragraph is hard-split rather
  than either truncated or left as one unbounded chunk. A real bug was
  caught in a self-written test here too (the test's own expectation
  was wrong, not the code) — worth noting only because it shows the
  test-after-each-piece habit catching problems on both sides.
- `asos/documents/embeddings.py`: defines the `EmbeddingProvider`
  interface plus exactly one implementation —
  `HashingEmbeddingProvider`, a deterministic bag-of-words placeholder.
  **This is explicitly NOT a real semantic embedding model** — it
  captures word overlap, not meaning. It exists so the full pipeline
  (chunk -> embed -> store -> retrieve) could be built and correctly
  tested end-to-end now, without a real model dependency this sandbox
  can't download (no network access to a model hub). Swapping in a
  real local model later should only mean adding one new class and
  changing one construction site — see the module docstring.
- `asos/documents/ingestion.py`: `ingest_document()` — parses, chunks,
  embeds, and stores a document, copying the source file into AsOS's
  own data directory first (so ingestion doesn't silently depend on
  the original file staying where it was, e.g. a Downloads folder the
  user later cleans up). Verified with real files end-to-end, including
  that the original can be deleted afterward without affecting AsOS.
- `asos/documents/retrieval.py`: brute-force cosine-similarity search
  over `document_chunks`, scoped by course or by an explicit document-
  id set (e.g. the documents linked to one assessment). Deliberately
  not a vector index (sqlite-vec/Chroma) — see decision table.
- `asos/documents/extraction.py` + `asos/documents/claude_client.py`:
  the one-time structured-fact-extraction pass. `ClaudeClient` is an
  injectable protocol (same DI pattern as the Canvas HTTP session and
  the keyring backend); extraction is fully tested against a fake
  client (valid JSON, markdown-fenced JSON, malformed JSON, wrong
  shape, missing fields — all produce either correct facts or a clear
  `ExtractionError`). `AnthropicClaudeClient` is a real implementation
  against the documented Messages API shape, but **has not been
  exercised with a real API key or a live network call** — that
  requires the user's own `anthropic_api_key` and explicit awareness
  that it's a real, billed request. Extracted facts are recorded via
  `record_fact()` with `source_type=SYLLABUS`, `document_id` set for
  provenance, and MEDIUM (not HIGH) confidence by default — see
  decision table for why.
- `asos docs ingest` / `asos docs search` / `asos docs extract-facts`
  CLI commands. `ingest` and `search` verified end-to-end against a
  real file through the real CLI binary (not just pytest); `extract-
  facts` verified to fail cleanly and actionably when credentials
  aren't set (the actual live-extraction path is untested, per above).
- 90 automated tests passing (was 54 after the authority-engine
  milestone).

### Done (previous session — fact authority / conflict-resolution milestone)
- `asos/facts/authority.py`: the authority engine implementing the
  locked design — a fact only auto-wins over a competitor if it's at
  least as strong on ALL THREE axes (source authority weight,
  explicitness, recency); mixed signals are surfaced as a genuine
  conflict rather than resolved via a single blended score. Verified
  against both worked examples from the design conversation: a recent
  explicit professor announcement correctly outranks a stale
  auto-generated Canvas calendar entry (auto-resolves); a syllabus
  date vs. a more-recently-synced but less-explicit Canvas calendar
  date correctly surfaces as unresolved (neither dominates).
- `resolve_fact()` also persists the `conflict_status` annotation onto
  the underlying `Fact` rows (bookkeeping only — never touches
  subject/value/source/verified_at) so other code can query "what's
  unresolved" without recomputing.
- `resolve_conflict_with_user_statement()`: the user's own correction
  becomes a new `USER_STATED` fact, and every previously-current fact
  for that subject is marked superseded + resolved — never deleted,
  but excluded from future candidate sets, so a resolved conflict
  never resurfaces (verified — acceptance criterion 7).
- `find_all_conflicts()`: scans every (course, subject) pair for
  unresolved conflicts — this is what a future briefing/notification
  pass will call.
- `seed_default_sources()`: idempotently seeds the `sources` reference
  table with default authority weights; wired into both `CoreService`
  startup and `asos init-db`, so a fresh DB is always immediately
  usable without a manual seeding step.
- `asos facts conflicts` / `asos facts resolve <subject> <value>` CLI
  commands — verified end-to-end against a real (non-mocked) SQLite DB,
  not just the test suite: surfaced a real conflict, resolved it via
  the CLI, confirmed it stopped appearing afterward.
- 54 automated tests passing (was 44 after the Canvas sync milestone).

### Done (previous session — Canvas sync milestone)
- `CanvasClient` (`asos/canvas/client.py`): thin, paginated Canvas REST
  API v1 wrapper (`get_active_courses`, `get_assignments`,
  `get_calendar_events`), HTTP transport injectable for testing, token
  sent only via `Authorization` header, never logged or included in
  exception messages. Followed real Canvas pagination (`Link: rel=next`
  headers) correctly under test.
- `CanvasSyncWorker` (`asos/canvas/sync.py`): pulls courses/assignments/
  calendar events and reconciles against local DB — inserts new
  entities, diffs known ones field-by-field, and records every change
  in the new `sync_change_log` table (old value retained, never
  silently overwritten — satisfies acceptance criteria 1 and 2).
  Verified: initial sync creates rows; re-sync with no Canvas-side
  change produces zero new diff entries; re-sync with a moved due date
  produces exactly one diff entry with the old date preserved; a
  Canvas-side status change (e.g. assignment graded) never touches a
  locally-tracked `Task`, confirming the Canvas/local-task independence
  principle actually holds in the sync path, not just in the schema.
- New `sync_change_log` table + migration, kept deliberately separate
  from the `facts` provenance model (see decision table below).
- `asos canvas sync` CLI command; fails with a clear, actionable
  message (not a crash) when Canvas credentials aren't set yet.
- **Bug caught and fixed during this milestone** (see decision log):
  SQLite silently returns naive datetimes on reload even for
  `DateTime(timezone=True)` columns, which would have caused false
  "changed" diffs after any process restart. Fixed by standardizing on
  naive-UTC datetimes everywhere via a shared `asos.db.base._now()`
  helper; added a regression test that explicitly forces identity-map
  eviction to catch any recurrence.
- 44 automated tests passing (was 32 after the foundation milestone).

### Done (previous session — foundation milestone)
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

### Explicitly not started yet
- **Real embedding model.** Only the `HashingEmbeddingProvider`
  placeholder exists (see above) — real semantic retrieval quality
  needs a real local model, chosen and latency-tested on the actual
  Windows CPU-only machine, not assumed here.
- **Live Claude API verification.** `AnthropicClaudeClient` exists and
  matches the documented API shape but has never made a real call —
  needs the user's own `anthropic_api_key` and awareness it's billed.
- **Live Canvas verification** (carried over from the Canvas sync
  milestone — still true). This sandbox's network egress is restricted
  to package registries (PyPI, npm, GitHub, etc.) and cannot reach any
  Canvas instance. `CanvasClient`/`CanvasSyncWorker` are thoroughly
  unit-tested against realistic mocked Canvas API responses, but a real
  end-to-end sync against an actual Canvas account has NOT been
  verified and needs to happen on the user's own machine with real
  credentials (`asos creds set canvas_base_url` / `asos creds set
  canvas_api_token`, then `asos canvas sync`).
- Deleted/withdrawn Canvas entities are logged for visibility but not
  pruned locally — see the decision table for reasoning; revisit if
  this proves wrong in practice.
- Periodic/scheduled Canvas polling (the sync worker currently runs
  once per invocation; wiring it into `CoreService`'s loop on an
  interval is a natural next step, not yet done).
- Wiring Canvas sync to also record assignment due dates as `facts`
  (so they can participate in conflict resolution against
  syllabus-extracted dates) — currently only syllabus extraction
  writes to `facts`.
- A watched-folder worker that automatically ingests dropped files —
  `docs ingest` is a manual CLI command for now.
- Manually confirming assessment-to-concept/document links from
  ingested study guides (the schema and `get_documents_for_assessment`
  helper exist; nothing yet proposes or confirms these links).
- Document ingestion / embeddings / vector index
- Voice pipeline (hotkey capture, STT, TTS)
- Autostart registration (Windows Task Scheduler / Startup folder)
- Dashboard UI

### Open technical decisions for upcoming milestones
- Exact local embedding model (e.g. bge-small vs all-MiniLM) — pick
  against real CPU latency measurements on the target machine, not
  assumptions made in this sandbox. `HashingEmbeddingProvider` is a
  placeholder, not a candidate.
- Whether a real vector index (sqlite-vec, Chroma) is ever actually
  needed — current brute-force cosine similarity is deliberately kept
  simple for a single-semester corpus size; revisit only if real usage
  shows it's too slow.
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
| All datetimes stored and compared as naive UTC (no `DateTime(timezone=True)`) | Caught during Canvas-sync development: SQLite doesn't actually preserve tzinfo — a `DateTime(timezone=True)` column looks timezone-aware only while the object stays in SQLAlchemy's in-memory identity map, and silently comes back naive on any reload (service restart, cache eviction, garbage collection). A naive/aware comparison never raises, it just silently evaluates unequal — which would have made the sync worker flag every synced date as "changed" after any restart. Being explicitly naive-UTC everywhere (via `asos.db.base._now()`) removes the trap instead of hiding it behind a flag that doesn't do what it implies on this backend. A regression test (`test_due_at_survives_identity_map_eviction_and_reload`) forces eviction explicitly so this can't silently regress. |
| `sync_change_log` kept separate from `facts` | Both are "history of what changed," but for different reasons: `sync_change_log` is an internal Canvas-poll audit trail (did anything change since last check, what was it before) with no authority weighting. `facts` is the cross-source, authority-weighted provenance model for the conflict-resolution engine (a separate, not-yet-built milestone). Conflating them would mean every Canvas field sync has to reason about source authority before it's needed, and would make the authority engine's job ambiguous about which history it owns. |
| Canvas entities that disappear from a poll are not deleted locally | A course/assignment vanishing from Canvas's "active" filter is often a term boundary or a temporary Canvas-side hiccup, not something the user wants silently destroyed along with any local task/mastery data linked to it. The `SyncChangeType.DELETED` enum value is reserved for this, but detecting and logging disappearances is NOT yet implemented — the current sync worker simply leaves untouched anything Canvas stops returning. Actual pruning should remain an explicit user action, not automatic, whenever this is built. |
| Fact authority resolved by 3-axis dominance, not a single blended score | A blended score (e.g. weighted sum of authority+explicitness+recency) would hide *why* a fact won and could pick something that's only "better on average" while being staler or less explicit than the alternative — the opposite of the transparency the design explicitly called for. Requiring dominance on all three axes independently means a fact only auto-wins when it's unambiguously better, and any genuine trade-off (higher authority but staler vs. lower authority but fresher) correctly surfaces as a conflict instead of being guessed at. |
| Fact conflict resolution never deletes or edits existing facts | Resolving a conflict (`resolve_conflict_with_user_statement`) creates a new fact and marks previous ones `superseded_by_fact_id` + `conflict_status=RESOLVED`, rather than overwriting them. Mirrors the same append-only-history principle used for `mastery_events` — "why did it used to think X" stays answerable. |
| `seed_default_sources()` is a Python function called on startup, not an Alembic data migration | Keeps the default authority weights in exactly one place (avoiding a second copy embedded in a migration file that could silently drift from the code), and is trivially idempotent. Standard Alembic guidance is that data migrations should be self-contained with literal values rather than importing application code (since the app's models can change after a migration is written) — but for a single-user app, the duplication risk of hand-copying the weight table into a migration outweighed that purity concern here. |
| Placeholder (`HashingEmbeddingProvider`) instead of a real embedding model, for now | This sandbox cannot download real model weights (no network access to a model hub). Rather than block the whole ingestion pipeline on that, the embedding step is an injectable interface with exactly one implementation swap point — the placeholder proves the plumbing (chunk -> embed -> store -> cosine-similarity retrieve) works correctly, and it's explicitly documented as non-semantic so nobody mistakes it for a real quality bar. |
| Brute-force cosine similarity, no vector index library | A single user's single-semester corpus is realistically a few dozen documents and at most a few thousand chunks — a plain Python loop over rows already fetched from SQLite is fast enough, and adding sqlite-vec/Chroma now would be complexity with no measured benefit. Revisit only if real usage proves this too slow. |
| Document ingestion copies the source file into AsOS's own data directory rather than referencing it in place | The original file (e.g. a Canvas download in the user's Downloads folder) is outside AsOS's control and could be moved, renamed, or deleted at any time. Copying once at ingest time means AsOS's record of a document never silently breaks because of something the user did elsewhere. |
| Syllabus-extracted facts get MEDIUM confidence by default, not HIGH, despite `explicitness=EXPLICIT_STATEMENT` | `explicitness` describes the *source document* (the syllabus states this directly, it isn't inferred from context) — but the *extraction mechanism* is still an LLM parse of that document, which can misread or hallucinate. Confidence is deliberately more conservative than a human directly transcribing the same sentence would warrant, so a wrong extraction doesn't inherit unwarranted trust just because the underlying sentence was unambiguous. |
| Claude client (for extraction) and Canvas HTTP session both use the same injectable-protocol DI pattern | Consistency: the same pattern already proven for `keyring` (credentials) and `requests.Session` (Canvas) means every external-service boundary in this codebase is tested the same way — a fake implementing the same small interface — rather than each milestone inventing its own mocking approach. |

---

*Last updated: foundation milestone (project scaffolding, schema,
migrations, credential vault, core service skeleton, health check).
Update this file's Section 8 and, when applicable, Section 9, at the
end of every future implementation milestone.*
