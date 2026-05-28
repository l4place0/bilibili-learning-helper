## ADDED Requirements

### Requirement: Multi-URL batch submission
The system SHALL accept multiple video URLs in a single submission request, processing each independently and then generating a synthesis.

#### Scenario: Submit 3 URLs together
- **WHEN** a user submits 3 URLs in one request (via API or Web UI multi-line input)
- **THEN** the system creates 3 independent tasks with a shared group_id
- **AND** each task runs the full pipeline (download → transcribe → summarize → question generation)

#### Scenario: Partial failure in batch
- **WHEN** 1 of 3 tasks fails during pipeline execution
- **THEN** the remaining 2 successful tasks are still available individually
- **AND** the synthesis is skipped with a notification about the failed task

### Requirement: Group task association
The system SHALL associate related tasks with a group_id to track multi-source submissions.

#### Scenario: Group ID stored in task metadata
- **WHEN** a multi-URL submission is processed
- **THEN** each task's metadata contains the same group_id
- **AND** a group-level query can retrieve all tasks in the group

#### Scenario: Group status tracking
- **WHEN** a group has tasks in progress
- **THEN** the group status reflects the aggregate (pending / partial / complete / failed)
- **AND** the Web UI shows group progress

### Requirement: Two-stage synthesis pipeline
The system SHALL implement a two-stage pipeline: Stage 1 processes each video independently, Stage 2 generates a synthesis from the combined outputs.

#### Stage 1: Independent Processing
- **WHEN** all tasks in a group reach status "done"
- **THEN** the system automatically triggers Stage 2 (synthesis)

#### Stage 2: Synthesis Generation
- **WHEN** Stage 2 is triggered
- **THEN** the system calls an LLM with: 3 full summaries + top segments from each transcript
- **AND** generates a structured synthesis document

### Requirement: Synthesis uses condensed input
The system SHALL use condensed input for the synthesis LLM call to stay within context limits.

#### Scenario: Token-controlled synthesis input
- **WHEN** preparing the synthesis prompt
- **THEN** the system includes: full summary for each video + top 20% segments per transcript (by position, not density)
- **AND** total input stays under 8000 tokens

#### Scenario: Long transcripts are truncated
- **WHEN** a transcript exceeds 4000 tokens
- **THEN** only the first N segments fitting the token budget are included
- **AND** the summary (which covers the full content) is always included in full

### Requirement: Structured synthesis output
The system SHALL generate a synthesis document with standardized sections.

#### Scenario: Synthesis output structure
- **WHEN** the synthesis LLM call completes
- **THEN** the output contains these sections:
  - **统一理解**: Core knowledge integrating all sources
  - **各视角独特贡献**: What each source uniquely covers
  - **共识与分歧**: Where sources agree, disagree, and complement each other
  - **最佳实践提炼**: Optimal approaches distilled from all sources
  - **综合复习卡片**: Cross-source review questions

### Requirement: Synthesis review cards
The system SHALL generate cross-source review questions that test understanding across multiple videos.

#### Scenario: Cross-source questions in synthesis
- **WHEN** synthesis review cards are generated
- **THEN** questions reference concepts from multiple videos
- **AND** questions include comparison and integration types (not just recall)

### Requirement: Synthesis Review Doc
The system SHALL generate a Review Doc for the synthesis that includes all question types from individual videos plus synthesis-specific questions.

#### Scenario: Synthesis Review Doc content
- **WHEN** a synthesis Review Doc is generated
- **THEN** it contains: synthesis summary, synthesis questions, and links to individual video Review Docs
- **AND** the Cards tab includes all questions from individual videos + synthesis questions

### Requirement: Web UI multi-URL input
The system SHALL support multi-URL input in the Web UI with group progress visualization.

#### Scenario: Multi-line URL input
- **WHEN** a user pastes multiple URLs in the submit textarea
- **THEN** the system detects multiple URLs and offers "Process as group" option
- **AND** selecting "Process as group" creates a multi-source submission

#### Scenario: Group progress display
- **WHEN** a group is processing
- **THEN** the Web UI shows progress for each individual task
- **AND** shows a "Synthesis pending" state until all tasks complete
- **AND** shows a "View synthesis" button when synthesis is ready

### Requirement: API endpoint for multi-source submission
The system SHALL provide a batch API endpoint that accepts multiple URLs and returns a group_id.

#### Scenario: POST /api/summarize/group
- **WHEN** a POST request is made to /api/summarize/group with {"urls": [...], "lang": "zh", "detail": "normal"}
- **THEN** the system creates a group with individual tasks
- **AND** returns {"group_id": "...", "task_ids": [...]}

#### Scenario: GET /api/groups/{group_id}
- **WHEN** a GET request is made to /api/groups/{group_id}
- **THEN** the system returns group status, individual task statuses, and synthesis result if available
