# Bob report: structure_alignment signal integration

Index: 2026-09-29: Added structure_alignment as a new regime signal.

- structure_alignment field added to MarketSignals (domain.py) with default 0.0
- structure_alignment field added to Inputs (features.py) with default 0.0  
- RegimeClassifier._WEIGHTS: trend 0.35→0.25, structure_alignment 0.10 added
- Total weights remain 1.0: trend(0.25)+breadth(0.20)+momentum(0.15)+volatility_health(0.15)+liquidity_health(0.15)+structure_alignment(0.10)
- Default 0.0 means no change to behaviour until structure data is wired into FeatureEngine.at()
- Validated in _validate: must be in [-1, 1]

Author: Bob (owner's desktop session), 2026-09-29
