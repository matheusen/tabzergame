---
id: study-generate-theory
name: Study Agent — Generate Theory Exercises
goal: Generate {count} theory/ear-training exercises for topic '{topic_id}' and append to studyExercises.ts
action: theory
default_count: 2
---

# Task: Generate Theory & Ear Training Exercises

Generate theory-focused exercises (type: "visual" or "ear") for the target topic.
These exercises help students visualize harmonic concepts on the fretboard and train their ear.

## How to Run

```bash
python backend/agents/study_agent/run_agent.py \
  --topic <topic_id> \
  --action theory \
  --count 2
```

Both technical and theory exercises in one call:

```bash
python backend/agents/study_agent/run_agent.py \
  --topic <topic_id> \
  --action both \
  --count 3
```

## Generated Exercise Types

| action | exercise types produced |
|--------|------------------------|
| `exercises` | `technical`, `application`, `constraint` |
| `theory` | `visual`, `ear` |
| `both` | mix of all types |

## Acceptance Criteria

- Generated exercises have `type` of `"visual"` or `"ear"`
- Instructions guide the student to identify intervals, scales, or chord tones by ear
- `patternTab` (when present) illustrates the harmonic concept clearly
- IDs are prefixed with `{topic_id}-theory-`
- All text in Brazilian Portuguese
