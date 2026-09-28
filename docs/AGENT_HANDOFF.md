      **While Codex's allowance is exhausted, a Claude session (not the automated
      review) that did not write or revise the task file substitutes for Codex's
      pre-merge task-file review** (owner instruction 2026-09-28, Claude session
      `e0b16be3`: *"same goes for things if bob merges you need to do the correct
      steps before he does it"* — applied here to task-file PRs by any author, under
      the same principle): that Claude session reviews the task PR at the full head
      and posts its verdict; the automated review does not count as this review; the
      exhausted-allowance gate then applies as for any other PR. Codex reviews the
      task file on return, owed in the
      [Codex-review-owed issue](https://github.com/mgalic01/adaptive-market-engine/issues/134).