# GyanVerse Academy — V1 Anti-Drift Plan

## Executive Summary
This plan defines the official V1 product boundaries, evaluation policy, testing rules, completion strategy, and done criteria for GyanVerse Academy. Its purpose is to prevent scope creep and eliminate non-scalable per-question evaluator patching.

---

## 1. V1 Product Scope

GyanVerse Academy is an offline-first AI Tutor & Test Engine for **GSEB** (Gujarat State Secondary and Higher Secondary Education Board), serving **Std 7 and Std 8** in both **English and Gujarati medium** across **four core subjects**:
1. English
2. Mathematics
3. Science & Technology
4. Social Science

### Core Included Features:
- **Tutor Explanation**: Chapter & topic explanations grounded in local GSEB syllabus repository.
- **Two Examples Request**: Local generation of two relevant real-world/chapter examples on student demand.
- **Hint-Only Guidance**: Actionable, progressive hint delivery without revealing direct answers prematurely.
- **Chapter Tests**: Deterministic generation of 25-mark single-chapter random test papers.
- **Full Syllabus Tests**: Deterministic generation of 100-mark full-syllabus random test papers with natural Section A–D structure.
- **Weak-Topic Revision**: Progress tracking and automated student weak-topic identification.

---

## 2. Explicitly Out of Scope for V1

- **Perfect Board-Exam Grading for Every Open-Ended Answer**: Arbitrary essay and creative writing scoring that mimics human board examiners down to stylistic nuance.
- **Per-Question Hardcoded String Evaluators**: Writing individual `elif "question text"` branches for every unique test prompt.
- **Handwriting Recognition / Optical Mark Recognition**: Automated grading of scanned physical student answer sheets.

---

## 3. Standardized Evaluation Policy

To balance accuracy, scalability, and fairness:

1. **Deterministic Auto-Grading (1-Mark Objective / Factual / Numeric)**:
   - Reserved strictly for objective items, numerical calculations, unit conversions, single proper nouns, binary true/false, and categorical classifications.
   - Uses strict matching, exact numeric range checks, and canonical entity lookup.

2. **Rubric & Key-Points Feedback (2, 3, 6-Mark Descriptive)**:
   - 2/3/6-mark descriptive answers MUST NOT be auto-marked `Correct` or `Incorrect` unless a structured, reusable rubric or generic evaluation pattern exists.
   - Evaluated against key concept coverage (identifying essential historical, scientific, or civic concepts present vs. missing).

3. **Fallback Policy ("Needs Review")**:
   - If no structured reusable rubric exists for a descriptive answer, the system result MUST be `"Needs review"` with key-point feedback.
   - No confident marks should be awarded automatically when no structured rubric exists.

---

## 4. Manual Testing Policy

1. **Test One Gate at a Time**: Focus manual testing and verification strictly on one target gate/workflow at a time.
2. **Run Targeted Tests Only**: Execute only the specific test module or command relevant to the current gate (e.g. `python -m unittest tests/test_gseb_english_7_social_science.py -v`).
3. **Milestone Validation**: Execute full validation loops (`unittest discover` or `validate_phase11.ps1`) only before major milestone commits or releases, NOT after every micro-fix.

---

## 5. Project Completion Strategy

- **Workflow Locking**: V1 completes by locking end-to-end workflows per subject (explanation, examples, hint-only, test rendering, objective auto-grading, and descriptive rubric/needs-review feedback).
- **Quality Boundary**: V1 is NOT completed by attempting to perfect-grade every possible student answer variation for open-ended descriptive prompts.

---

## 6. Stop Rules

1. **No Per-Question Evaluator Patching**:
   - Immediately halt adding question-specific string checks unless the change establishes a **reusable, generic evaluator pattern** (e.g., `DirectionalContradictionGuard`, `SetCoverageEvaluator`, `CategoryCountEvaluator`).

2. **No Unsolicited Full Validation Loops**:
   - Do not execute repository-wide `unittest discover` or `validate_phase11.ps1` runs unless explicitly instructed by the user.

---

## 7. Done Criteria for Std 7 English-Medium

A subject is considered **TutorReady V1 Done** when:
- **Paper Generation**: 25-mark chapter tests and 100-mark full-syllabus papers render deterministically without generic template title insertions (`"Explain in detail..."`) or variant leakage (`"(Variant..."`).
- **Section Depth**: Section D (6-mark) questions strictly enforce long-answer depth and reject factual recall prefixes (`"What was"`, `"Who was"`, `"Name"`).
- **Answer Evaluation**: 1-mark factual/objective questions achieve deterministic precision; 2/3/6-mark descriptive items use rubric key-point coverage or `"Needs review"` fallbacks.
- **Test Integrity**: All automated regression tests pass cleanly for the subject module.

---

## 8. Next Implementation Step

1. **Refactor Evaluation Engine**: Abstract existing specific evaluators into generalized, reusable evaluation primitives (`SetCoverageEvaluator`, `DirectionalContradictionGuard`, `CategoryCountEvaluator`).
2. **Apply Fallback Policy**: Implement the `"Needs review"` status for un-anchored open-ended descriptive questions across all 4 subjects.
