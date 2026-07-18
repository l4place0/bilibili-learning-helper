## ADDED Requirements

### Requirement: Three-stage structured output

The system SHALL generate three distinct learning materials from a single LLM call when processing a video: preview, index, and summary. The output SHALL be structured JSON with fields `preview`, `index`, and `summary`.

#### Scenario: Successful three-stage generation
- **WHEN** a video URL is submitted and the pipeline completes transcription and classification
- **THEN** the system calls the LLM once with a prompt requesting structured JSON output
- **AND** the response contains `preview` (overview, questions, pre_quiz), `index` (timestamped knowledge points), and `summary` (full summary, cards, post_quiz, weak_points)

#### Scenario: LLM returns malformed JSON
- **WHEN** the LLM response cannot be parsed as valid JSON
- **THEN** the system attempts regex-based extraction of the three sections from the raw text
- **AND** if extraction fails, falls back to treating the entire response as the summary text with empty preview and index

### Requirement: Preview stage with guided questions

The preview SHALL contain a brief overview (2-3 sentences), a list of core questions (3-5 items), and a pre-watch quiz (3-5 multiple-choice questions). The overview MUST NOT reveal core answers or conclusions from the video.

#### Scenario: Preview content is spoiler-free
- **WHEN** the preview is generated for a tutorial video
- **THEN** the overview describes the topic and scope
- **AND** the core questions frame what the viewer should watch for
- **AND** no direct answers or solutions are included in the preview

#### Scenario: Pre-watch quiz generation
- **WHEN** the preview is generated
- **THEN** the pre_quiz contains 3-5 multiple-choice questions
- **AND** each question has 4 options, a correct answer, and a brief explanation
- **AND** questions test prerequisite knowledge or set up curiosity, not video content recall

### Requirement: Index with timestamped knowledge points

The index SHALL contain a list of knowledge points, each with a time in seconds, a display label, and a one-sentence detail. The system SHALL support building external links to the original video at the corresponding timestamp.

#### Scenario: Index entries have valid timestamps
- **WHEN** the index is generated from a video with duration 1200 seconds
- **THEN** each index entry's `time_seconds` is between 0 and 1200
- **AND** each entry has a human-readable `time_display` (MM:SS format)
- **AND** entries are ordered by ascending time

#### Scenario: External link construction for YouTube
- **WHEN** the source platform is YouTube with video_id "abc123"
- **THEN** clicking an index entry with time_seconds=225 opens `https://youtube.com/watch?v=abc123&t=225`

#### Scenario: External link construction for Bilibili
- **WHEN** the source platform is Bilibili with bvid "BV1xx411c7mD"
- **THEN** clicking an index entry with time_seconds=225 opens `https://bilibili.com/video/BV1xx411c7mD?t=225`

#### Scenario: Index entry count is reasonable
- **WHEN** the index is generated
- **THEN** the number of entries is between 5 and 25
- **AND** entries are spaced roughly evenly across the video duration (no large gaps > 30% of total duration)

### Requirement: Summary stage with review materials

The summary SHALL contain a full text summary (Markdown), knowledge cards (Q&A pairs with difficulty and bloom level), a post-watch quiz (3-5 multiple-choice questions), and a list of weak points.

#### Scenario: Summary includes complete learning materials
- **WHEN** the summary is generated
- **THEN** `text` is a Markdown-formatted full summary of the video content
- **AND** `cards` contains 3-8 Q&A pairs, each with question, answer, difficulty (1-5), and bloom_level
- **AND** `post_quiz` contains 3-5 multiple-choice questions testing video content recall
- **AND** `weak_points` lists 1-3 topics that warrant further study

#### Scenario: Post-watch quiz differs from pre-watch quiz
- **WHEN** both pre_quiz and post_quiz are generated
- **THEN** post_quiz questions test content recall and understanding from the video
- **AND** pre_quiz questions test prerequisite knowledge or curiosity
- **AND** no question appears in both pre_quiz and post_quiz

### Requirement: Three-tab Review Doc UI

The Review Doc SHALL present learning materials in three tabs: Preview (预习), Index (索引), and Summary (总结). Each tab displays its corresponding section from the structured output.

#### Scenario: Tab switching
- **WHEN** the Review Doc loads
- **THEN** the Preview tab is active by default
- **AND** clicking any tab switches the visible content
- **AND** the active tab is visually highlighted

#### Scenario: Index tab shows clickable timestamps
- **WHEN** the Index tab is displayed
- **THEN** each knowledge point is shown with its time_display, label, and detail
- **AND** clicking a knowledge point opens the external video URL at the corresponding timestamp in a new tab
- **AND** the link target is determined by the source platform (YouTube/Bilibili)

#### Scenario: Summary tab contains cards and quiz
- **WHEN** the Summary tab is displayed
- **THEN** the full summary text is rendered as Markdown
- **AND** knowledge cards are displayed with flip interaction (question on front, answer on back)
- **AND** post-watch quiz questions are displayed with option selection
- **AND** weak points are highlighted as a distinct section

#### Scenario: Backward compatibility with old tasks
- **WHEN** a Review Doc is generated for a task that has no preview/index data (old format)
- **THEN** only the Summary tab is shown
- **AND** the Preview and Index tabs are hidden or disabled

### Requirement: Platform-aware URL matching for external links

The system SHALL determine the source platform from the task metadata and construct the correct external link format for timestamp navigation.

#### Scenario: YouTube URL construction
- **WHEN** the task platform is "youtube" and video_id is "dQw4w9WgXcQ"
- **THEN** the external link base is `https://youtube.com/watch?v=dQw4w9WgXcQ`

#### Scenario: Bilibili URL construction
- **WHEN** the task platform is "bilibili" and video_id is "BV1GJ411x7h7"
- **THEN** the external link base is `https://bilibili.com/video/BV1GJ411x7h7`

#### Scenario: Unknown platform fallback
- **WHEN** the task platform is not youtube or bilibili
- **THEN** index entries are displayed without external links
- **AND** the time_display is still shown as text

## MODIFIED Requirements

### Requirement: Pipeline summary stage produces structured output

The pipeline summarize stage SHALL be replaced with a three-stage generation stage that produces the combined preview/index/summary JSON. The separate generate_questions stage SHALL be removed as question generation is now embedded in the three-stage output.

#### Scenario: Pipeline execution flow
- **WHEN** a video task is processed
- **THEN** the pipeline executes: download → transcribe → classify → generate_three_stage
- **AND** the generate_three_stage stage produces preview, index, and summary in one LLM call
- **AND** no separate generate_questions stage is executed

#### Scenario: Streaming support for summary text
- **WHEN** the generate_three_stage stage runs in text-only mode
- **THEN** the summary.text portion is streamed to the client via SSE
- **AND** preview and index are included in the final stored result (not streamed separately)
