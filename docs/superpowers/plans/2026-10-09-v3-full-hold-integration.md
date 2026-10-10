# Full-size hold input and report integration

Connect the separately decoded unmasked spot stream to the supplied-input experiment
and render its reported-only drawdown comparison. Keep strategy eligibility and A1-A5
unchanged. No fetch, historical dispatch or final verdict is authorized here.

1. Assemble hold_hourly independently of month eligibility, with the first full
   spot month boundary and duplicate checks. Test excluded-month separation.
2. Build an audited diagnostic summary with status, cash, fees, scheduled/attempt
   times and maximum drawdown. Unavailable diagnostics show no performance claim.
3. Require the dedicated stream in run_experiment; record the hold once at the same
   start/end as other accounts. Optional report input preserves legacy callers but
   leaves an explicit missing-diagnostic requirement when absent.
4. Test runner failure propagation and input routing, report boundary/account
   rejection, unavailable status and unchanged acceptance checks. Run focused
   integration/static checks and independent review before publication.
