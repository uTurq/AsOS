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
                                                       `asos canvas sync` invocation only. BLOCKED on the
                                                       user's institution for live verification — see
                                                       "Explicitly not started yet"]
  - ICS calendar-feed fallback (asos.calendar_feed.*) [implemented + CLI (`asos calendar sync`); the
                                                       real-world workaround for when Canvas API tokens
                                                       are institutionally disabled. Confirmed working
                                                       end-to-end against a synthetic feed; not yet
                                                       tried against the user's real school feed URL]
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
  - Mastery engine (derived scoring over the ledger) [implemented: asos.mastery.events +
                                                       asos.mastery.scoring; CLI commands
                                                       (`asos study record`/`mastery`)]
  - Assessment/preparedness engine                   [implemented: asos.assessments.linking +
                                                       asos.assessments.preparedness; CLI command
                                                       (`asos study preparedness`); verified against
                                                       the exact worked example from the original
                                                       design conversation]
  - Task state tracker                               [implemented: asos.tasks.management;
                                                       CLI (`asos task create/update/list`)]
  - Notification severity engine                     [implemented: asos.notifications.classification/
                                                       delivery/scan; CLI (`asos notify
                                                       scan/critical/briefing/ambient`); NOT yet
                                                       wired into CoreService's own loop for periodic
                                                       automatic scanning — currently a manual
                                                       `asos notify scan` invocation only, same
                                                       status as Canvas sync]
  - Claude API client                                [implemented: asos.llm.client (protocol) +
                                                       asos.llm.anthropic_client (real impl, shared
                                                       across extraction and the core assistant);
                                                       asos.core.context + asos.core.assistant tie
                                                       everything built so far into actual Q&A and
                                                       daily-briefing generation via CLI (`asos ask`/
                                                       `asos brief`)]

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
   no explanation available. **[Verified — including the exact worked
   example from the design conversation, both in the test suite and
   manually through the real CLI.]**
9. "Why am I weak on X" surfaces actual underlying mastery events, not
   just a restated score. **[Verified — `asos study mastery` prints the
   raw events including notes, e.g. "mixed up numerator and
   denominator", not just a number.]**
10. A task with no Canvas counterpart can be created, updated through
    all five states, and persists independent of any Canvas assignment.
    **[Verified.]**
11. Marking a Canvas-linked task `done` locally doesn't alter/require a
    Canvas submission, and vice versa. **[Verified — the sync worker's
    equivalent test from the Canvas milestone and this milestone's own
    task-management test both confirm `canvas_status` is untouched.]**
12. Mastery events accumulate (never overwritten); derived score
    changes appropriately with new evidence. **[Verified — including a
    dedicated test confirming a recent miss visibly lowers the score
    even after a run of correct answers, and that stale-but-perfect
    history alone does NOT register as confidently "strong."]**
13. Notification severity classification + delivery bundling/rate
    limiting/quiet hours all behave per the severity engine's rules.
    **[Verified — escalation-only dedup, quiet-hours wraparound, and
    the daily rate limit are each directly tested; quiet hours was
    additionally confirmed against the sandbox's real wall-clock time,
    not just synthetic timestamps.]**
14. Voice-lite hotkey → STT → core → TTS works end-to-end for a
    briefing + one Q&A exchange, no text required.
15. CLI/text path works identically for every feature above (voice is
    an interface, not a separate code path). **[The CLI/text path now
    exists and is the ONLY path — `asos ask`/`asos brief` are what
    voice-lite will call into once built, not a parallel
    implementation, so this criterion is satisfied by construction
    once voice-lite reuses `asos.core.assistant` directly.]**
16. "Wake up AsOS" (via hotkey) produces a real, DB-traceable briefing
    across ≥2 courses: schedule, one Critical/Notable item, one weak
    concept — no hallucinated content. **[The text equivalent (`asos
    brief`) is built and its prompt-grounding is verified end-to-end
    short of the live network call — see above. The actual hotkey
    trigger doesn't exist yet (voice-lite, step 10); this criterion
    will be fully satisfied once that thin layer calls the same
    `generate_daily_briefing()` already built and tested here.]**

## 8. Implementation progress

### Done (this session — asos docs show, prompted by real diagnostic need)
- **Real diagnostic need**: after `asos facts list` showed only 1
  extracted fact for one real syllabus (vs. 7 and 3 for the other two
  ingested that batch), needed a way to tell whether that's because
  the syllabus genuinely doesn't state exam dates/grading in prose, or
  because PDF table extraction (a known real weakness — text
  extraction handles tables poorly) mangled something before Claude
  ever saw it. `docs search`'s relevance ranking wasn't a reliable way
  to check this, since the placeholder embedding could plausibly rank
  that document's chunks low even if the content is fine.
- `asos docs show <document_id>` — dumps every chunk actually stored
  for one document, in order, with no relevance-score guessing
  involved. Caught and fixed a real bug while testing this: the
  command didn't call the `Base.metadata.create_all` safety net other
  read commands use, so a database that was never `init-db`'d raised a
  raw `sqlite3.OperationalError` instead of a clean message — fixed to
  match the pattern every other CLI command already follows.
- 187 automated tests passing (was 185 after `asos facts list`).

### Done (previous session — asos facts list, prompted by a real usability gap)
- **Real gap found by actual use**: the user ran `docs ingest-folder
  --extract-facts` on two real syllabi and got back only fact *counts*
  ("extracted 1 fact(s)", "extracted 3 fact(s)") with no way to see
  what those facts actually were — there was no command to list facts
  outside of `facts conflicts`, which only shows contested ones.
- `asos/facts/authority.py`: `list_current_facts()` — the plain "what
  does AsOS currently know" view, optionally filtered by course or by
  the specific document facts were extracted from. Correctly excludes
  superseded facts (consistent with `get_current_facts`) and returns
  everything else regardless of conflict status.
- `asos facts list [--course-id] [--document-id]` CLI command.
- 185 automated tests passing (was 181 after the batch-ingestion
  milestone).

### Done (previous session — batch document ingestion + first live syllabus extraction result)
- **First live, real-content confirmation of the syllabus-extraction
  pipeline**: the user ingested a real syllabus and ran
  `asos docs extract-facts` for real. It correctly extracted 7 facts —
  a detailed grading breakdown, an explicit late policy, and four unit
  exam dates plus the final — all matching the real document. This is
  the first time this pipeline has been validated against real content
  rather than a controlled test fixture, and it held up well.
- `asos/documents/ingestion.py`: `ingest_folder()` — batch-ingests
  every supported file directly inside a folder (non-recursive by
  design; subfolders are deliberately skipped rather than walked, to
  keep behavior predictable). Unsupported file types are silently
  skipped rather than raising, since a real folder of course materials
  will have other things in it (images, zips, etc.).
  Explicitly scoped as the smaller, faster half of a two-part want —
  full watched-folder automation (drop a file in, no command needed at
  all) remains a distinct, larger future milestone, not built here.
- `asos docs ingest-folder <dir> --source-type ... [--extract-facts]`
  CLI command — the `--extract-facts` flag chains the Claude
  extraction pass onto every ingested file in one command, for the
  exact "give it a folder, it just adds all the info" workflow the
  user asked for.
- 181 automated tests passing (was 175 after the scheduler milestone).

### Done (previous session — real-world Canvas verification results + periodic job scheduler)
- **Real-world outcome, recorded for the historical record**: the
  user's institution formally denied Canvas API token generation
  ("This is not something we allow, due to security concerns"). The
  ICS calendar feed (built last session anticipating exactly this) was
  tried instead and **works** — confirmed live: `asos calendar sync`
  against the user's real Canvas account pulled in 327 real events.
  `asos brief` was also confirmed live against real synced data for
  the first time — Claude correctly reasoned about real course names
  and even correctly inferred, unprompted, that midnight-timestamped
  items were likely housekeeping/syllabus checkpoints rather than
  timed commitments (a genuinely good piece of grounded reasoning,
  not something instructed for).
- **A real ethical judgment call, worth recording precisely**: the
  user proposed adding browser automation of their own Canvas session
  as a third data source. This was initially declined — not because
  scraping is technically hard, but because IT's stated concern
  ("we do not allow anyone to generate their own API tokens... due to
  security concerns") was reasonably read as being about automated
  programmatic access to the data generally, not narrowly about the
  literal token mechanism, and building a workaround to an explicit
  institutional "no" wasn't something to help architect. The user went
  back to IT and asked specifically about this approach; IT
  explicitly approved it ("Since it is using your own system access
  and not API integration from a third party, there is no security
  concern"). That explicit, specific authorization is what changed the
  answer — the same request would still be declined without it. This
  is exactly the intended resolution path or a values disagreement:
  raise the concern, let the person go back to the actual authority,
  proceed once genuinely authorized.
- `CoreService` gained a real, generic, tested job scheduler
  (`register_job`/`run_due_jobs`) — interval-based, per-job failure
  isolation (one job's exception never crashes the service or blocks
  others), and per-job backoff (a persistently failing job retries
  once per interval, not once per heartbeat tick). This closes a gap
  flagged as open since the Canvas sync milestone ("NOT yet wired into
  CoreService's own loop for periodic polling").
- `asos/service/jobs.py`: `register_default_jobs()` — decides which
  jobs actually make sense to run based on which credentials exist
  (Canvas sync only if both `canvas_base_url` and `canvas_api_token`
  are set; ICS sync only if `ics_feed_url` is set; notification
  scanning always). Kept deliberately separate from `CoreService`
  itself so the scheduler stays credential/network-free and testable
  in complete isolation — verified with 5 tests covering every
  combination of configured/unconfigured credentials.
- `asos run` now calls `register_default_jobs()`, so the background
  service is no longer heartbeat-only — it actually does the periodic
  work the whole system was designed around.
- Added `Assignment.description` / `.score` / `.grade` columns
  (nullable, additive-only migration) — the landing spot for whatever
  the upcoming browser-automation work extracts (assignment
  instructions and grades), decided before writing any scraping code.
- **Verified the full scheduler pipeline end-to-end for real**: set a
  real ICS credential, constructed a real `CoreService`, called
  `register_default_jobs()`, ran a single `run_one_tick()` — the exact
  method the real background loop calls every heartbeat — and
  confirmed real events landed in the database. This is what will
  happen automatically, unattended, once `asos run` is left running.
- 175 automated tests passing (was 165 after the ICS milestone).

### Done (previous session — ICS calendar-feed fallback, prompted by a real-world blocker)
- **Real-world context**: the user's Canvas administrator disabled
  self-service API token generation entirely (institution policy).
  Rather than block on IT approving a token, built a genuine fallback:
  most Canvas instances still expose a private per-user ICS calendar
  feed URL (Calendar page -> "Calendar Feed") that works with no token.
  This gets due dates and scheduled events; it does NOT get grades or
  submission status — a real, disclosed limitation, not a full
  Canvas-API replacement.
- **Two schema fixes made along the way**, both because "Canvas" had
  been baked into field names that needed to become source-agnostic
  once a second calendar source existed:
  - `calendar_events.canvas_event_id` -> `external_event_id`, plus a
    new `source` enum column (canvas/ics_feed/manual).
  - `sync_change_log.canvas_id` -> `external_id` (it's a shared audit
    column across course/assignment/calendar_event changes, not
    Canvas-specific).
  Both were written as true renames (SQLite batch-mode
  `alter_column`/backfill), NOT autogenerate's default drop-and-add —
  each was verified by seeding real data, running the migration, and
  confirming the data survived the upgrade AND a downgrade back.
- `asos/calendar_feed/parsing.py`: `parse_ics()` — normalizes ICS
  events (including all-day dates and timezone-aware datetimes) to
  naive UTC per the existing project-wide convention. A fixture bug
  was caught and fixed during testing: a synthetic fixed-offset
  timezone doesn't round-trip through real ICS serialization the way
  an actual IANA timezone does (which is what real Canvas feeds
  always use) — the test was rewritten to use `zoneinfo.ZoneInfo`
  instead of a bug in the parser itself.
- `asos/calendar_feed/sync.py`: `fetch_ics()` (injectable HTTP
  session, same DI pattern as Canvas) + `sync_ics_text()`, reusing the
  same `sync_change_log` diff/audit trail Canvas sync already writes
  to — this is just a second writer into the same `calendar_events`
  table, not a parallel system.
- `asos creds set ics_feed_url` + `asos calendar sync` CLI commands.
- **Verified genuinely end-to-end, not just against fakes**: served a
  real ICS file over a real local HTTP server, pointed the real CLI
  at it, and confirmed events were correctly fetched, parsed, and
  stored — then ran the sync again and confirmed zero spurious changes
  were detected (real idempotency, not asserted idempotency).
- 165 automated tests passing (was 153 after the core assistant
  milestone).

### Done (previous session — core assistant milestone: text/CLI interface wiring Claude into everything)
- **Small refactor first**: moved the `ClaudeClient` protocol and the
  real `AnthropicClaudeClient` implementation out of
  `asos.documents.*` into a shared `asos/llm/` package
  (`asos/llm/client.py`, `asos/llm/anthropic_client.py`), since Claude
  is now called from more than just document extraction. Full test
  suite re-run immediately after to confirm the refactor broke nothing
  (it didn't — same 137 tests passed before touching anything new).
- `asos/core/context.py`: `build_context_snapshot()` — the local,
  Claude-free half of architectural principle 1. Assembles today's
  schedule, open tasks, upcoming assessments (with preparedness where
  concepts are linked), unresolved fact conflicts, and pending
  notifications into one structured snapshot. Explicitly read-only —
  verified it never marks a notification delivered even when called
  repeatedly, unlike the notification-delivery consumption functions.
  `format_context_for_prompt()` renders it to plain text for a prompt.
- `asos/core/assistant.py`: `answer_query()` / `generate_daily_briefing()`
  — the only two places in the codebase that call Claude for open-ended
  synthesis rather than structured extraction. Both prompts explicitly
  instruct Claude to answer only from the supplied context and say so
  plainly rather than guess when something isn't there — the direct
  guardrail against acceptance criterion 16 (a briefing must never
  contain hallucinated content). Tested against a fake Claude client:
  confirmed real DB content (not fabricated placeholder text) actually
  reaches the prompt, and that the grounding instruction is present.
- `asos/memory/episodic.py`: `record_episodic_note()` — the storage
  path for the semantic-memory tier. Deliberately just storage, not an
  automatic "summarize every conversation" pipeline — deciding what's
  worth remembering is a judgment call for a real conversation loop
  (voice-lite) to make, not something to fake here.
- **Verified the full pipeline end-to-end, short of the live network
  call**: set up a real task in a real DB, intercepted the actual
  `requests.post` call `AnthropicClaudeClient` makes, and confirmed the
  real task title and the real user query both appear in the exact
  prompt that would be sent — proving vault → context assembly →
  prompt construction → HTTP call shape → response parsing all work
  correctly together. The one hop still unverified is the live network
  round-trip to Anthropic's servers itself, which needs the user's own
  key per the standing sandbox limitation.
- CLI: `asos ask "<query>"`, `asos brief` — both verified to fail
  cleanly with an actionable message when `anthropic_api_key` isn't
  set, consistent with every other external-service CLI command.
- 153 automated tests passing (was 137 after the task/notification
  milestone).

### Done (previous session — task tracking + notification severity engine milestone)
- `asos/tasks/management.py`: `create_task()` / `update_task_state()`.
  `related_assignment_id` is optional and nothing here ever reads or
  writes `Assignment.canvas_status` — verified directly (acceptance
  criteria 10/11): a task with no Canvas counterpart moves through all
  five states, and marking a Canvas-linked task DONE locally leaves
  the Canvas-sourced `canvas_status` field completely untouched.
  `BLOCKED` requires a reason; leaving `BLOCKED` clears it automatically
  so a stale explanation can't linger.
- `asos/notifications/classification.py`: pure, DB-free severity
  judgment — `classify_assessment_urgency()` /
  `classify_task_urgency()`. Kept separate from persistence (mirrors
  the parsing/chunking vs. ingestion/retrieval split) so the actual
  urgency judgment is testable in complete isolation from the DB.
- `asos/notifications/delivery.py`: the three guardrails from the
  locked design, all directly tested:
  - **Escalation only, never silent downgrade** —
    `upsert_notification_for_target()` raises an existing undelivered
    notification's severity in place, never creates a duplicate for
    the same task/assessment, and a later lower-severity classification
    never downgrades what's already there.
  - **Quiet hours** — `is_quiet_hours()` correctly wraps midnight;
    `get_deliverable_critical_notifications()` withholds CRITICAL
    interrupts entirely during quiet hours.
  - **Daily rate limit** — capped at `DEFAULT_MAX_CRITICAL_PER_DAY=2`;
    verified that a 3rd same-day CRITICAL item is correctly held back.
  - NOTABLE is bundled and only marked delivered when a briefing pulls
    it (`get_notable_notifications_for_briefing`); AMBIENT is never
    auto-delivered at all, only queryable on demand
    (`get_ambient_log`) — both verified.
- `asos/notifications/scan.py`: `scan_for_notifications()` ties
  classification + delivery together against real assessments/tasks
  with due dates — the first piece of actual proactive behavior in the
  system. Verified idempotent (repeated scans under unchanged
  conditions never duplicate).
- **The quiet-hours logic was verified against the sandbox's actual
  wall-clock time, not just synthetic timestamps**: `asos notify
  critical` correctly withheld a real critical notification at
  3:41am (inside default quiet hours), and the identical notification
  was confirmed deliverable when the same query was run with an
  explicit 2pm timestamp — proving the gating logic actually works,
  not just that nothing happened to fire.
- CLI: `asos task create/update/list`, `asos notify scan/critical/
  briefing/ambient`.
- 137 automated tests passing (was 108 after the preparedness
  milestone).

### Done (previous session — mastery scoring + assessment preparedness milestone)
- **Reordered from the original roadmap deliberately**: step 6
  (mastery event logging + derived scoring) was pulled forward ahead of
  its planned position, because step 5 (preparedness) is meaningless
  without a real scoring function — building it against a stub would
  have meant redoing it immediately after. `asos/mastery/events.py` +
  `asos/mastery/scoring.py` are effectively both steps 5 and 6's
  foundational piece, done together, tested first in isolation with
  synthetic event sequences exactly as the original roadmap intended
  for step 6 specifically.
- `asos/mastery/scoring.py`: `compute_concept_mastery()` — recency-
  weighted average of mastery_events, shrunk toward a neutral 0.5
  prior in proportion to how little/stale the evidence is (standard
  Bayesian-average smoothing with a prior pseudo-count). A concept
  with zero events is a distinct NO_EVIDENCE state, never a guessed
  0 or 0.5. Categorized into STRONG/DEVELOPING/WEAK/NO_EVIDENCE.
  **A real behavior was discovered, not assumed, via a failing test**:
  five perfect answers all 60+ days old do NOT register as confidently
  "strong" — they decay toward the neutral prior since nothing recent
  confirms the knowledge is still there. This was initially a wrong
  test expectation on my part, caught immediately by running it, and
  turned into a dedicated regression test once confirmed as correct,
  intentional behavior rather than a bug.
- `asos/mastery/events.py`: `record_mastery_event()` — append-only,
  sensible outcome_score defaults (CORRECT=1.0/INCORRECT=0.0/
  PARTIAL=0.5, SELF_RATED maps a 1-5 rating to 0.0-1.0), explicit
  override always available.
- `asos/assessments/linking.py`: idempotent `link_concept()` /
  `link_document()` — calling twice updates rather than duplicates.
- `asos/assessments/preparedness.py`: `compute_assessment_preparedness()`
  — buckets linked concepts into strong/developing/weak/no-evidence;
  `overall_score` is importance-weighted but excludes no-evidence
  concepts entirely (never fabricates a 0 for "never studied");
  `coverage` separately reports what fraction of the assessment (by
  importance) has been studied at all, specifically so a high score on
  a small studied slice isn't mistaken for full readiness. **Verified
  against the exact worked example from the original design
  conversation** (buffers/titration curves strong, Henderson-
  Hasselbalch weak with 2 recent misses, acid-base edge cases no
  evidence) — both in the test suite and again manually through the
  real CLI end-to-end.
- CLI: `asos study add-concept/record/mastery/link-concept/preparedness`
  — the mastery-and-preparedness smoke test above was run through the
  actual installed `asos` binary against a real SQLite DB, not just
  pytest.
- 108 automated tests passing (was 90 after the document-ingestion
  milestone).

### Done (previous session — document ingestion / embeddings / Claude extraction milestone)
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
- **Browser automation (Canvas assignment descriptions + grades) —
  ACTIVE NEXT MILESTONE**, explicitly authorized by the user's
  institution for this specific approach (see decision log). Plan
  locked: a dedicated, separate browser profile the user logs into
  manually once (never the daily-use profile, never a stored
  password — session-cookie reuse only), scraping assignment
  instructions into `Assignment.description` and
  grades/scores into `Assignment.score`/`.grade`, running on the new
  scheduler. Split into two layers for testability: navigation
  (Playwright-driven, genuinely untestable from this sandbox — no
  browser, no real Canvas login) and parsing (pure functions over raw
  HTML, testable with realistic fixtures same as everything else).
  This will need substantially more real-machine iteration than any
  prior integration, since Canvas's actual page structure can only be
  verified against the user's real account.
- **Real embedding model.** Only the `HashingEmbeddingProvider`
  placeholder exists (see above) — real semantic retrieval quality
  needs a real local model, chosen and latency-tested on the actual
  Windows CPU-only machine, not assumed here.
- **Live Claude API — CONFIRMED WORKING.** The user set a real
  `anthropic_api_key` and ran `asos ask "what should I do right now?"`
  on their real Windows machine: it returned a real, live Claude
  response. It gave generic advice rather than anything schedule-
  specific — correct behavior, not a bug, since no Canvas/ICS data had
  been synced into the DB yet at that point. This closes out the "live
  Claude API" gap that every prior session could only verify against
  fakes.
- **Live Canvas API — BLOCKED, not just unverified.** The user's
  institution disables self-service Canvas API token generation
  entirely (confirmed via a real screenshot: "Your Canvas
  administrators have chosen to limit your ability to generate your
  own access token"). An email to IT requesting one is pending as of
  this writing. `CanvasClient`/`CanvasSyncWorker` remain fully built
  and unit-tested against realistic mocked responses, but live
  verification depends on IT's response, not just on the user running
  a command. **The ICS calendar-feed fallback (this session) exists
  specifically to make progress possible without waiting on that.**
- **Live ICS calendar feed — CONFIRMED WORKING**, but only against a
  synthetic feed. Verified end-to-end by this session (a real local
  HTTP server serving a real ICS file, fetched and synced by the real
  CLI, idempotency confirmed on a second run) — but never yet against
  the user's actual school Canvas ICS feed URL, since obtaining that
  URL is the user's next step.
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
- A true watched-folder worker that automatically ingests dropped
  files with zero command needed at all — `docs ingest`/
  `docs ingest-folder` are both manual CLI commands (the latter at
  least batches, so this is a smaller gap than it was, but genuine
  drop-and-forget automation is still a distinct, larger future
  milestone: it needs duplicate-ingestion avoidance, automatic
  source-type inference, and detecting when a file is done being
  written before reading it).
- Manually confirming assessment-to-concept/document links from
  ingested study guides (the schema and `get_documents_for_assessment`
  helper exist; nothing yet proposes these links automatically — you
  can create them via `asos study link-concept`, but nothing reads a
  study guide and suggests which concepts it covers).
- Periodic/scheduled automatic notification scanning (`asos notify
  scan` is a manual command right now, same status as Canvas sync —
  wiring both into `CoreService`'s own loop on an interval is a
  natural next step).
- Wiring Canvas sync to also generate tasks automatically from new
  assignments (mentioned in the original design as a natural behavior
  — "a Canvas assignment can spawn a task automatically" — but not
  built; tasks are currently created manually or by future callers).
- Wiring `answer_query`/`generate_daily_briefing` into `CoreService`'s
  own loop for proactive, unprompted delivery — they're built and
  callable via CLI now, but nothing calls them automatically yet
  (and per the locked v1 scope, proactive unprompted interrupts are
  deferred to v1.1+ anyway — this is about the pull-based briefing
  becoming schedulable, not about adding push notifications).
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
| Mastery score = recency-weighted average shrunk toward a neutral prior (Bayesian-average smoothing), not a plain weighted average | A plain recency-weighted average, when normalized, is invariant to how old ALL the evidence is (the normalization cancels out a uniform age shift) — so five perfect answers from 60 days ago would look identical to five from yesterday. Adding a constant-weight neutral prior (0.5) means sparse or entirely-stale evidence gets pulled toward "not sure," while abundant recent evidence overwhelms the prior and the score reflects the real track record. This is what makes "we haven't confirmed this recently" show up in the number at all, not just in a separate staleness flag. |
| `overall_score` (preparedness) excludes no-evidence concepts rather than scoring them as 0 | Scoring an unstudied concept as 0% mastered would fabricate a confidence level AsOS doesn't have — "never studied" and "studied and failing" are different facts, and conflating them would actively mislead someone into thinking they're doing worse than they are on material they simply haven't touched yet. `coverage` exists specifically to prevent the opposite failure mode (mistaking a high score on a small studied slice for full readiness). |
| Mastery-scoring milestone (originally step 6) pulled forward ahead of preparedness (step 5) | Preparedness is only as honest as the score it's built on — building it against a stubbed/fake score first would have meant redoing the real logic immediately after anyway. The roadmap's dependency was already implicit ("depends on mastery events, stub with fake data initially"); building the real thing first was less total work than building a stub and then a replacement. |
| Notification classification (judgment) kept in a separate module from delivery (persistence/policy) | Same split as document parsing/chunking vs. ingestion/retrieval: "how urgent is this?" is a pure function of an assessment's preparedness or a task's due date, testable with zero DB access; "what do we do about it" (dedup, escalate, rate-limit, respect quiet hours) is a persistence/policy concern. Mixing them would have made the urgency judgment harder to test in isolation and the delivery guardrails harder to reason about independently. |
| Notifications escalate in place rather than ever creating a second row for the same target | Locked requirement: "something starts Ambient and can escalate to Critical... but should never downgrade silently." Representing escalation as an update to the same row (rather than a new row superseding an old one, as Facts do) was the simpler correct model here — a notification is inherently about current state ("is this still urgent"), not a provenance trail of multiple sources disagreeing, so the Facts append-only pattern doesn't apply the same way. |
| NOTABLE is delivered by a briefing pull, AMBIENT is never auto-delivered at all | Matches the three-tier design exactly: NOTABLE is "bundled — delivered only at next natural touchpoint," so a briefing calling `get_notable_notifications_for_briefing` IS that touchpoint and marking delivered=True then is correct. AMBIENT is "logged only... never pushed," so nothing should ever flip its delivered flag automatically — it stays queryable indefinitely via an explicit ask. |
| Context assembly (`asos.core.context`) is entirely separate from and precedes any Claude call | Direct implementation of architectural principle 1: local code does all retrieval, Claude only synthesizes. Keeping this as its own module with zero Claude dependency means the "what does AsOS currently know" question is testable (and debuggable) without ever touching an API key, and means Claude's context is always something a person could point to in the database — never something Claude reached for on its own. |
| `ClaudeClient` protocol and `AnthropicClaudeClient` moved into a shared `asos/llm/` package rather than staying under `asos/documents/` | Claude is now called from two independent places (syllabus extraction and the core assistant), and a third (voice) is coming. Keeping the shared interface under a feature-specific package would have made the next caller either duplicate the protocol or import from an unrelated feature's namespace. Moved once, at the point a second real caller appeared — not preemptively before there was a second user of it. |
| Every Claude prompt in the core assistant explicitly instructs "never invent... say plainly you don't have that information" | Direct implementation of acceptance criterion 16 ("no hallucinated content"). This is stated as an instruction in the prompt, not enforced in code, because it can't be — verifying it holds in practice requires a real model call this sandbox can't make; the test suite verifies the instruction is present and that real context reaches the prompt, not that Claude obeys it. |
| ICS calendar feed built as a genuine fallback, not a stopgap to delete later | A real institutional constraint (admin-disabled token self-service) is common enough across schools that this is worth keeping permanently, not just unblocking this one user — `CalendarEvent.source` distinguishes canvas/ics_feed/manual precisely so both paths can coexist (e.g. ICS for schedule, manually-entered facts for grades) rather than one being deleted once a token eventually arrives. |
| Browser automation for Canvas: dedicated separate browser profile with one-time manual login, never a stored password | Session-cookie reuse is a meaningfully smaller security surface than automated login (no password storage, no MFA-handling fragility, nothing for AsOS to mishandle). Using a profile separate from the user's daily browser keeps the automation's persistent login state isolated from everything else they browse. This was decided rather than offered as a choice — storing a password for automated use isn't a close call given the project's existing stance that credentials never get typed or stored outside the OS-native vault, and a login form is exactly that. |
| Job scheduler built as a generic interval-runner in `CoreService`, with the "which jobs exist" decision kept in a separate `asos.service.jobs` module | Mirrors every other split in this codebase between mechanism and judgment (parsing vs. chunking, classification vs. delivery): `CoreService` needs zero credential or network awareness to be fully tested, and the actual "given what's configured, what should run" logic lives in exactly one place rather than being smeared across the scheduler's internals. |
| Scheduler jobs fail in isolation and back off by their own interval, not per-tick | A single broken credential (e.g. an expired Canvas token) must not crash the whole background service or spam retries every heartbeat forever — both were directly tested (a failing job doesn't block a working one; a persistently failing job only retries once per interval). This matters more here than anywhere else in the project so far, since this is the first genuinely long-running, unattended code path. |
| Renamed `canvas_event_id`/`canvas_id` to `external_event_id`/`external_id` via true migrations, not left as-is | Once a second calendar source existed, keeping Canvas-specific names on shared columns would have meant either lying in the schema (an ICS UID stored in a column literally named `canvas_event_id`) or duplicating columns per source. Fixed at the point a second real user of the column appeared — not renamed preemptively, not left wrong indefinitely. Both migrations were hand-corrected from Alembic's default drop-and-add autogenerate output specifically to avoid silently discarding any Canvas sync history a user might already have. |

---

*Last updated: foundation milestone (project scaffolding, schema,
migrations, credential vault, core service skeleton, health check).
Update this file's Section 8 and, when applicable, Section 9, at the
end of every future implementation milestone.*
