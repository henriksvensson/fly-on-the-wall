# Fly on the Wall: Transcription and Speaker Identity Notes

## Goal

Build a system that can take meeting audio and produce readable, named transcripts across recordings.

The desired end result is not just diarization labels like `speaker_0`, but stable person identities such as `Person C`, `Person A`, `Person D`, `Person E`, and `Person F`, even when different transcription providers assign different local speaker labels per recording.

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

However, it had an important failure on the latest meeting: it merged Person D and Person E into one diarization label, `speaker_1`.

That means ElevenLabs was strong on content, but not fully reliable for speaker separation.

### Speechmatics

Speechmatics was the runner-up for diarization.

With default-ish settings, it also merged Person D and Person E. With higher speaker sensitivity, it over-split the meeting into many labels, but that over-splitting turned out to be useful because it separated some speakers that ElevenLabs had merged.

For the latest recording:

- Speechmatics sensitivity `0.5` still merged Person D/Person E.
- Speechmatics sensitivity `0.7` over-split heavily, but separated key Person D and Person E segments.

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

Bee does not provide useful speaker identification for this workflow. It named Person A in some places, but most other speakers were `Unknown`.

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
2. Compare those clips to known speaker profile clips.
3. Score similarity using embeddings.
4. Assign likely person names based on scores and transcript context.

This keeps speaker identity matching local. The speaker-ID comparison does not require uploading profile audio to a third-party API.

## Speaker Profiles

Speaker profiles are stored as directories with one or more reference clips per person.

Example:

```text
speaker-profiles/
  person_c/
  person_a/
  person_d/
  person_e/
  person_f/
  profiles.json
```

Each person can and should have multiple reference clips.

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

Instead, each person should have a collection of speaker identity references.

## Current Known Speaker Profiles

Current known speakers include:

- Person C
- Person A
- Person D
- Person E
- Person F

Some speakers were identified by embedding similarity. Others were confirmed from transcript context or user review.

Examples:

- Person D was inferred from a handoff where Person C said, "Person D, du kan val fortsatta."
- Person F was identified from a self-introduction: "Person F heter jag."
- Person E was created from a user-confirmed Speechmatics segment.
- Person C's profile was strengthened with a longer user-confirmed segment from the latest meeting.
- Person F's profile was also strengthened with a longer user-confirmed segment.

## Speaker Matching Lessons

### Averaging All Profile Clips Can Be Brittle

The current matching approach averages all profile clips for a person before comparing. This can work, but it can also dilute good references.

We saw this with Person C:

- Before adding a better profile clip, `S2 -> Person C` was around `0.638`.
- After adding a longer confirmed Person C clip, `S2 -> Person C` improved to around `0.767`.
- Using only the new Person C clip in a temporary test, `S2 -> Person C` improved further to around `0.851`.

This suggests the old Person C references were not wrong, but they diluted the best match.

### Better Future Matching Strategy

Instead of averaging all clips into one embedding, the real system should compare against multiple references and report:

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
  "S2": "Person C",
  "S3": "Person A",
  "S4": "Person E",
  "S6": "Person D",
  "S9": "Person E",
  "S11": "Person F",
  "S12": "Person E"
}
```

Some labels were weak or very short fragments and should not be trusted blindly.

For those, we generated two transcript variants:

1. A permissive version with weak best guesses marked using `?`
2. A strict version where weak fragments remain `Unknown`

This is a useful pattern for the real system.

## Named Transcript Rendering

We added rendering that can take:

- raw provider JSON
- speaker-label-to-name mapping
- re-merge map

And produce named transcripts.

Example output style:

```text
Person C [sv] (S2): ...
Person A [sv] (S3): ...
Person D [sv] (S6): ...
Person E [sv] (S4): ...
Person F [sv] (S11): ...
```

The source speaker labels remain in parentheses for auditability.

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
Person A [sv] (S3): Example Company Hands. Liksom Vet

Person A [sv] (S3): nar det hander. Ja,

Person A [sv] (S3): dar har vi Mr. Beeman.
```

Tidied:

```text
Person A [sv] (S3): Example Company Hands. Liksom vet nar det hander. Ja, dar har vi Mr. Beeman.
```

It improved readability but did not infer that `Hands` might be wrong, which was appropriate given the instruction not to guess.

## Post-Processing Direction

The real application should separate raw transcription from readable transcript cleanup.

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

ElevenLabs had better text quality but merged Person D/Person E.

Speechmatics over-split at high sensitivity but gave useful separation.

A robust system may use one provider for the main transcript and another provider as a diarization cross-check.

### Use Human Feedback To Improve Profiles

The system benefits directly from user-confirmed passages.

When the user says "this is Person E" or "this is Person C," we can extract that audio span and improve the speaker profile.

This suggests the application should include a feedback workflow:

- user corrects a speaker name
- system extracts the relevant audio
- system adds or proposes a new profile reference
- future matching improves

### Preserve Uncertainty

Some speaker assignments are weak. The system should expose uncertainty rather than hiding it.

Examples:

- `Person A?`
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
- speaker profiles for several known participants
- re-merge logic for over-split diarization
- first experiments with post-processing
- evidence that user-confirmed profile clips improve matching

## Next System Improvements

Recommended next steps:

1. Improve speaker matching to use per-reference scoring instead of simple averaged profiles.
2. Add confidence thresholds and confidence margins.
3. Build a structured speaker-profile format with multiple references per person.
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
- Use human-confirmed clips to continuously improve speaker profiles.
- Use post-processing to turn raw STT output into readable meeting transcripts.

The key insight is that transcription, diarization, speaker identity, and readability are separate problems. Treating them as separate stages makes the system easier to debug, improve, and trust.
