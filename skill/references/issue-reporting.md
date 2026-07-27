# AI-friendly Issue reporting

Use this workflow only after a user accepts the offer to report a problem.
The AI owns diagnosis collection, drafting, duplicate search, and submission;
do not make the user transcribe logs or fill the repository form.

## Workflow

1. Preserve the failing command, final structured error event, stage, and
   observed impact. Reproduce at most once when it is safe, inexpensive, and
   does not overwrite resources.
2. Run bootstrap status and the narrowest relevant `video-sum doctor`
   invocation. Record the CLI version, OS target, ASR provider/profile, cache
   mode and hit state, frame mode, acceleration probe states, and whether the
   runtime came from a Release or local development fallback.
3. Sanitize before drafting:
   - Replace API keys, cookies, tokens, authorization headers, signed query
     strings, and private endpoints with `<redacted>`.
   - Replace home-directory usernames and private library paths with semantic
     placeholders such as `<home>` and `<library>`.
   - Omit the full transcript, downloaded media, private video frames, and
     credentials. Include only the smallest non-sensitive log excerpt needed.
   - Ask before including an unlisted/private video URL. Prefer a redacted URL,
     platform, and content type when the URL is not essential.
4. Search open and closed Issues in
   `l4place0/bilibili-learning-helper` using the error code and concise symptom.
   If a matching Issue exists, show it and offer to add only genuinely new,
   sanitized evidence. Do not create a duplicate.
5. Draft the body with every heading below. Use `Not observed`, `Unknown`, or
   `Not applicable` rather than inventing missing details.
6. Show the exact title and complete body to the user. Ask for explicit
   approval to submit this draft.
7. After approval, use an available authenticated GitHub connector or:

   ```bash
   gh issue create \
     --repo "l4place0/bilibili-learning-helper" \
     --title "<title>" \
     --body-file "<sanitized-draft.md>"
   ```

   Do not install or authenticate GitHub tooling without separate approval.
   Return the created Issue URL. If submission fails, report the real failure
   and preserve the ready-to-submit draft.

## Body contract

````markdown
### Summary
<One observable problem, without diagnosis presented as fact>

### Affected stage
<bootstrap | install | doctor | download | ASR | frames | compose | library>

### User impact
<What could not be completed or was degraded>

### Steps to reproduce
1. <Minimal deterministic step>
2. <Exact sanitized CLI arguments or user intent>

### Expected behavior
<Expected result>

### Actual behavior
<Actual result and structured error code>

### Sanitized diagnostics
- video-sum version:
- bootstrap target:
- runtime source:
- OS/architecture:
- ASR provider/profile:
- GPU hardware probe:
- Whisper GPU runtime probe:
- frame acceleration probe:
- cache mode/hit:
- frame mode/count:

### Minimal logs
```text
<Smallest sanitized NDJSON/stderr excerpt>
```

### Workaround
<Known workaround, or "None found">

### Additional context
<Public video URL or other non-sensitive context, only when necessary>
````

Use a concise title such as:

```text
[ASR] Metal hardware detected but whisper runtime remains CPU-only
```

Manual fallback URL:

```text
https://github.com/l4place0/bilibili-learning-helper/issues/new/choose
```
