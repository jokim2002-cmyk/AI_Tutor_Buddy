# ROADMAP: AI Tutor Buddy / GyanVerse Academy

## Canonical Development Policy

- Core intelligence before UI.
- UI only after backend contracts are stable.
- EXE/APK packaging only after stabilization.
- Every phase requires:
  - backup;
  - implementation;
  - automated tests;
  - full regression validation;
  - documentation;
  - Git checkpoint;
  - clean working tree.
- Student dignity, privacy, explainability, and guardian-safe reporting are mandatory across all phases.

## Product Identity & Canonical Scope

- **Internal engine:** AI Tutor Buddy
- **Public brand:** GyanVerse Academy
- **Supported classes/standards:** Classes 1 through 10
- **First production boards:** GSEB and CBSE
- **Target platforms:** Windows and Android

### Status Separation
- **Implemented source:** Responsive shell, tutor composer, context persistence, voice/attachment flow, board-neutral syllabus repository foundation.
- **Automated validation:** Executed dynamically via test suite and `validate_phase11.ps1`.
- **Pending curriculum coverage:** Acquisition and validation of official textbook packages for GSEB and CBSE.
- **Pending build acceptance:** Windows EXE packaging and Android APK packaging verification.
- **Pending device acceptance:** Physical Android phone and Windows desktop acceptance.

## Academy Architecture

```text
Student
  ↓
Student Analyzer
  ↓
Teacher Reasoning Engine
  ↓
Teaching Strategy Selector
  ↓
Live Classroom Orchestrator
  ↓
Long-Term Student Memory & Knowledge Graph
  ↓
Class Teacher
  ↓
Principal
  ↓
Parent / Guardian
```

## Completed Foundation

### Phase 1 — Vision & Planning ✅

- Product vision
- Teaching ethics
- School metaphor
- Core personas
- Initial architecture
- Roadmap policy

### Phase 2 — Environment & Git ✅

- Local development environment
- Repository initialization
- Git workflow
- Backup and validation discipline
- Remote GitHub checkpoints

### Phase 3 — AI Brain ✅

- AI interaction foundation
- Structured tutoring flow
- Prompt and response foundations
- Safety-oriented teaching behavior

### Phase 4 — Voice Foundation ✅

- Initial voice capability foundation
- Speech interaction direction
- Voice-ready architecture boundary

### Phase 5 — Core Tutoring Engine ✅

- Core tutor engine
- Daily sync
- Homework generation and checking
- Diagnostic tracking
- Revision tracking
- Core automated tests

## Phase 6 — GyanVerse Intelligence

### Phase 6A — Academy Foundation ✅

- Academy constitution
- Architecture contracts
- Staff profiles
- Subject routing
- Safe teacher prompts
- Automated academy tests

### Phase 6B — Student Analyzer ✅

- Stable student-context contract
- Subject inference
- Evidence-based confidence signals
- Confusion, guessing, developing, and understood states
- Revision urgency detection
- Prerequisite-check recommendations
- Teaching-method recommendations
- Safe database/API adapter
- Non-labelling safety rules
- Automated analyzer tests

### Phase 6C — Teacher Reasoning Engine ✅

- Structured teaching-decision contract
- Clarification and prerequisite priority rules
- Hint, explanation, practice, revision, and extension actions
- Step-size selection
- Difficulty-direction selection
- Final-answer release policy
- Teacher-profile coordination
- Explainable reasoning evidence
- Safe teaching-plan generation
- Automated reasoning-engine tests

### Phase 6D — Teaching Strategy Selector ✅

- Central teaching-strategy catalog
- Subject-aware pedagogy defaults
- Strategy compatibility rules
- Explainable strategy scoring
- Primary and supporting strategy selection
- Student-preference support
- Recent-strategy variety control
- Current-turn avoid list
- Student-facing teaching sequence
- Reasoning-engine integration
- Final-answer policy preservation
- Automated strategy-selector tests

### Phase 6E — Parent, Guardian & Future Path Intelligence ✅

- Guardian profiles
- Multiple children per guardian
- Linked-child authorization
- Privacy-safe progress snapshots
- Daily guardian reports
- Class Teacher guardian conversations
- Principal progress overview
- Strength and interest mapping
- Home-support recommendations
- Sensitive-note protection
- Safeguarding summary boundary
- Sibling-comparison protection
- Exploration-based future-path guidance
- Non-deterministic career recommendations
- Automated guardian-intelligence tests

### Phase 6F — Live Classroom Orchestrator ✅

- Lesson session manager
- Classroom lifecycle state machine
- Valid transition enforcement
- Teacher turn manager
- Guided and independent practice
- Understanding-check revision routing
- Homework and summary flow
- Session memory
- Progress event generation
- Staff collaboration notifications
- Class Teacher and Principal updates
- Learning goals
- Prerequisite-based goal unlocking
- Session audit records
- Classroom service integration
- Automated classroom-orchestrator tests

### Phase 6G — Long-Term Student Memory & Knowledge Graph ✅

- Isolated memory per student
- Concept mastery graph
- Prerequisite relationships
- Ordered learning-path traversal
- Blocked-concept detection
- Knowledge-graph cycle protection
- Mastery evidence updates
- Misconception history
- Repeated misconception counting
- Misconception resolution evidence
- Spaced revision scheduling
- Forgotten-topic risk detection
- Revision prioritization
- Teacher-shared memory
- Guardian-safe summary boundary
- Role-based memory visibility
- Memory retention policy
- In-memory repository
- JSONL durable-storage boundary
- Automated long-term-memory tests

### Phase 6H — Learning Intelligence & Exam Readiness ✅

- Student learning intelligence profile
- Subject and concept mastery aggregation
- Learning velocity
- Consistency and effort trends
- Evidence-based exam readiness
- Syllabus coverage tracking
- Weak-prerequisite impact analysis
- Revision-plan generation
- Priority topic ranking
- Confidence calibration
- Readiness uncertainty reporting
- Non-deterministic prediction policy
- Class Teacher and Principal intelligence summaries
- Guardian-safe readiness summary
- Automated learning-intelligence tests

## Later Product Phases

### Phase 7 — Parent Monitoring & Reports ✅

- Parent portal backend
- Daily, weekly, and monthly reports
- Multiple-child dashboard
- Home-support actions
- Notification preferences
- Safe alerts
- Report history and exports

### Phase 8 — Performance, Safety & Stabilization ✅

- Full integration testing
- Security review
- Privacy controls
- Error handling and recovery
- Performance profiling
- Rate limiting
- Secrets management
- Backup and restore
- Data-deletion workflows
- Release-candidate stabilization

### Phase 9 — UI/UX ✅

- Student classroom UI
- Parent portal UI
- Teacher dashboard
- Principal dashboard
- Homework screens
- Progress timeline
- Knowledge-graph visualization
- Accessibility
- Responsive design
- Final UI/UX polish
- Responsive Flet application shell
- Student, parent, teacher, and principal role views
- Offline-safe core tutoring workflows
- Settings and privacy transparency

### Phase 10 — EXE, APK & Release 🟡 IN PROGRESS

- Production API deployment
- Windows EXE packaging
- Android APK/AAB packaging
- Installer and update strategy
- Release documentation
- Acceptance testing
- Final release audit
- Production launch

## Current Verified Checkpoint

```text
Phase 6G complete
Tests: 89/89 PASS
Latest verified commit: 102ee9d
Branch: master
Remote: origin/master
Working tree: clean
```

## Roadmap Tally

```text
Completed:
- Phase 1
- Phase 2
- Phase 3
- Phase 4
- Phase 5
- Phase 6A
- Phase 6B
- Phase 6C
- Phase 6D
- Phase 6E
- Phase 6F
- Phase 6G

Next:
- Phase 6H

Pending after 6H:
- Phase 7
- Phase 8
- Phase 9
- Phase 10
```

## Completion Estimate

- Core intelligence/backend foundation: approximately 85%
- Overall user-ready product: approximately 60%

These percentages are planning estimates, not automated measurements. They should be revised after every major phase.

---

## Phase 11 implementation checkpoint

The cohesive Phase 11 source batch adds the responsive hidden-drawer shell, modern tutor composer, persistent student context (Classes 1–10, GSEB and CBSE), voice/attachment integration paths, local homework history, board-neutral syllabus repository foundation, original branding, cross-platform packaging configuration and Phase 11 automated tests. Historical initial checkpoint baseline was 215 tests; actual current total is evaluated dynamically by `validate_phase11.ps1`.

Phase 11 remains **IN PROGRESS**, not complete. Windows/Android builds and physical-device acceptance gates—including microphone, spoken output, attachment providers, narrow-screen layout and official syllabus source coverage—must pass before final release sign-off. See `PHASE11_IMPLEMENTATION.md`.

---

## Phase 11 — Production Tutor Experience, Mobile UX, Voice and GSEB Foundation

### Goal

Deliver a polished Windows EXE and Android APK that feel like a trusted personal tutor rather than a generic demo app. The student must be able to open the app and immediately continue learning from the chapter currently being taught in school.

### 11.1 Mobile-first responsive shell

- Fit every screen correctly on common Android phone sizes without horizontal clipping.
- Replace the permanently visible left navigation rail with a hidden slide-out drawer.
- Provide a compact menu or arrow control to open and close the drawer.
- Keep the main learning area full-width when the drawer is closed.
- Reduce oversized icons, padding and empty space.
- Add safe scrolling for long lessons, answers and homework reviews.
- Preserve a clean equivalent desktop layout for the Windows EXE.

### 11.2 Tutor-grade conversational interface

- Build a modern ChatGPT/Gemini-style chat experience.
- Add a clearly visible rounded message composer fixed near the bottom.
- Support multiline typing and long questions.
- Show user and tutor messages in readable conversation bubbles or cards.
- Add typing/loading indicators, retry states and clear error messages.
- Preserve conversation context within the current learning session.
- Use a professional student-friendly colour system with accessible contrast.
- Avoid developer terminology and technical configuration in the student UI.

### 11.3 Student learning-context onboarding

The student should not be forced to begin from zero every time.

- On first use, collect board, medium, standard and preferred language.
- Let the student say or type: “Today we studied Chapter 4 in class.”
- Detect or ask for subject, chapter and topic only when needed.
- Save the current school-learning context locally.
- Reopen the app at the latest subject/chapter context.
- Let the student quickly switch class, medium, subject or chapter.
- Adapt explanation depth, examples, vocabulary and answer format to the selected standard.
- Distinguish explanation, homework help, revision and exam-answer modes.

### 11.4 GSEB syllabus and knowledge foundation

- Add a structured GSEB content model:
  - Board
  - Medium
  - Standard
  - Subject
  - Textbook
  - Chapter
  - Topic
  - Learning objective
  - Explanation
  - Examples
  - Exercises
  - Solutions
  - Practice questions
  - Marks pattern
- Support Gujarati, English and Hindi-medium learning paths where source material is available.
- Add a syllabus import and validation pipeline instead of hard-coding content into the UI.
- Track source, edition, standard, subject and chapter metadata.
- Clearly separate official textbook material from AI-generated examples and practice.
- Prevent unsupported claims when syllabus content is missing.
- Add chapter-completion and syllabus-coverage reporting.

### 11.5 Voice input and spoken answers

- Add Android microphone permission handling.
- Add working speech-to-text for Gujarati, Hindi and English.
- Show recognised speech in the composer before submission.
- Let the student edit recognised text.
- Add text-to-speech playback for tutor responses.
- Provide visible recording, processing, playback, stop and failure states.
- Fall back gracefully to typing when voice services are unavailable.
- Test voice functionality on a real Android device and Windows.

### 11.6 Homework submission and review

- Add a prominent “+” attachment button beside the chat composer.
- Support camera capture, gallery images, PDFs and common document formats.
- Let the student submit one or multiple homework pages.
- Show upload previews before submission.
- Provide progress, cancellation and retry controls.
- Allow the tutor to read the question, identify subject/chapter, explain the method, review the student’s attempt, highlight mistakes and provide hints before revealing the final answer.
- Save homework sessions and review history locally.
- Add privacy-safe file handling and clear deletion controls.

### 11.7 GyanVerse brand system

- Create an original GyanVerse Academy logo suitable for Android launcher icon, Windows app icon, splash screen, app header, and light/dark backgrounds.
- Define a consistent colour palette, typography scale, icon style and spacing system.
- Ensure the app looks credible, calm and education-focused.
- Avoid a template-like or random-app appearance.

### 11.8 Reliability and release quality

- Keep existing backend and packaging tests passing.
- Add responsive-layout tests for narrow phone widths.
- Add tests for drawer open/close behaviour.
- Add chat-composer and attachment-flow tests.
- Add voice permission and fallback tests.
- Add learning-context persistence tests.
- Add GSEB syllabus schema/import validation tests.
- Add homework upload and error-state tests.
- Test Android back-button behaviour.
- Test app close/reopen and offline-safe behaviour.
- Produce a signed/reproducible Windows EXE and Android APK.
- Run full Windows and real-device Android acceptance testing.

### Phase 11 release gates

Phase 11 is complete only when all of the following pass:

1. Android UI fits common phone screens without clipping.
2. Navigation drawer is hidden by default and does not consume learning space.
3. Chat experience feels clear and familiar to a student.
4. Voice input and spoken output work on a real Android phone.
5. The “+” attachment flow accepts homework photos and files.
6. The app remembers board, medium, standard and current chapter.
7. GSEB content is loaded through the validated syllabus structure.
8. Long answers and homework reviews remain readable and scrollable.
9. Windows EXE and Android APK pass the same core tutor workflows.
10. Automated tests, packaging checks and operator acceptance all pass.

### Planned implementation order

1. Responsive shell and hidden navigation drawer.
2. Tutor chat composer and conversation layout.
3. Student profile and current-chapter context.
4. Voice input/output.
5. Homework attachment and review flow.
6. GSEB syllabus schema and importer.
7. GyanVerse visual identity and logo integration.
8. Full regression, device acceptance, packaging, commit and release checkpoint.

