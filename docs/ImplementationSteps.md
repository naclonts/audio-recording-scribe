# Implementation Steps

This document turns [Plan.md](/home/nathan/projects/audio-recording-scribe/docs/Plan.md) into an execution plan for a future parent agent that will coordinate subagents working in separate git worktrees.

## Implementation Goal

Build the project in layers so that:

1. the MVP works without diarization, local LLMs, UI, or auto-update
2. the deployment target remains the Debian-hosted VM + Docker topology described in the plan
3. subagents can work mostly on disjoint file sets
4. merges into `main` happen in a predictable order with minimal conflict risk

## Delivery Priorities

Prioritize work in this order:

1. local batch pipeline
2. automated ingestion and resumable orchestration
3. VM/Docker deployment shell
4. private Git output publishing
5. diarization and speaker inference
6. safe source auto-update
7. optional UI and LLM adjudication

The first usable version should satisfy the MVP acceptance criteria from `docs/Plan.md`:

1. discover new files
2. normalize audio
3. transcribe audio
4. remove obvious GPS/system speech with heuristics
5. write cleaned outputs and metadata
6. prevent duplicate processing
7. survive failures without stopping the whole service

## Recommended Initial Repository Shape

Create this baseline structure before parallel work begins:

```text
.
  pyproject.toml
  README.md
  .env.example
  config/
    settings.yaml
    gps_patterns.yaml
    prompts/
  src/
    audio_recording_scribe/
      __init__.py
      cli.py
      config.py
      logging.py
      paths.py
      pipeline/
      state/
      audio/
      transcription/
      classification/
      output/
      ingestion/
      deployment/
  tests/
    fixtures/
    unit/
    integration/
```

Use `audio_recording_scribe` as the Python package name unless the parent agent finds a stronger reason to pick another name early.

## Parent Agent Rules

The parent agent should keep ownership of shared, high-conflict files:

* `pyproject.toml`
* `README.md`
* `.env.example`
* `config/settings.yaml`
* package entrypoints such as `src/audio_recording_scribe/cli.py`
* top-level integration tests that span multiple subsystems

The parent agent should do these tasks itself before spawning workers:

1. scaffold the repo layout
2. choose the packaging and CLI approach
3. set naming conventions for jobs, artifacts, and status values
4. create base config models and logging conventions
5. land any shared test helpers used across tracks

This reduces churn across worktrees and keeps later merges shallow.

## Merge Strategy

Use merge waves rather than opening every lane at once.

### Wave 0: Bootstrap

One agent, or the parent agent directly, should land:

* project skeleton
* dependency manifest
* basic CLI entrypoint
* config loading
* logging setup
* path helpers
* empty package modules
* test harness and fixture layout

This is the main prerequisite for clean parallel work.

### Wave 1: MVP Core

After Wave 0 lands, parallelize these tracks:

1. state + ingestion orchestration
2. audio normalization + transcription + heuristic filtering + output writing
3. deployment shell and local run tooling

Merge order inside Wave 1 should be:

1. deployment shell if it only touches container and ops files
2. state + ingestion orchestration
3. processing core
4. parent-agent integration pass to wire the CLI and end-to-end tests

### Wave 2: Publishing and Observability

After the MVP core is stable:

1. Git output publishing
2. richer metadata and job inspection helpers
3. retry and failure recovery polish

### Wave 3: Accuracy Enhancements

After the MVP is proven on fixtures:

1. diarization runner
2. transcript-speaker alignment
3. speaker-level GPS inference

### Wave 4: Operations Enhancements

After diarization is stable:

1. updater service/timer
2. idle-aware deployment logic
3. health checks and rollback support

### Wave 5: Optional Features

Only after the above:

1. local LLM adjudication
2. Streamlit UI
3. review tooling for uncertain segments

## Recommended Subagent Workstreams

The future parent agent should spawn workers with explicit file ownership. The slices below are designed to minimize overlap.

| Track | Scope | Primary file ownership |
|---|---|---|
| A | State store and job lifecycle | `src/audio_recording_scribe/state/**`, `tests/unit/test_state*`, `tests/integration/test_job_lifecycle*` |
| B | Ingestion and orchestration | `src/audio_recording_scribe/ingestion/**`, `src/audio_recording_scribe/pipeline/**`, `tests/unit/test_ingestion*`, `tests/integration/test_scan_retry*` |
| C | Audio normalization and transcription | `src/audio_recording_scribe/audio/**`, `src/audio_recording_scribe/transcription/**`, `tests/unit/test_audio*`, `tests/integration/test_transcription*` |
| D | Heuristic classification and transcript assembly | `src/audio_recording_scribe/classification/heuristics.py`, `src/audio_recording_scribe/classification/assembly.py`, `tests/unit/test_heuristics*`, `tests/integration/test_clean_output*` |
| E | Output writing and Git publishing | `src/audio_recording_scribe/output/**`, `tests/unit/test_output*`, `tests/integration/test_git_publish*` |
| F | Deployment shell | `Dockerfile*`, `docker-compose*.yml`, `deploy/**`, `ops/**`, deployment docs |
| G | Diarization and speaker inference | `src/audio_recording_scribe/diarization/**`, `src/audio_recording_scribe/alignment/**`, `src/audio_recording_scribe/classification/speaker_inference.py`, related tests |
| H | Updater and rollback logic | `src/audio_recording_scribe/deployment/**`, `scripts/update*`, `systemd/**`, updater tests |
| I | LLM adjudication and UI | `src/audio_recording_scribe/classification/llm_classifier.py`, `src/audio_recording_scribe/ui/**`, related tests |

If the parent agent wants fewer workers, combine tracks `A+B`, `C+D`, and `F+H`. Do not combine `E` with `H` unless coordination cost is acceptable, because both can touch deployment-facing configuration.

## Detailed Step Plan

### Step 1: Bootstrap the project

Deliverables:

* Python project metadata
* pinned runtime dependencies and optional extras for diarization, UI, and LLM support
* package skeleton
* typed config loader
* central logging setup
* CLI skeleton with placeholder commands for `scan-once`, `watch`, `process`, and `retry`

Exit criteria:

* package imports cleanly
* CLI help renders
* unit-test harness runs

### Step 2: Implement state and idempotency

Deliverables:

* SQLite schema for `jobs`, `artifacts`, and `segments`
* status transition helpers
* job registration by file hash
* duplicate detection rules
* artifact recording helpers

Exit criteria:

* duplicate files do not create duplicate jobs
* interrupted jobs can be resumed or retried cleanly
* state transition tests pass

### Step 3: Implement ingestion safeguards

Deliverables:

* inbox scanner
* stable-file detection based on size and mtime
* supported file-type filtering
* move or copy into a controlled processing area if needed

Exit criteria:

* partial files are ignored until stable
* unsupported or corrupt files fail cleanly
* scanner can run once and in a loop

### Step 4: Implement normalization and transcription

Deliverables:

* ffmpeg-based normalization to mono 16 kHz PCM WAV
* duration and probe checks
* `faster-whisper` transcription wrapper
* timestamped transcript artifact output

Exit criteria:

* sample audio processes end-to-end through transcription
* missing ffmpeg is reported clearly
* transcript segments are persisted in metadata/state

### Step 5: Implement heuristic GPS filtering and clean transcript assembly

Deliverables:

* configurable GPS phrase patterns from `config/gps_patterns.yaml`
* heuristic labels `gps_high_confidence`, `not_gps`, and `uncertain`
* conservative keep/remove decision logic
* clean text and markdown assembly
* JSON provenance output

Exit criteria:

* obvious navigation prompts are removed in fixture tests
* diary text is preserved in conservative cases
* output files are written deterministically

### Step 6: Wire the MVP pipeline

Deliverables:

* job orchestrator that moves work through the planned statuses
* per-job logging
* failure recording and retry support
* batch command for a single file and inbox scan

Exit criteria:

* one command can process a fixture file from discovery to output
* failures do not stop later jobs
* metadata and artifacts are inspectable after completion

### Step 7: Add deployment shell

Deliverables:

* Dockerfile for the processor image
* Compose file for processor and optional services
* environment wiring for data, config, and output-repo mounts
* base deployment documentation for the VM layout

Exit criteria:

* the processor container starts successfully in a local dev environment
* paths and permissions are explicit
* no deployment step assumes broad host mounts

### Step 8: Add Git output publishing

Deliverables:

* output repo staging logic
* deterministic commit messages
* push retry or pending-publication state
* local metadata recording of publish results

Exit criteria:

* successful jobs can publish without duplicating commits
* publish failure does not invalidate job completion
* tests cover idempotency and retry state

### Step 9: Add diarization, alignment, and speaker inference

Deliverables:

* pyannote wrapper behind a feature flag
* transcript-to-speaker alignment
* speaker-level GPS scoring
* fallback path when diarization is unavailable

Exit criteria:

* diarization remains optional
* alignment outputs can be inspected in metadata
* speaker inference can remove GPS/system segments without harming the MVP fallback path

### Step 10: Add safe source auto-update

Deliverables:

* updater service or timer
* deployed-commit tracking
* idle detection
* health checks
* rollback behavior

Exit criteria:

* updates are deferred during active jobs
* failed deployments return to last-known-good state
* deployment logs show target commit, result, and rollback when applicable

### Step 11: Add optional LLM adjudication and UI

Deliverables:

* local LLM client behind config flags
* JSON-only classification prompt
* Streamlit inspection UI
* uncertain-segment review affordances

Exit criteria:

* system still works with LLM and UI disabled
* ambiguous-segment classification is isolated from the main deterministic pipeline
* UI binds locally only

## Cross-Cutting Technical Decisions To Preserve

The parent agent should enforce these decisions during reviews and merges:

* `faster-whisper` is the default ASR path
* diarization is optional, not a hard requirement
* heuristic filtering runs before any LLM call
* intermediate artifacts are always retained
* SQLite is the source of truth for job state
* output content repo stays separate from the source repo
* deleting diary content incorrectly is treated as a more severe error than leaving stray GPS text behind

## Testing Plan By Phase

### MVP test minimum

Add these tests before claiming the MVP:

* state transition tests
* duplicate detection tests
* stable-file detection tests
* heuristic GPS matcher tests
* transcript assembly tests
* one integration test from input audio fixture to cleaned transcript artifact

### Post-MVP test additions

Add these with later waves:

* diarization fallback tests
* speaker-inference scoring tests
* Git publishing idempotency tests
* updater idle-check and rollback tests
* optional LLM unavailable-path tests

## Suggested Parent-Agent Sequence

Use this exact sequence unless repository reality forces a change:

1. land Wave 0 bootstrap directly
2. spawn Track A and Track C+D in parallel
3. spawn Track F in parallel if it only touches deployment files
4. merge A first if B depends on finalized state helpers
5. merge C+D next and perform an integration pass
6. add Track B if orchestration still needs separate cleanup after core processing lands
7. add Track E after output paths and job completion semantics stabilize
8. add Track G only after the MVP fixtures and metadata format are stable
9. add Track H after deployment conventions are fixed
10. add Track I last

## Handoff Checklist For The Future Parent Agent

Before spawning subagents:

* confirm the repo is still near-empty and the file ownership plan still makes sense
* create the shared scaffold first
* assign disjoint write scopes explicitly
* tell each worker not to revert unrelated changes from other workers
* require each worker to list changed files in its final message

Before merging a worker branch:

* review for conflicts with shared config or CLI files
* run the narrowest relevant tests first
* keep the pipeline runnable after each merge, even if later phases are incomplete

Before declaring success:

* verify MVP acceptance criteria locally
* verify deployment assumptions are reflected in config and docs
* leave the repo in a state where later optional phases can be added without reshaping the package
