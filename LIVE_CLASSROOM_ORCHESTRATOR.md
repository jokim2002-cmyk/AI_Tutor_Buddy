# Live Classroom Orchestrator

## Purpose

The Live Classroom Orchestrator converts analysis, reasoning, and teaching
strategy into a controlled lesson lifecycle.

It manages the lesson rather than generating final natural-language teacher
responses.

## Lesson Lifecycle

1. Session start
2. Greeting
3. Goal setting
4. Teaching
5. Guided practice
6. Independent practice
7. Understanding check
8. Revision when required
9. Homework
10. Summary
11. Complete

## Core Components

### Lesson State Machine

Only valid classroom transitions are allowed. Invalid jumps, such as moving
directly from session start to homework, are rejected.

### Teacher Turn Manager

Chooses the next classroom action:

- greet;
- explain;
- ask a question;
- give a hint;
- encourage;
- revise;
- challenge;
- assign homework;
- summarize;
- wait.

### Session Memory

Stores:

- current stage;
- last strategy;
- mistakes;
- pending doubts;
- homework IDs;
- revision topics;
- progress events;
- stages visited.

### Progress and Collaboration

Progress events may notify:

- Asha Ma'am as Class Teacher;
- Principal Arvind;
- later parent-report pipelines.

### Learning Goals

Goals may be:

- locked;
- active;
- completed;
- needing revision.

Completing one goal can unlock a prerequisite-dependent next goal.

## Safety Boundaries

- Final-answer policy remains controlled by the reasoning engine.
- Failed understanding checks route to revision.
- Revision targets the idea, never the student's identity.
- No invalid stage jump is allowed.
- Lesson completion requires a controlled sequence.
- Progress events are auditable.
- Parent reports are not generated from raw private conversation text.

## Phase Boundary

Phase 6F does not yet connect to Gemini-generated teacher language or voice.
It produces a deterministic classroom execution plan and audit trail.
