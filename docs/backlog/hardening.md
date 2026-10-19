# Hardening: known gaps from reviews

Roadmap: Q1, then ongoing in [ROADMAP.md](../ROADMAP.md). Target: patch releases. Item ids: `HRD-n`.

Small problems found by the milestone reviews. Each one is real but rare or minor; they are fixed in order of how likely a user meets them.

**Done when** the list is empty or every open item has a reason to wait.

## Items

- [x] **HRD-1** (S) Renamed-only, mode-only and empty files get the "binary or too large" note. Done when: a precise note per case.
- [x] **HRD-2** (S) An invalid glob such as `[z-a]` in a base `.editorconfig` ends the run with a traceback. Done when: the section is ignored with a note naming the file and section.
- [x] **HRD-3** (S) The note about skipped lock, vendored and generated files gives a count, not the paths. Done when: paths listed, capped.
- [x] **HRD-4** (S) Nothing says so when GitHub's 3000-file listing cap cuts a pull request short. Done when: a note in the summary.
- [x] **HRD-5** (M) If posting fails partway, the summary's saved state can disagree with the comments already posted. Done when: state written last and reconciled on the next run.
- [x] **HRD-6** (M) Two findings on identical lines in one file share a fingerprint, so one can hide the other. Done when: findings sharing a fingerprint pair with their own threads by line, and the state remembers thread ids.
- [x] **HRD-7** (S) `bylaw post --dry-run` previews with the default config, not the base branch's `.bylaw.toml`. Done when: dry run reads the base config.
- [x] **HRD-8** (S) Thread replies past the first 50 are not read, so a late mute or resolve can be missed. Done when: the first comment and the 50 newest replies are read.
- [x] **HRD-9** (M) The Anthropic call caps output at 20,000 tokens and does not stream. Done when: streaming with a higher cap.
- [x] **HRD-10** (M) The prompt budget counts characters, not tokens. Done when: the budget is set in tokens per repository and estimated conservatively; exact counting through a provider is left out because the Claude Code and Codex path has no key.
- [x] **HRD-11** (S) With the `pull_request_target` recipe, adding or removing a label re-runs the review. Done when: only the `bylaw` label triggers.
- [x] **HRD-12** (S) `/bylaw-review` argument parsing: `post` as a base name, `#12` and URLs, fork `origin`, `master` default. Done when: command handles each case.
- [x] **HRD-13** (S) `--base` reviews committed changes only, and the skill does not tell the user so. Done when: skill says it.
- [x] **HRD-14** (S) In `--pr` mode the skill may open local files that differ from the pull request's head. Done when: skill checks out or warns.
- [x] **HRD-15** (S) Codex manifest default prompt names pull request 12; listing fields missing (`websiteURL`, `privacyPolicyURL`, `logo`, `composerIcon`). Done when: manifest ready for a listing.
- [x] **HRD-16** (S) A failed paid evaluation attempt is billed but its tokens are not recorded. Done when: usage recorded on failure.
- [x] **HRD-17** (S) `bylaw eval run` exits 0 when cases failed, does not mention `BYLAW_API_KEY`, and does not show the case count first. Done when: exit code, message and count.
- [x] **HRD-18** (S) An evaluation case directory without `case.toml` is skipped silently; kind and labels are not cross-checked. Done when: load error.
- [x] **HRD-19** (S) Rule findings in the evaluation are matched by place and category, not by the rule line they cite. Done when: citation scored.
- [x] **HRD-20** (S) `cs-async-void` accepts only the declaration as the place of the defect. Done when: the call site also accepted.
- [x] **HRD-21** (S) Throwaway evaluation repositories run the user's global git hooks. Done when: hooks disabled in those repositories.
- [x] **HRD-22** (S) A linked issue whose comments cannot be read ends the review. Done when: review goes on without the comments, with a note.
- [x] **HRD-23** (S) Summary cells show 80 characters, so an inferred criterion of up to 300 is cut. Done when: criterion cells show the full text.
- [x] **HRD-24** (S) Maintainer comments sit under an in-band heading that an issue body could imitate. Done when: comments in their own labelled block.
- [x] **HRD-25** (S) Hidden (minimised) issue comments still count. Done when: read through GraphQL `isMinimized` and left out.
- [x] **HRD-26** (S) In a thread with more than 51 comments, replies between the first comment and the 50 newest are not read. Done when: long threads are paged.
- [x] **HRD-27** (S) A renamed file whose binary content also changed gets no note, and a copied file gets the generic one. Done when: both have their own note.
- [x] **HRD-28** (S) A pull request that already had two threads with the same fingerprint keeps an orphan thread after the HRD-6 pairing change. Done when: the orphan is resolved on the next run.
- [x] **HRD-29** (S) An OpenAI answer cut off by the output limit fails inside `responses.parse`, so its billed tokens are not recorded. Done when: usage is recorded for it too.
- [x] **HRD-30** (S) When the comments that could be read were all untrusted, the note says none could be read. Done when: the note depends on whether any page was read.
- [x] **HRD-31** (S) Current Codex docs put the interface under `extensions."com.openai"` in a root `plugin.json`; bylaw uses the `.codex-plugin/plugin.json` fallback. Done when: moved, and the install re-checked.
- [x] **HRD-32** (S) The test SSE stream has no thinking blocks, `ping` events or `stop_details`, so a refusal category and a stream that starts with thinking are untested. Done when: the adapter models them and tests cover both.
- [x] **HRD-33** (S) A moved file with no `sha` whose base lookup also returns nothing counts as unchanged. Done when: that pair gets the binary note, with a test.
- [x] **HRD-34** (S) A GraphQL error on the older-replies query of a long thread ends the run. Done when: the thread is read without its older replies, with a note.
- [x] **HRD-35** (S) Validation treats two different problems of the same category on the same lines as duplicates and drops the second (found by the Claude Code host evaluation: a shell injection and a path traversal on one line). Done when: findings are deduplicated by message as well, with a test.
- [x] **HRD-36** (S) Two different findings of one category on the same lines share a fingerprint, so their threads pair by line and then by order; if the model lists them the other way round, a mute or resolve can pass from one to the other. Done when: the message takes part in pairing for findings that share a fingerprint, without unpairing threads posted before, with a test.
- [ ] **HRD-37** (S) `bylaw review --pr --repo <another repository>` sends the tracker tokens in the environment to the Jira site or Azure DevOps organisation that the other repository's `.bylaw.toml` names. `bylaw mcp` and `bylaw context --pr` already pin the sites to `JIRA_URL` and `AZURE_DEVOPS_ORGANIZATION` when the repository is not `GITHUB_REPOSITORY` (ADR 0019). Done when: the same pinning applies to `bylaw review --pr`, with a test.

## Notes

Pick these up between features. Each fix comes with a test that fails first.
