# Audio Diary Cleanup Pipeline Spec

## Current Repository Status

As of 2026-04-14, the repository implements the MVP without diarization, speaker inference, Git publishing, deployment shell, updater logic, or UI/LLM features.

Implemented now:

* polling inbox ingestion with stable-file detection
* SQLite state for jobs and artifacts
* ffmpeg normalization to mono 16 kHz PCM WAV
* `faster-whisper` transcription wrapper
* heuristic GPS filtering
* deterministic text, markdown, and JSON provenance outputs
* CLI commands for `scan-once`, `watch`, `process`, and `retry`

Deferred from this spec:

* diarization and alignment
* speaker-based GPS inference
* optional local LLM adjudication
* Git publishing
* deployment and updater concerns

## Goal

Build a laptop-hosted code project that automatically ingests voice recordings from a synced folder, transcribes them, removes GPS/navigation speech from the transcript, and writes clean diary text outputs to a local output directory and optional private Git repository.

The system should require near-zero manual intervention after setup.

---

## Primary Use Case

The user records spoken audio diaries while driving.

Those recordings may contain:

* the user’s spoken voice
* GPS/navigation voice prompts from the phone or car system
* occasional background noise
* possible pauses, filler, or non-speech audio

The desired output is a cleaned text transcript containing the user’s diary content while excluding navigation/GPS speech.

---

## Non-Goals

* Real-time live transcription during recording
* Cloud-hosted processing as the primary path
* Multi-user support
* Production-scale distributed architecture
* Perfect speaker identification in all acoustic environments
* General-purpose audio editing UI

---

## High-Level Approach

### Ingestion

Phone recordings are automatically synced into a designated folder on the laptop, likely via Google Drive / Dropbox / Syncthing / iCloud equivalent.

### Processing pipeline

For each new audio file:

1. Detect and register the file in a job queue/state store.
2. Normalize audio into a consistent format.
3. Run speaker diarization on the audio.
4. Run speech-to-text transcription with timestamps.
5. Align transcript segments with diarization segments.
6. Classify segments as either:

   * diary speech
   * GPS/navigation/system voice
   * uncertain
7. Remove GPS/system segments.
8. Merge remaining segments into a cleaned transcript.
9. Save outputs and metadata.
10. Optionally commit/push cleaned text into a private Git repo.

### Preferred classification strategy

Use a layered approach:

1. **Heuristic rules first** for high-confidence GPS text patterns.
2. **Speaker-based filtering** where one diarized speaker is consistently GPS/system voice.
3. **Local LLM cleanup/classification** only for ambiguous segments.

This reduces cost, latency, and complexity while improving reliability.

---

## Recommended Architecture

### Core services/modules

#### 1. Folder watcher / ingestion service

Responsible for discovering new audio files.

Possible implementations:

* Python watchdog-based file watcher
* periodic polling job
* cron job invoking a scanner script every N minutes

Recommendation:

* Start with a polling scanner or watchdog.
* Prefer polling if synced cloud folders create temporary/partial files during sync.

Responsibilities:

* detect newly added files
* ignore partial/incomplete uploads
* register processing jobs
* avoid duplicate processing

#### 2. Audio normalization module

Convert arbitrary phone recording formats into a standard form for downstream models.

Standard target:

* mono WAV
* 16 kHz sample rate
* PCM 16-bit

Tool:

* ffmpeg

Responsibilities:

* transcode source audio
* validate duration
* reject corrupt files
* optionally trim long silence

#### 3. Diarization module

Performs speaker diarization on audio.

Preferred options:

* `pyannote.audio`
* optional future alternative: NVIDIA NeMo diarization

Responsibilities:

* identify speaker turns
* produce timestamped speaker segments
* estimate number of speakers
* expose confidence where available

Expected output example:

```json
[
  {"start": 0.0, "end": 12.4, "speaker": "SPEAKER_00"},
  {"start": 12.4, "end": 15.1, "speaker": "SPEAKER_01"}
]
```

#### 4. Transcription module

Performs ASR on the audio.

Preferred options:

* `faster-whisper` for local performance
* fallback: standard Whisper

Model recommendation:

* default: `small` or `medium` depending on laptop hardware
* configurable model size

Responsibilities:

* produce timestamped transcript segments
* expose confidence/logprob if available
* optionally enable VAD filtering

Expected output example:

```json
[
  {"start": 0.2, "end": 5.7, "text": "I’ve been thinking about work today"},
  {"start": 5.8, "end": 7.0, "text": "Turn right in 500 feet"}
]
```

#### 5. Alignment module

Maps transcription segments to diarization speakers.

Responsibilities:

* assign each transcript segment to the most overlapping diarized speaker
* support partial overlaps
* create unified segment records

Expected output example:

```json
[
  {
    "start": 0.2,
    "end": 5.7,
    "speaker": "SPEAKER_00",
    "text": "I’ve been thinking about work today"
  },
  {
    "start": 5.8,
    "end": 7.0,
    "speaker": "SPEAKER_01",
    "text": "Turn right in 500 feet"
  }
]
```

#### 6. GPS/system speech classifier

Determines which segments should be removed.

This should be a three-stage classifier.

##### Stage A: Heuristic classifier

High-precision rules to catch obvious GPS prompts.

Example patterns:

* “turn left”
* “turn right”
* “in 500 feet”
* “continue straight”
* “your destination is on the …”
* “take the exit”
* “merge onto”
* “keep left” / “keep right”
* “head north/south/east/west”
* “re-routing” / “rerouting” / “route recalculated”
* “you have arrived”

Heuristics can also include:

* short command-like utterances
* text with strong navigation keyword density
* repeated phrase templates

Output labels:

* `gps_high_confidence`
* `not_gps`
* `uncertain`

##### Stage B: Speaker-pattern classifier

Use diarization history within a file to infer whether one speaker is likely the GPS/system voice.

Signals:

* one speaker has short, command-like utterances only
* one speaker appears intermittently and never in long narrative form
* lexical pattern of that speaker matches navigation prompts
* one speaker has synthetic/consistent timing patterns

This stage should operate at the file level.

Example inference:

* If `SPEAKER_01` has 8 segments, all short, all matching nav-like phrases, mark `SPEAKER_01` as likely GPS.
* Then remove all `SPEAKER_01` segments unless confidence drops below threshold.

Output labels:

* `gps_speaker_likely`
* `human_speaker_likely`
* `uncertain`

##### Stage C: Local LLM adjudication

Only ambiguous segments should be sent to a small local LLM.

Purpose:

* classify whether a segment is diary content or navigation/system audio
* optionally use neighboring segments as context

Suggested prompt behavior:

* input: segment text + previous/next segments + speaker metadata
* output JSON only
* labels: `diary`, `gps`, `uncertain`

Candidate local models:

* lightweight instruct model runnable via Ollama or llama.cpp
* examples: 3B–8B instruct models depending on laptop resources

Important:

* The LLM should classify, not rewrite.
* Rewriting should be a separate optional cleanup step.

#### 7. Transcript assembler

Builds final clean transcript.

Responsibilities:

* remove rejected segments
* preserve ordering
* join adjacent diary segments
* format paragraphs
* optionally add timestamps/headings

Output products:

* cleaned plain text
* optional markdown
* optional JSON with provenance

#### 8. Output/publishing module

Writes outputs to disk and optional Git repo.

Responsibilities:

* save transcript
* save machine-readable metadata
* save logs/status
* optional git add/commit/push

---

## Directory Layout

Suggested project structure:

```text
project/
  README.md
  pyproject.toml
  .env.example
  config/
    settings.yaml
    gps_patterns.yaml
    prompts/
      gps_classifier.txt
  data/
    inbox/
    processing/
    archive/
    failed/
    normalized/
    outputs/
    metadata/
    logs/
  src/
    main.py
    scanner.py
    pipeline.py
    audio/
      normalize.py
      probe.py
    diarization/
      pyannote_runner.py
    transcription/
      whisper_runner.py
    alignment/
      align.py
    classification/
      heuristics.py
      speaker_inference.py
      llm_classifier.py
    output/
      writer.py
      git_publish.py
    state/
      db.py
      models.py
    ui/
      streamlit_app.py
  tests/
    test_alignment.py
    test_heuristics.py
    test_end_to_end.py
```

---

## Data Flow

### Input

* source audio files placed into `data/inbox/` or synced there automatically

### Processing states

A file should move through these states:

1. `discovered`
2. `ready`
3. `normalizing`
4. `normalized`
5. `diarizing`
6. `transcribing`
7. `aligning`
8. `classifying`
9. `assembling`
10. `writing_output`
11. `completed`
12. `failed`

State should be stored in a lightweight local DB, preferably SQLite.

---

## State Management

Use SQLite for job state and idempotency.

Suggested tables:

### `jobs`

* `id`
* `source_path`
* `file_hash`
* `status`
* `created_at`
* `updated_at`
* `error_message`

### `artifacts`

* `job_id`
* `artifact_type` (`normalized_audio`, `diarization_json`, `transcript_json`, `clean_text`, etc.)
* `path`
* `created_at`

### `segments`

* `job_id`
* `segment_index`
* `start_sec`
* `end_sec`
* `speaker_label`
* `raw_text`
* `heuristic_label`
* `speaker_label_inference`
* `llm_label`
* `final_label`
* `confidence`

This allows later debugging and model improvement.

---

## Functional Requirements

### FR1. Automatic ingestion

The system shall detect new audio files placed in the configured inbox directory.

### FR2. Duplicate prevention

The system shall avoid reprocessing the same file based on content hash and/or persistent job state.

### FR3. Partial file protection

The system shall not begin processing a file until it appears stable in size/modification time.

### FR4. Audio normalization

The system shall normalize supported audio formats to a standard WAV format for downstream processing.

### FR5. Timestamped transcription

The system shall produce transcript segments with timestamps.

### FR6. Speaker diarization

The system shall produce timestamped speaker segments from audio.

### FR7. Segment alignment

The system shall assign transcript segments to the most likely speaker label.

### FR8. GPS filtering

The system shall identify and remove GPS/system voice segments using heuristics, speaker-pattern inference, and optional LLM adjudication.

### FR9. Clean transcript output

The system shall produce a cleaned transcript file in plain text and optionally markdown/JSON.

### FR10. Metadata retention

The system shall retain intermediate metadata for debugging and auditing.

### FR11. Failure handling

The system shall mark failed jobs and preserve logs without crashing the entire pipeline.

### FR12. Optional Git publishing

The system may commit and push cleaned transcripts to a configured private Git repository.

### FR13. Optional UI

The system may expose a simple local web UI for job status and manual re-run.

---

## Non-Functional Requirements

### NFR1. Laptop-first

The full pipeline should run locally on a developer laptop.

### NFR2. Resumable

If interrupted, processing should be resumable without corrupting the state store.

### NFR3. Configurable

Model choices, folders, thresholds, and publishing behavior should be configurable via YAML/env.

### NFR4. Observable

The system should log per-job timing, model decisions, and failures.

### NFR5. Privacy-preserving

No cloud dependency should be required for the main path.

### NFR6. Reasonable performance

A typical phone recording should process in a practical amount of time for offline batch usage.

---

## Configuration

Use a YAML config plus `.env` for secrets/paths.

Example `settings.yaml`:

```yaml
paths:
  inbox_dir: data/inbox
  processing_dir: data/processing
  archive_dir: data/archive
  failed_dir: data/failed
  outputs_dir: data/outputs
  metadata_dir: data/metadata

scanner:
  mode: polling
  poll_interval_seconds: 60
  stable_file_age_seconds: 120

transcription:
  engine: faster_whisper
  model_size: small
  device: auto
  compute_type: auto
  vad_filter: true

diarization:
  engine: pyannote

classification:
  use_llm_for_ambiguous: true
  llm_backend: ollama
  llm_model: small-instruct-model
  heuristic_confidence_threshold: 0.9
  speaker_gps_threshold: 0.8

output:
  write_txt: true
  write_md: true
  write_json: true
  include_timestamps: false
  git_publish_enabled: false
```

Example `.env`:

```env
PYANNOTE_AUTH_TOKEN=
OLLAMA_HOST=http://localhost:11434
GIT_REMOTE=git@github.com:USER/private-diary.git
```

---

## GPS Filtering Logic

### Core principle

Prefer false negatives over false positives only up to a point.

In practice:

* deleting genuine diary content is worse than leaving a stray GPS line
* therefore the system should be conservative when confidence is low

### Decision rule example

For each segment:

1. If heuristics say `gps_high_confidence`, remove.
2. Else if segment speaker belongs to inferred GPS speaker with high confidence, remove.
3. Else if ambiguous and LLM says `gps`, remove.
4. Else keep.

### File-level speaker inference algorithm

For each speaker in a file, compute features such as:

* number of segments
* mean segment duration
* median token count
* fraction of segments matching GPS heuristics
* ratio of imperative phrases
* vocabulary entropy
* occurrence pattern across timeline

Then calculate a GPS-likelihood score.

Example heuristic score:

```text
score =
  0.45 * fraction_matching_nav_patterns +
  0.20 * short_utterance_ratio +
  0.15 * imperative_ratio +
  0.10 * repeated_phrase_ratio +
  0.10 * intermittent_segment_pattern
```

If score > threshold, mark speaker as probable GPS/system voice.

---

## Web UI Option

Implement a minimal local UI with Streamlit.

### UI goals

* upload or select audio files
* show job statuses
* inspect raw transcript vs cleaned transcript
* view segments removed as GPS
* re-run classification with different settings

### UI should not be required

The CLI/batch path is the primary path.

---

## CLI Commands

Suggested commands:

```bash
python -m src.main scan-once
python -m src.main watch
python -m src.main process path/to/file.m4a
python -m src.main retry JOB_ID
python -m src.main ui
```

Optional with Typer:

```bash
diary-cleaner watch
diary-cleaner process my_audio.m4a
diary-cleaner ui
```

---

## Error Handling

### Common failure cases

* incomplete synced file
* unsupported/corrupt audio
* ffmpeg missing
* diarization model setup failure
* ASR out-of-memory
* LLM backend unavailable
* Git push failure

### Required behavior

* mark job as failed with error message
* preserve the original source file
* write stack trace/logs
* allow retry after config fix
* continue processing other jobs

### Graceful degradation

If local LLM is unavailable:

* continue with heuristics + speaker inference only
* mark output as `llm_skipped`

If diarization fails:

* fall back to transcript-only GPS filtering
* mark reduced-confidence mode in metadata

---

## Testing Requirements

### Unit tests

* text heuristic matcher correctness
* alignment logic correctness
* speaker GPS score calculation
* state transitions

### Integration tests

* normalize -> transcribe -> diarize -> align -> classify pipeline on sample files
* fallback behavior when LLM unavailable
* duplicate detection

### Golden test set

Create a small evaluation corpus of manually reviewed recordings with:

* expected raw transcript
* expected GPS segments removed
* expected cleaned transcript

Metrics:

* GPS segment precision
* GPS segment recall
* diary-content preservation rate

Most important metric:

* low false deletion of user diary content

---

## Acceptance Criteria

### Minimum viable version

An MVP is acceptable when all of the following are true:

1. A new recording dropped into the inbox directory is automatically discovered.
2. The file is normalized and transcribed.
3. GPS/system speech is removed at least via heuristics and optional diarization.
4. A cleaned text file is written to the output directory.
5. Duplicate files are not reprocessed.
6. Failures are logged and do not crash the whole service.

### Strong version

A stronger version is acceptable when:

1. Speaker diarization meaningfully improves GPS removal.
2. Ambiguous segments are adjudicated via a local LLM.
3. A local UI exists for inspection and re-runs.
4. Outputs can be auto-committed into a private Git repo.

---

## Suggested Implementation Order

### Phase 1: Core batch pipeline

* project scaffolding
* config loading
* SQLite state store
* ffmpeg normalization
* faster-whisper transcription
* text-only GPS heuristics
* clean text output

### Phase 2: Automation

* folder polling/watcher
* stable-file detection
* job orchestration
* logging and retries

### Phase 3: Diarization

* pyannote integration
* transcript-speaker alignment
* speaker-level GPS inference

### Phase 4: LLM ambiguity resolver

* local LLM backend integration
* structured classification prompt
* uncertainty thresholds

### Phase 5: UI + publishing

* Streamlit UI
* Git commit/push integration
* settings inspection and job review

---

## Key Implementation Decisions

### Decision 1: Prefer `faster-whisper` over stock Whisper

Reason: faster local inference and simpler laptop usability.

### Decision 2: Use heuristics before LLM

Reason: deterministic, cheaper, and easy to debug.

### Decision 3: Treat diarization as an enhancement, not a hard dependency

Reason: it adds setup complexity and may fail in noisy car recordings.

### Decision 4: Keep intermediate artifacts

Reason: debugging incorrect removals will otherwise be painful.

### Decision 5: Use SQLite rather than only file markers

Reason: makes retries, idempotency, observability, and UI much easier.

---

## Open Questions / Configurable Decisions

These should be resolved during implementation, but the architecture should support either answer.

1. Which sync mechanism will be used from phone to laptop?

   * Google Drive
   * Dropbox
   * Syncthing
   * other

2. What laptop hardware is available?

   * CPU only
   * Apple Silicon
   * NVIDIA GPU

3. Which local LLM runtime is preferred?

   * Ollama
   * llama.cpp
   * none for MVP

4. Should transcripts be stored as:

   * `.txt`
   * `.md`
   * `.json`
   * all three

5. Should the final output preserve timestamps?

6. Should there be a human review mode for uncertain segments?

   * likely optional for later, not required for MVP

---

## Example End-to-End Output Artifacts

For input:

```text
2026-04-13_173245.m4a
```

Produce:

```text
data/outputs/2026-04-13_173245.clean.txt
data/outputs/2026-04-13_173245.clean.md
data/metadata/2026-04-13_173245.transcript.json
data/metadata/2026-04-13_173245.diarization.json
data/metadata/2026-04-13_173245.segments.json
data/logs/2026-04-13_173245.log
```

Example clean text:

```text
April 13, 2026

I’ve been thinking about how I want to structure my week better. Work has felt scattered lately, and I keep noticing that I do better when I choose one concrete thing to finish instead of carrying five things mentally.

I also want to spend more time on the robotics project this week, especially the face tracking control loop.
```

---

## Security / Privacy Notes

* All processing should run locally by default.
* Secrets should be in `.env`, not committed.
* If Git publishing is enabled, repository should be private.
* Consider optional encryption at rest for diary outputs if desired.

---

## Nice-to-Have Future Extensions

* Speaker embedding cache to recognize the user’s own voice over time
* Better system-voice detector trained on navigation prompts
* OCR/extraction of location or time metadata from file names
* Summarization and tagging of diary entries
* Search UI across transcript history
* Mobile shortcut to trigger sync/processing
* Confidence review queue for uncertain segments

---

## Deployment Addendum: Debian Host, VM Isolation, Docker, Private Git Output, Auto-Update

## Deployment Goals

Deploy the project in a VM running on the user’s Debian laptop so that:

* the pipeline is isolated from the host OS
* the service is always on while the laptop is on
* cleaned transcript outputs are committed to a private Git repository
* application code updates are automatically pulled from a source Git repository
* updates occur safely, with health checks and rollback behavior

---

## Recommended Topology

### Host machine

Host OS:

* Debian Linux on laptop

Host responsibilities:

* receive synced audio recordings from phone
* run the VM hypervisor
* expose a narrow inbox path to the VM, or copy files into the VM
* optionally expose an output path for convenience, though final canonical transcript storage is the private Git output repo

### Guest VM

Guest OS recommendation:

* Ubuntu Server LTS or Debian stable minimal install

Guest responsibilities:

* run the audio diary pipeline continuously
* host the application runtime
* host Docker Engine and Docker Compose
* maintain job state, logs, and intermediate artifacts
* publish cleaned transcripts to a private Git output repo
* periodically check for app source repo updates and redeploy safely

### Isolation model

The VM is the trust boundary for the application.

Within the VM:

* run application containers as non-root where possible
* mount only the minimum required directories
* avoid exposing the application UI to the LAN; bind to localhost only or use SSH port forwarding

---

## Recommended Runtime Stack

Inside the VM:

* Docker Engine
* Docker Compose
* systemd

Recommended services:

1. `processor`

   * scans for new audio
   * normalizes, diarizes, transcribes, classifies, writes outputs
2. `ui` (optional)

   * local inspection and debugging interface
3. `ollama` (optional)

   * local LLM service for ambiguous segment classification
4. `updater`

   * checks app source repo for updates
   * rebuilds/restarts safely
5. `git-publisher`

   * can be part of `processor` or a separate helper component for transcript output publishing

Recommended operational model:

* use Docker Compose to manage app services
* use a systemd unit to ensure the Compose stack starts automatically on VM boot

---

## Host-to-VM File Boundary

### Preferred model

Phone recordings sync to a dedicated host folder.

Examples:

* `/home/user/audio-diary-sync/inbox/`
* a narrow folder populated by Google Drive, Syncthing, Dropbox, or equivalent

The VM should access only that narrow folder, not a broad section of the host filesystem.

Recommended approaches:

### Approach A: Narrow shared mount

Expose a dedicated host inbox directory into the VM.

Pros:

* simple
* fewer moving parts

Cons:

* larger coupling between host and guest
* partial/incomplete sync writes must be handled carefully

### Approach B: Host-side copier into VM inbox

A small host-side script copies stable files from the host sync directory into the VM’s internal inbox directory.

Pros:

* better isolation
* VM owns its processing inbox
* easier to reason about file state

Cons:

* one extra moving part

Recommendation:

* prefer Approach B if implementing from scratch
* Approach A is acceptable if the shared path is narrow and the app has strong stable-file detection

---

## Canonical Storage of Cleaned Text

The final cleaned transcripts should be stored in a separate private Git repository.

Keep these repos separate:

* **source repo**: application code and deployment config
* **output repo**: cleaned diary transcript outputs only

Reasons:

* clearer separation of code and private content
* lower risk of mixing diary content into code history
* easier backup and auditing

Suggested output repo layout:

```text
private-diary-output/
  entries/
    2026/
      2026-04-13_173245.clean.md
      2026-04-13_173245.clean.txt
  metadata/
    2026/
      2026-04-13_173245.summary.json
  manifests/
    processed_files.json
```

Recommended canonical transcript format:

* markdown for readability
* optional `.txt` alongside it
* compact JSON metadata for provenance/debugging

---

## Private Git Publishing Design

### Publishing behavior

For each successfully completed job:

1. write cleaned transcript to a staging directory
2. validate that output is non-empty and job status is `completed`
3. copy output into the checked-out output repo working tree
4. `git add` relevant files
5. create a commit with deterministic metadata
6. `git push` to the private remote
7. record pushed commit hash in local job metadata

### Commit message format

Use a deterministic, machine-friendly format.

Example:

```text
Add cleaned diary entry 2026-04-13_173245
```

Optional richer format:

```text
Add cleaned diary entry 2026-04-13_173245

Source file: 2026-04-13_173245.m4a
Job ID: 418
Pipeline version: abc1234
```

### Idempotency rule

Do not create duplicate output commits for the same input file.

Use:

* source file hash
* job ID
* manifest tracking in SQLite and/or repo manifest file

### Failure handling for Git publishing

If `git push` fails:

* mark publishing state as failed or pending
* do not lose the cleaned transcript
* preserve local staged artifacts
* retry publishing later

Publishing failure must not invalidate the processing job itself.

---

## Safe Auto-Update Plan for Source Repo

The application code should auto-update from its source Git repository, but only with guardrails.

### Requirements

The update process must:

* detect whether a newer source commit exists
* avoid interrupting active processing whenever possible
* deploy atomically or near-atomically
* verify application health after update
* roll back if the new version fails health checks

### Recommended update cadence

* check every 5 minutes by default
* configurable via settings

### Required updater behavior

For each update cycle:

1. fetch latest remote refs from the source repo
2. compare deployed commit vs target branch commit
3. if identical, do nothing
4. if new commit exists:

   * check whether a processing job is active
   * if active, defer update until idle, or until a configurable max deferral threshold
   * pull the new code into a deployment working tree
   * build or rebuild the relevant Docker image(s)
   * start the new version
   * run health checks
   * if health checks pass, finalize deployment and record deployed commit
   * if health checks fail, restore the last known-good version

### Idle-first rule

Do not restart the processor in the middle of a job unless the system fully supports clean interruption and resume.

Preferred rule:

* update only when no job is in `normalizing`, `diarizing`, `transcribing`, `aligning`, `classifying`, or `assembling`

Optional fallback:

* if a job runs longer than a configured threshold, allow a deferred maintenance restart after checkpointing

### Health checks

Minimum required health checks after update:

* processor container starts successfully
* app config loads successfully
* database is accessible
* ffmpeg is callable
* Whisper backend is callable
* if enabled, diarization backend loads
* if enabled, LLM backend is reachable

Optional deeper health check:

* run a tiny test transcription on a fixture audio clip

### Rollback strategy

Keep a last-known-good deployment reference.

Possible rollback mechanisms:

* previous Docker image tag
* previous Git commit plus rebuild
* blue/green style container replacement if desired

On failure:

1. stop failed new deployment
2. redeploy prior version
3. run health check on rollback version
4. log the failed target commit

---

## Deployment Layout Inside the VM

Suggested directories inside VM:

```text
/opt/audio-diary/
  deploy/
    docker-compose.yml
    .env
  src/
    current/          # active checked out source repo
    previous/         # optional rollback reference
  data/
    inbox/
    processing/
    archive/
    failed/
    normalized/
    outputs/
    metadata/
    logs/
    state/
  repos/
    diary-output/     # checked-out private output repo
```

### Notes

* `src/current/` is the active source checkout used for deployment
* `repos/diary-output/` is a separate clone for transcript publication
* SQLite DB should live under `/opt/audio-diary/data/state/`

---

## Docker Compose Guidance

Suggested Compose services:

### `processor`

Responsibilities:

* folder scanning
* normalization
* transcription
* diarization
* classification
* output writing
* Git publication or handoff for publication

Mounts:

* app config
* inbox
* state
* logs
* metadata
* output repo checkout

### `ui` (optional)

Responsibilities:

* show job status
* inspect removed segments
* re-run classification

Bind:

* localhost only

### `ollama` (optional)

Responsibilities:

* serve local LLM for ambiguous segment classification

### `updater`

Responsibilities:

* poll source Git repo
* coordinate rebuild/redeploy
* run health checks
* roll back if needed

An alternative is to make `updater` a systemd timer/service instead of a container. That is acceptable and often simpler.

Recommendation:

* updater as a systemd service/timer on the VM host OS is often cleaner than placing redeployment logic inside a container

---

## systemd Boot and Recovery Plan

Use systemd inside the VM to ensure the deployment survives reboot.

Recommended units:

### `audio-diary-compose.service`

Starts Docker Compose stack on boot.

Responsibilities:

* ensure Docker is up
* run `docker compose up -d`
* restart if compose startup fails

### `audio-diary-updater.timer`

Runs the updater on a schedule.

### `audio-diary-updater.service`

Performs one update check and, if needed, a safe redeploy.

### Optional `audio-diary-host-import.timer`

If using a host-to-VM file import mechanism, this can periodically import stable audio files into the VM inbox.

---

## Security Requirements for This Deployment

### Required

* run containers as non-root where feasible
* keep the UI bound to localhost only
* use SSH keys for private Git access
* store secrets in `.env` or Docker secrets, not in the repo
* mount only required paths
* keep code repo and transcript repo separate

### Strongly recommended

* mount host inbox read-only when using a shared mount
* give the VM no access to unrelated host directories
* use branch pinning for source updates, e.g. `main` or `stable`
* disable password SSH auth if the VM is remotely reachable

---

## Config Additions for This Deployment

Example additions to `settings.yaml`:

```yaml
deployment:
  mode: vm_docker
  host_os: debian
  update_branch: main
  update_check_interval_seconds: 300
  update_only_when_idle: true
  max_update_deferral_seconds: 7200
  health_check_timeout_seconds: 120
  rollback_enabled: true

git_output:
  enabled: true
  repo_path: /opt/audio-diary/repos/diary-output
  commit_each_entry: true
  push_after_commit: true
  branch: main

host_import:
  enabled: false
  mode: shared_mount
  shared_inbox_path: /mnt/host-audio-inbox
```

---

## Additional Functional Requirements for Deployment

### FR14. VM boot persistence

The system shall start automatically when the VM boots.

### FR15. Safe source auto-update

The system shall periodically check for source repo updates and redeploy safely.

### FR16. Idle-aware updates

The system shall defer updates while processing active jobs unless explicitly configured otherwise.

### FR17. Output repo publication

The system shall publish cleaned transcript outputs to a separate private Git repo.

### FR18. Rollback capability

The system shall restore the last known-good application version if an update fails health checks.

---

## Additional Acceptance Criteria for Deployment

The deployment is acceptable when all of the following are true:

1. The VM boots and the service stack starts automatically.
2. New audio files arriving in the VM inbox are processed without manual intervention.
3. Cleaned transcript outputs are committed and pushed to the private output Git repo.
4. The updater detects new source commits and deploys them automatically.
5. Updates do not interrupt active jobs unless explicitly allowed by configuration.
6. Failed updates trigger rollback to a working version.
7. Logs clearly show deployed source commit, output publish status, and rollback events.

---

## Updated Recommended Implementation Order

### Phase 1: Core batch pipeline

* project scaffolding
* config loading
* SQLite state store
* ffmpeg normalization
* faster-whisper transcription
* text-only GPS heuristics
* clean text output

### Phase 2: Automation inside VM

* folder polling/watcher
* stable-file detection
* job orchestration
* logging and retries
* Dockerization
* systemd boot integration

### Phase 3: Git output publishing

* separate private output repo clone
* commit/push logic
* publish retry logic

### Phase 4: Diarization

* pyannote integration
* transcript-speaker alignment
* speaker-level GPS inference

### Phase 5: Safe source auto-update

* updater service/timer
* idle detection
* rebuild/redeploy
* health checks
* rollback

### Phase 6: UI + optional LLM

* Streamlit UI
* local LLM backend integration
* ambiguous-segment adjudication

---

## Final Summary

This project should be implemented as a local, VM-isolated, batch-oriented audio-processing system running on the user’s Debian laptop. The VM should host a Docker-based deployment that continuously watches for new synced recordings, normalizes incoming audio, transcribes it, performs speaker diarization when enabled, filters GPS/system speech using layered classification, and writes cleaned diary transcripts.

The cleaned transcript outputs should be committed to a separate private Git repository. The application source code should auto-update from its own source repository using an idle-aware, health-checked deployment flow with rollback to the last known-good version.

The MVP should work without diarization or a local LLM. Those should remain enhancements rather than hard dependencies for baseline functionality.
