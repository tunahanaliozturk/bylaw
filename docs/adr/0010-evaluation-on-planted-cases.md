# 0010: Evaluate on planted cases with certain labels

Status: Accepted, 2026-10-15

## Context

The design promises recall and precision per category, a false alarm rate on clean pull requests and cost per pull request, measured per model. Those numbers are only as good as the labels behind them. A label has to say exactly where a defect is, which categories count as right, and what a reviewer may add without being wrong.

## Decision

The set is 50 synthetic cases: four small base projects (Python, TypeScript, Go, C#) and one planted change per case, each labelled with the defect's lines, the accepted categories, the allowed spans and the accepted criterion statuses. A case is built into a real git repository and goes through the normal context, prompt and validation code. A finding matches a label within 2 lines. A test runs a reviewer that answers with the labels and requires a perfect score, so every label is reachable through the real pipeline.

## Consequences

- Labels are certain: each case has one planted defect, written on purpose, so a miss is a miss.
- The set is stable: it does not change when an upstream project rewrites its history, and there are no licence questions about copying third-party code.
- A paid run is resumable and per case, so the cost of a full run is known after the first few cases.
- Given up: realism. Real pull requests are larger, mix several concerns and carry history that a planted case does not. Scores here are an upper bound on what a reviewer does on messy, large changes.
- The 2-line tolerance accepts a finding on the line before or after the defect, which is where reviewers often anchor a multi-line problem. It also means two defects closer than 5 lines apart in one file could be confused, so cases keep one defect each.

## Alternatives

- **Mined real pull requests with the review comments that led to fixes.** Lost because the labels are uncertain: an unreported problem is not proof of a clean change, and a fix commit often fixes something other than what the comment said. It would win as a second, smaller set once the planted set has stopped finding problems in bylaw itself.
- **Exact line matching.** Lost because it punishes a finding anchored on the first line of a statement that spans two lines.
- **Scoring raw model output.** Lost because users see what passes validation; the dropped share is reported separately.
