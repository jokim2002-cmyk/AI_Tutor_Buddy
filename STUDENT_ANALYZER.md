# Student Analyzer

## Purpose

The Student Analyzer converts current messages and learning-history evidence into
a small, auditable decision object for the Teacher Reasoning Engine.

It does **not** diagnose intelligence, personality, disability, or mental health.
It records temporary learning signals only.

## Inputs

- student ID;
- class level and preferred language;
- subject and topic;
- recent accuracy;
- attempts, hints, and repeated mistakes;
- prior mastery;
- practice gap;
- previously helpful teaching methods;
- recent student messages.

## Outputs

- confidence signal: low, medium, high, or unknown;
- understanding state: confused, guessing, developing, understood, or unknown;
- revision need: none, soon, or urgent;
- recommended teacher subject;
- recommended teaching methods;
- prerequisite-check flag;
- clarification-question flag;
- evidence list;
- safe human-readable summary.

## Safety Rules

- No permanent negative labels.
- Message wording alone must never be treated as proof of ability.
- Every output must remain explainable through evidence.
- Ambiguity should trigger clarification, not guessing.
- Wellbeing and safeguarding remain separate from academic confidence analysis.

## Phase Boundary

Phase 6B produces analysis only. It does not yet change the live Gemini response
flow. Phase 6C will consume this structured analysis inside the Teacher Reasoning
Engine.
