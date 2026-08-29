# Teacher Reasoning Engine

## Purpose

The Teacher Reasoning Engine converts a `StudentAnalysis` object into an
explainable teaching decision before any language model generates the lesson.

The language model writes the response. GyanVerse controls the pedagogy.

## Decision Outputs

- selected teacher;
- teaching action;
- step size;
- difficulty direction;
- teaching methods;
- understanding-check requirement;
- prerequisite-check requirement;
- revision requirement;
- confidence-support requirement;
- final-answer release policy;
- human-readable rationale;
- structured evidence.

## Teaching Actions

- `clarify`
- `check_prerequisites`
- `give_hint`
- `explain`
- `guided_practice`
- `independent_practice`
- `revise`
- `extend`

## Priority Order

1. Missing context → clarify.
2. Possible prerequisite gap → check foundations.
3. Urgent revision → revise.
4. Confusion → explain.
5. Guessing → hint and reasoning prompt.
6. Developing understanding → guided practice.
7. Demonstrated understanding → independent or extension practice.

## Safety Rules

- The engine never labels a student.
- It never exposes private hidden reasoning.
- It records only short, auditable evidence statements.
- It prevents immediate final-answer release when clarification, foundations,
  hints, or reasoning should come first.
- Decisions must be re-evaluated after new student evidence.
- Teacher personality may affect method and tone, but cannot override academy
  safety or prerequisite rules.

## Phase Boundary

Phase 6C is deterministic and isolated. It does not yet replace the existing live
Gemini chat flow. Phase 6D will formalize the Teaching Strategy Selector, and a
later integration phase will connect these decisions to live lesson generation.
