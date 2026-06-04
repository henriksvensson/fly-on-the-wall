# Fly on the Wall: Transcription and Speaker Identity Notes

## Goal

Build a system that can take meeting audio and produce readable, named transcripts across recordings.

The desired end result is not just diarization labels like `speaker_0`, but stable person identities such as `Person A`, `Person B`, `Person C`, and `Person D`, even when different transcription providers assign different local speaker labels per recording.

## Overall Architecture

The emerging architecture has four separate stages:

1. Audio transcription and diarization
2. Local speaker identity matching
3. Speaker-label re-merge and name assignment
4. Transcript post-processing

Each stage should preserve its inputs and outputs so we can inspect, compare, and improve the system without losing auditability.

## Stage 1: Transcription and Diarization

The first stage sends audio to a speech-to-text provider and receives:

- transcribed text
- word-level timestamps
- provider-local speaker labels
- raw provider response

The provider-local speaker labels are not stable identities. For example, `speaker_1` in one recording does not mean the same person as `speaker_1` in another recording.

We store provider outputs beside the audio sample, using provider/model names in filenames.

Example layout:

```text
audio-samples/<recording-stem>/transcripts/
  elevenlabs-scribe_v2.txt
  elevenlabs-scribe_v2.raw.json
  speechmatics-batch-auto-sensitivity-0.7.txt
  speechmatics-batch-auto-sensitivity-0.7.raw.json
```

The raw JSON is important because it contains word timestamps and original diarization labels needed for later identity matching and rendering.

## API Evaluation

We tested multiple transcription providers on Swedish meeting audio.

### ElevenLabs

ElevenLabs Scribe v2 became the main baseline because it produced the best overall combination of:

- readable Swedish transcription
- coherent meeting context
- useful diarization
- good speaker continuity in many sections

However, it had an important failure on one meeting: it merged two recurring speakers into one diarization label, `speaker_1`.

That means ElevenLabs was strong on content, but not fully reliable for speaker separation.

### Speechmatics

Speechmatics was the runner-up for diarization.

With default-ish settings, it also merged the same recurring speakers. With higher speaker sensitivity, it over-split the meeting into many labels, but that over-splitting turned out to be useful because it separated some speakers that ElevenLabs had merged.

For the latest recording:

- Speechmatics sensitivity `0.5` still merged the two recurring speakers.
- Speechmatics sensitivity `0.7` over-split heavily, but separated key segments for those speakers.

This makes Speechmatics useful as a second diarization pass, especially when we need to recover from merged speakers.

### Soniox

Soniox produced strong wording on the first sample. It was one of the better providers for transcription quality, but ElevenLabs and Speechmatics were stronger for diarization continuity.

### Deepgram

Deepgram was weaker on Swedish wording in the first tests.

### OpenAI

OpenAI was weaker on this Swedish clip. One diarized model hallucinated English, making it less useful for this use case.

### Gladia

Gladia produced decent diarization but weaker wording compared to the best providers.

### Bee

Bee does not provide useful speaker identification for this workflow. It identified one known speaker in some places, but most other speakers were `Unknown`.

Compared only on transcript content, Bee was significantly weaker than ElevenLabs and Speechmatics for this Swedish meeting. It often produced garbled pseudo-Swedish/English and lost business context.

## Current Provider Ranking

For this use case so far:

1. ElevenLabs: best overall readable transcript and decent diarization
2. Speechmatics: useful diarization runner-up, especially with sensitivity tuning
3. Soniox: strong wording, less useful for speaker continuity
4. Gladia: usable but weaker wording
5. Deepgram/OpenAI/Bee: weaker for this Swedish meeting scenario

## Stage 2: Local Speaker Identity

The speech providers only give per-recording diarization labels. To identify people across recordings, we built a local speaker identity layer.

This uses local voice embeddings from a pyannote-compatible model:

```text
pyannote/wespeaker-voxceleb-resnet34-LM
```

This model worked locally without requiring gated Hugging Face access.

The idea is:

1. Extract representative audio clips for each diarized speaker label.
2. Compare those clips to known voice samples.
3. Score similarity using embeddings.
4. Assign likely person names based on scores and transcript context.

This keeps speaker identity matching local. The speaker-ID comparison does not require uploading voice-sample audio to a third-party API.

## Voice Samples

The proof of concept stored speaker references as directories with one or more clips per person.

Example:

```text
speaker-profiles/
  person-a/
  person-b/
  person-c/
  person-d/
  profiles.json
```

The implemented app models these confirmed references as `voice_sample` records. Each person can and should have multiple voice samples.

This is important because one speaker can sound different depending on:

- microphone
- room acoustics
- call software
- compression
- distance from mic
- background noise
- emotional tone
- meeting context

We concluded that the system should not rely on one canonical speaker embedding per person.

Instead, each person should have a collection of confirmed voice samples.

## Current Known Voice Samples

The proof of concept used several recurring known speakers:

- Person A
- Person B
- Person C
- Person D
- Person E

Some speakers were identified by embedding similarity. Others were confirmed from transcript context or user review.

Examples:

- One speaker was inferred from meeting context and handoff phrasing.
- Another speaker was identified from a self-introduction.
- One recurring speaker was created from a user-confirmed Speechmatics segment.
- Several profiles were strengthened with longer user-confirmed segments.

## Speaker Matching Lessons

### Averaging All Voice Samples Can Be Brittle

The proof-of-concept matching approach averaged all clips for a person before comparing. This can work, but it can also dilute good references.

We saw this with one recurring speaker:

- Before adding a better voice sample, one match was around `0.638`.
- After adding a longer confirmed clip, the same match improved to around `0.767`.
- Using only the new clip in a temporary test, the match improved further to around `0.851`.

This suggests the older references were not wrong, but they diluted the best match.

### Better Future Matching Strategy

Instead of averaging all clips into one embedding, the implemented direction is to compare against multiple references and report:

- best matching reference clip
- top-k average score
- mean score
- number of references
- winning reference filename
- confidence margin versus next-best person

This would let us preserve multiple voice references per person without letting a weak clip drag down the whole profile.

## Stage 3: Re-Merging Speaker Labels

Speechmatics sensitivity `0.7` over-split the latest meeting into many speaker labels, such as `S1`, `S2`, `S3`, etc.

Using speaker-ID profiles, we were able to re-merge many of those labels into real names.

Recommended mapping from the latest Speechmatics `0.7` run included:

```json
{
  "S2": "Person A",
  "S3": "Person B",
  "S4": "Person C",
  "S6": "Person D",
  "S9": "Person C",
  "S11": "Person E",
  "S12": "Person C"
}
```

Some labels were weak or very short fragments and should not be trusted blindly.

For those, we generated two transcript variants:

1. A permissive version with weak best guesses marked using `?`
2. A strict version where weak fragments remain `Unknown`

This remains a useful pattern for future provider-comparison work.

## Named Transcript Rendering

We added rendering that can take:

- raw provider JSON
- speaker-label-to-name mapping
- re-merge map

And produce named transcripts.

Historical proof-of-concept output style:

```text
Person A (S2): ...
Person B (S3): ...
Person D (S6): ...
Person C (S4): ...
Person E (S11): ...
```

The current final export omits language codes and source speaker labels for readability. Source labels remain available in preserved raw and normalized artifacts for auditability.

This is important because if a name assignment is wrong, we can trace it back to the provider's original diarization label.

## Stage 4: Transcript Post-Processing

So far, there is very little post-processing.

Current rendering does:

- speaker name substitution
- basic grouping
- some merging of adjacent same-speaker fragments

It does not yet do serious cleanup such as:

- correcting punctuation
- fixing casing
- smoothing fragmented sentences
- correcting obvious STT errors
- normalizing names and domain terms
- merging broken utterances across short pauses
- using context to improve readability

We tested a sub-agent that tidied the latest named Speechmatics transcript without any of the broader project context.

It successfully:

- merged adjacent same-speaker fragments
- improved punctuation and capitalization
- preserved speaker labels
- avoided making aggressive guesses

Example improvement:

Original:

```text
Person B (S3): Fragmented sentence part one.

Person B (S3): Fragmented sentence part two.

Person B (S3): Fragmented sentence part three.
```

Tidied:

```text
Person B (S3): Fragmented sentence part one. Fragmented sentence part two. Fragmented sentence part three.
```

It improved readability but did not infer that `Hands` might be wrong, which was appropriate given the instruction not to guess.

## Post-Processing Direction

The application separates raw transcription from readable transcript cleanup.

Recommended pipeline:

1. Raw provider output
2. Diarized transcript
3. Named/re-merged transcript
4. Lightly post-processed readable transcript
5. Optionally, heavily edited summary/minutes/action items

The post-processed transcript should preserve links back to source spans where possible.

We should support different cleanup modes:

- Conservative: punctuation, casing, merge obvious fragments
- Balanced: fix obvious terms/names from glossary
- Aggressive: rewrite into clean meeting prose
- Summary mode: produce meeting notes, decisions, action items

## Important Design Principles

### Keep Raw Outputs

Always keep raw provider JSON. It is needed for:

- debugging
- replaying matching
- extracting speaker clips
- comparing providers
- improving renderers
- auditing post-processing changes

### Separate Diarization From Identity

Provider diarization labels are local to one transcript. They should never be treated as stable identities.

Speaker identity should be a separate local layer.

### Use Multiple Providers When Needed

No provider was perfect.

ElevenLabs had better text quality but merged two recurring speakers.

Speechmatics over-split at high sensitivity but gave useful separation.

A robust system may use one provider for the main transcript and another provider as a diarization cross-check.

### Use Human Feedback To Improve Profiles

The system benefits directly from user-confirmed passages.

When the user confirms "this is Person C" or "this is Person A," we can extract that audio span and add or improve voice samples.

This suggests the application should include a feedback workflow:

- user corrects a speaker name
- system extracts the relevant audio
- system adds or proposes a new voice sample
- future matching improves

### Preserve Uncertainty

Some speaker assignments are weak. The system should expose uncertainty rather than hiding it.

Examples:

- `Person B?`
- `Unknown`
- confidence score
- source speaker label
- competing match scores

## Current State

We now have:

- transcription scripts for multiple APIs
- raw transcript storage
- named transcript rendering
- local speaker embedding matching
- voice samples for several known participants
- re-merge logic for over-split diarization
- first experiments with post-processing
- evidence that user-confirmed voice samples improve matching

## Next System Improvements

Recommended next steps:

1. Improve speaker matching to use per-reference scoring instead of simple averaged samples.
2. Add confidence thresholds and confidence margins.
3. Keep improving structured voice-sample handling with multiple references per person.
4. Add a UI or command workflow for confirming/correcting speaker identity.
5. Add glossary/context support for names, companies, and domain terms.
6. Add conservative transcript post-processing as a formal stage.
7. Compare ElevenLabs and Speechmatics outputs automatically for diarization disagreement.
8. Generate final meeting artifacts:
   - readable transcript
   - speaker timeline
   - summary
   - decisions
   - action items

## Conclusion

The most promising architecture is a hybrid system:

- Use a strong STT provider for transcription quality.
- Use one or more diarization outputs for speaker segmentation.
- Use local speaker embeddings for stable identity across recordings.
- Use human-confirmed clips to continuously improve voice samples.
- Use post-processing to turn raw STT output into readable meeting transcripts.

The key insight is that transcription, diarization, speaker identity, and readability are separate problems. Treating them as separate stages makes the system easier to debug, improve, and trust.
