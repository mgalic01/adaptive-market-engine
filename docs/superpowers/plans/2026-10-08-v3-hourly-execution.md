# V3 hourly execution implementation plan

Purpose: implement the frozen experiment's execution chronology so its costs and
risk exposure can be evaluated faithfully. Synthetic fixtures only; no data fetch
or replay authorization, no adoption of the pending audit amendment.

1. Test and implement mandatory quantity reductions without the daily rebalance
   band, reusing the prescribed minimum/dust/max split rules.
2. Test and implement leverage checkpoint handling: liquidation first, masked and
   tradable gross, proportional targets, one reduction batch, post-cost recheck,
   explicit invalid outcome if the limit cannot be restored.
3. Integrate hourly open marks, daily reduction-before-increase batches, funding
   timestamp groups and adverse marks, preserving terminal evidence and true peaks.
4. Add deferred decision scheduling, then inspect lifecycle/report consumers before
   connecting actual data. Missing invariants stop the experiment as engine errors.
5. Run focused synthetic tests and static checks, inspect the full diff, publish
   for Bob and Cloud review. Keep the branch stacked on the account PR until its
   dependencies merge; do not merge into a dependency branch.

Owner: Codex Desktop. This plan implements sections5/6; broader strategy families,
walk-forward selection and evaluation remain separate outstanding work.
