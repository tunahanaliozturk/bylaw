# Real pull requests: selection rules

The planted set (ADR 0010) has certain labels and little realism. The real set is the other half: pull requests people actually opened, reviewed and merged, frozen so a run never reads live data (ADR 0015). These rules decide which pull requests may join it. They are strict on purpose: every rule removes a way a label could be wrong.

## A pull request joins the real set when

1. **The project is permissively licensed.** GitHub detects the licence as MIT, Apache-2.0, BSD-2-Clause or BSD-3-Clause **at the commit the files are copied from**, and no touched file names another licence in its header. Anything else is skipped, including no licence and `NOASSERTION`, even when the text reads like MIT: the rule is applied as written, not by eye. The snapshot copies files from the project, so the licence has to allow it, and the case keeps the licence text and any `NOTICE` file of that commit.
2. **It was merged into the default branch** between 1 January 2023 and the day it was picked, by a person, not a bot. Merged means the project accepted the result, so the review that shaped it was taken seriously. Dependency bumps from bots have no review worth learning from.
3. **It has a linked issue in the same repository.** GitHub's "closing issues" list names it. The issue is the requirement bylaw checks the change against, and a linked issue in another repository would not be read without an opt-in (ADR 0007).
4. **A reviewer other than the author left an inline comment that names a concrete problem**: a bug, a security problem, a broken project rule or convention, or something the issue asks for that the change misses. Not a question, not praise, not a matter of taste. Inline, because a label needs a file and a line.
5. **The comment led to a fix.** A later commit in the same pull request changes the commented lines, within 3 lines, the way the comment asked. This is what makes the label trustworthy: the author agreed there was a problem by fixing it. A comment that was argued away or ignored proves nothing.
6. **The reviewed commit still exists.** The case is the pull request as the reviewer saw it, so the commit the comment was made on must still be readable. Force-pushed history that GitHub no longer serves rules a pull request out.
7. **It is small.** At the reviewed commit the change touches at most 8 files, none binary, generated or a lockfile, each under 60 KB (the snapshot tool enforces it). Large changes are realistic, but they make a committed snapshot heavy and a label hard to check by hand.
8. **The languages are ones bylaw reviews well**: Python, TypeScript or JavaScript, and Go. The set spreads over at least 6 projects with at most 5 pull requests each, so one project's habits do not decide the score.

## What a case is

The case is the pull request at the **reviewed commit**, not at the merge. At the merge the problem is already fixed; at the reviewed commit it is still there, which is what a reviewer is asked to find. The base is the merge base of the reviewed commit and the pull request's base branch, which is exactly what GitHub diffed for the reviewer.

## Why these rules and not looser ones

- Mining every merged pull request would be cheaper, but an unreported problem is not proof of a clean change (ADR 0010). The real set therefore labels only what a reviewer found and the author fixed, and treats the rest of the change as unknown, not clean.
- Requiring a fix rather than any review comment drops a lot of candidates. It is still worth it: a comment the author rejected is an opinion, and labelling opinions as defects would punish a reviewer for disagreeing with one person.
- Requiring a linked issue drops pull requests that fix something nobody wrote down, but keeps the requirement check in the measurement, which is the part of bylaw the planted set covers least realistically.

How cases are labelled, and by whom, is in [labelling.md](labelling.md).
