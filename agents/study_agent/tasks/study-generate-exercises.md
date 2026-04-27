---
id: study-generate-exercises
name: Study Agent — Generate Technical Exercises
goal: Generate {count} new technical guitar exercises for topic '{topic_id}' and append them to studyExercises.ts
action: exercises
default_count: 2
---

# Task: Generate Technical Exercises

Generate practical guitar exercises for the target topic and append them directly to
`frontend/src/app/study/studyExercises.ts` under the correct topic key.

## How to Run

```bash
python backend/agents/study_agent/run_agent.py \
  --topic <topic_id> \
  --action exercises \
  --count 2
```

Dry-run (preview only, no file write):

```bash
python backend/agents/study_agent/run_agent.py \
  --topic <topic_id> \
  --action exercises \
  --count 2 \
  --dry-run
```

## Acceptance Criteria

- Generated exercises match the `ExerciseDefinition` TypeScript interface
- Each exercise has a unique `id` prefixed with `{topic_id}-gen-`
- Instructions are in Brazilian Portuguese
- `bpmStart` and `bpmGoal` are included for `type: "technical"` exercises
- `patternTab` is a valid 6-line ASCII guitar tab when provided
- File `studyExercises.ts` compiles without TypeScript errors after append

## Topic IDs (examples)

Run `python backend/agents/study_agent/run_agent.py --list-topics` to see all available topics.

Common topic IDs:
- `postura-anatomia-tecnica-basica`
- `escalas-e-modos`
- `arpejos`
- `acordes-triades-e-intervalos`
- `campo-harmonico`
- `cadencias`
- `caged`
- `circulo-de-quintas`
