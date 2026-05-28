## ADDED Requirements

### Requirement: Preserve transcript segment structure
The system SHALL retain Whisper output segments with start_time, end_time, and text fields throughout the pipeline. Segments SHALL be stored in task metadata as `transcript_segments` (JSON array).

#### Scenario: Transcription produces structured segments
- **WHEN** a video is transcribed via any ASR provider (inprocess, local, openai)
- **THEN** the pipeline stores both `transcript` (plain text) and `transcript_segments` (list of `{start, end, text}`)

#### Scenario: Cached transcript preserves segments
- **WHEN** a video uses a cached transcript from a previous task
- **THEN** the cached `transcript_segments` are copied to the new task

### Requirement: Format segments for LLM consumption
The system SHALL format transcript segments with sequential IDs and timestamps before passing to LLM prompts.

#### Scenario: Segments formatted with IDs and timestamps
- **WHEN** segments are passed to a summary prompt
- **THEN** each segment is formatted as `[S{n} @MM:SS] text` where n is zero-based index and MM:SS is the start time

#### Scenario: Segment IDs are stable within a task
- **WHEN** the same task's segments are referenced in summary and in review doc
- **THEN** segment IDs match between the two contexts

### Requirement: Summary prompts require source citations
The system SHALL instruct LLM to annotate each factual claim in the summary with segment references in `[Sn]` or `[Sn-Sm]` format.

#### Scenario: Summary includes segment citations
- **WHEN** a summary is generated for any content type
- **THEN** the summary text contains `[Sn]` citations after factual claims
- **AND** citations reference valid segment IDs from the input transcript

#### Scenario: Summary without citations for general statements
- **WHEN** a summary contains general/concluding statements not tied to specific segments
- **THEN** those statements may omit citations (citations are not 100% mandatory)

### Requirement: Review Doc renders citations as clickable links
The system SHALL render `[Sn]` citations in the summary as clickable elements that navigate to the corresponding transcript segment.

#### Scenario: Click citation jumps to transcript segment
- **WHEN** user clicks a `[S12]` citation in the Summary tab
- **THEN** the view switches to the Transcript tab
- **AND** segment S12 is scrolled into view and highlighted for 3 seconds

#### Scenario: Citation shows timestamp tooltip on hover
- **WHEN** user hovers over a `[S12]` citation
- **THEN** a tooltip shows the timestamp range (e.g., "02:15 - 02:32")

### Requirement: Transcript tab displays segments with timestamps
The system SHALL display the transcript in the Review Doc as individual segments with visible timestamps, not as a single text block.

#### Scenario: Transcript shown as timestamped segments
- **WHEN** user opens the Transcript tab in Review Doc
- **THEN** each segment shows its timestamp (MM:SS) and text on a separate line
- **AND** each segment has a stable ID attribute for citation anchoring

#### Scenario: Segment highlights associated frame
- **WHEN** a transcript segment has a nearby keyframe (within 5 seconds)
- **THEN** a small frame thumbnail is shown alongside the segment
