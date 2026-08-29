# Teaching Strategy Selector

## Purpose

The Teaching Strategy Selector converts the Teacher Reasoning Engine's decision
into a concrete method for teaching the next turn.

The Reasoning Engine decides **what the teacher should do**.

The Strategy Selector decides **how the teacher should teach it**.

## Strategy Catalog

- Step-by-step
- Worked example
- Analogy
- Socratic questioning
- Visual explanation
- Story-based teaching
- Observation or experiment
- Retrieval practice
- Error correction
- Debugging
- Communication practice
- Timeline and cause-effect
- Transfer challenge
- Confidence rebuild

## Inputs

- student analysis;
- teacher reasoning decision;
- subject;
- current understanding and confidence;
- selected step size and difficulty;
- optional student preferences;
- recently used strategies.

## Outputs

- primary strategy;
- up to two supporting strategies;
- strategies to avoid for the current turn;
- ranked, explainable scores;
- student-facing teaching sequence;
- teacher instruction;
- temporary selection summary.

## Subject Pedagogy

### Maths

Patterns, step-by-step reasoning, worked examples, visual grouping, and error
analysis.

### Science

Observation, prediction, safe experiments, evidence, analogy, and visual models.

### English and Hindi

Communication, contextual practice, short stories, feedback, vocabulary, and
expression.

### Computer

Logic, debugging, tracing, testing assumptions, worked examples, and gradual
independent practice.

### Social Science

Timeline, cause-effect, evidence, narrative context, comparison, and transfer.

## Safety

- A strategy never overrides prerequisite or final-answer safety.
- Unsafe experiments are prohibited.
- Errors are treated as learning evidence, never as a reason to shame.
- Confidence support praises effort and strategy, not fixed intelligence.
- The selector uses auditable scores, not private chain-of-thought.
- A strategy choice is temporary and must be reconsidered after new evidence.

## Phase Boundary

Phase 6D does not yet generate the final Gemini response. It produces a
structured strategic lesson plan. A later integration phase will connect this
plan to live prompt construction and lesson delivery.
