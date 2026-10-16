# bylaw

bylaw reviews a pull request or a local branch against what the repository already wrote down: its `.editorconfig`, linter configuration, CONTRIBUTING and agent instructions, and the acceptance criteria of the issues and specs the change says it implements. Every rule finding cites the line of the rule it rests on, and bylaw checks each finding against the diff before it is shown or posted.

The host model does the reviewing, so no extra API key is needed. bylaw itself runs from PyPI through `uvx`, so you need uv installed.

## Use it

- `/bylaw-review` reviews the current branch against the default branch.
- `/bylaw-review 12` reviews pull request 12 and shows the review.
- `/bylaw-review 12 post` posts the review to pull request 12.

Reviewing a pull request needs the GitHub CLI signed in, or `GITHUB_TOKEN` set. The token is passed to bylaw for that one command and is only sent to the GitHub API.

## What leaves your machine

bylaw has no server. It reads the pull request, its linked issues and the repository's rule files from the GitHub API, and posts comments there only when you ask for it. The review itself is done by the model you are already talking to.

The source, the GitHub Action and the full documentation live in the bylaw repository on GitHub, linked from this plugin's listing.
