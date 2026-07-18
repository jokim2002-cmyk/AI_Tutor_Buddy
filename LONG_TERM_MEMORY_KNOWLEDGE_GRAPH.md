# Long-Term Student Memory & Knowledge Graph

## Purpose

Phase 6G gives GyanVerse Academy durable learning continuity.

Each student receives a separate knowledge graph and evidence timeline. The
system can identify prerequisite gaps, recurring misconceptions, revision
needs, and likely forgetting risk without permanently labelling the student.

## Core Capabilities

### Concept Mastery Graph

Each concept stores:

- subject;
- concept name;
- prerequisites;
- mastery level;
- confidence score;
- evidence count;
- last evidence time;
- next revision time;
- linked misconceptions.

### Mastery Levels

- unknown;
- introduced;
- developing;
- proficient;
- mastered;
- needs revision.

Mastery describes current evidence for a concept. It does not describe the
student's identity or intelligence.

### Prerequisite Traversal

The graph can:

- build an ordered learning path;
- block a concept when prerequisites are not ready;
- detect invalid dependency cycles;
- unlock progression after sufficient mastery.

### Misconception Memory

The system records recurring misconceptions, counts repeated appearances, and
stores resolution evidence.

Example:

- Incorrect pattern: adding unlike denominators directly.
- Occurrence count: 3.
- Resolution evidence: two independently solved examples.

### Revision Scheduling

Revision priority considers:

- mastery level;
- known misconceptions;
- due date;
- forgetting risk.

Suggested strategies include:

- misconception repair;
- guided retrieval practice;
- spaced recall.

### Shared Teacher Memory

Subject Teachers, the Class Teacher, and Principal can access evidence according
to role permissions.

Guardian-facing information is generated as a safe summary. Raw teacher notes
and private evidence are not exposed automatically.

### Durable Storage Boundary

The phase provides:

- an in-memory repository for tests and development;
- a JSONL repository for local durable storage and migration testing;
- a repository interface for a future database implementation.

## Privacy and Retention

- Every student memory graph is isolated.
- Role-based visibility is enforced.
- Guardian access is summary-only.
- Restricted safeguarding records follow a separate retention boundary.
- Ordinary memory may be pruned by retention policy.
- Permanent negative student labels are prohibited.

## Phase Boundary

This phase does not yet create production database migrations, cloud sync, or
the final visual progress graph. It establishes the domain model, service
boundary, privacy rules, scheduling logic, and durable repository contract.
