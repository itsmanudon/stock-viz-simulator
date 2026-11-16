# Phase 8 risk figures checked by hand

Date: 2026-11-13. The handover's Phase 8 acceptance: **"Risk figures state
their method and horizon and match a hand-checked sample."** Each worked
example below is asserted by a test, so a change to the method that moves a
figure fails the build.

## 1. Time-weighted return (8.1)

`tests/test_returns.py::test_twr_chains_sub_periods_and_removes_outside_flows`

Valuations 100 (2 Jan), 160 (9 Jan, after a deposit of 50 that day), 144
(16 Jan).

- Sub-period 1: (160 - 50) / 100 = 1.10
- Sub-period 2: 144 / 160 = 0.90
- TWR = 1.10 x 0.90 - 1 = **-1.0%** (the deposit does not count as a gain)

## 2. Money-weighted return, XIRR (8.1)

`tests/test_returns.py::test_xirr_matches_the_published_example` uses
Microsoft's documented XIRR example: -10,000 on 1 Jan 2008, then 2,750 (1 Mar
2008), 4,250 (30 Oct 2008), 3,250 (15 Feb 2009), 2,750 (1 Apr 2009). The
published answer is 0.373362535, so **37.3362535%**; the engine matches to
1e-5 percentage points.

One holding (`test_headline_pl_includes_options_and_realized_gains`): MSFT
bought for 1,000 two hundred days ago and worth 900 today:
(900 / 1,000)^(365 / 200) - 1 = 0.9^1.825 - 1 = **-17.49%** a year.

## 3. FX attribution (8.2)

`tests/test_exposure_attribution.py::test_gain_splits_into_price_currency_and_cross`

USD account; 10 SAP.DE bought at 100 EUR with the euro at 1.10 USD; now 120
EUR with the euro at 1.05 USD.

| Part | Arithmetic | USD |
| --- | --- | ---: |
| Cost | 10 x 100 x 1.10 | 1,100 |
| Value | 10 x 120 x 1.05 | 1,260 |
| Price | 10 x (120 - 100) x 1.10 | +220 |
| Currency | 10 x 100 x (1.05 - 1.10) | -50 |
| Cross | 10 x (120 - 100) x (1.05 - 1.10) | -10 |
| Check | 220 - 50 - 10 = 160 = 1,260 - 1,100 | |

## 4. VaR and CVaR, historical simulation (8.3)

`tests/test_risk.py::test_hand_checked_var_and_cvar`

The rule: over n scenarios at confidence c, k = ceil(n x (1 - c)); **VaR** is
the k-th largest loss; **CVaR** is the mean of the k largest losses.

Twenty days of P&L (USD): 120, -340, 55, -80, 410, -15, -260, 90, 30, -500,
75, -45, 160, -120, 20, 300, -210, 5, -60, 140.

Losses, largest first: 500, 340, 260, 210, 120, 80, 60, 45, 15, then the
gains.

| Confidence | k | VaR | CVaR |
| --- | ---: | ---: | ---: |
| 95% | ceil(20 x 0.05) = 1 | 500 | 500 |
| 90% | ceil(20 x 0.10) = 2 | 340 | (500 + 340) / 2 = 420 |
| 75% | ceil(20 x 0.25) = 5 | 120 | (500 + 340 + 260 + 210 + 120) / 5 = 286 |

The endpoint itself (`test_risk_endpoint_matches_an_independent_calculation`)
is checked against a separate, plain-Python recomputation over 298 sessions
of two holdings, one in rupees: each scenario is 100 x AAPL's close times its
return plus 20 x RELIANCE.NS's close x the INR rate times
(1 + its return)(1 + the rupee's return) - 1. The 1-day 95% VaR and CVaR
agree to the cent.

A long option is repriced in full, so its loss cannot exceed its value
(`test_a_long_option_cannot_lose_more_than_its_value`).

## 5. Monte Carlo (8.3)

`tests/test_risk.py::test_bootstrap_is_repeatable_and_exact_for_a_constant_series`:
with every past day at +0.1%, every resampled path ends at
100,000 x 1.001^252 = **128,643.40**, so all percentiles are equal; with a
fixed seed the same input gives the same output.

## 6. Stress test, combined shock (8.4)

`tests/test_stress.py::test_combined_shock_matches_the_hand_check`

USD account: 100 AAPL at 100 USD; 166 RELIANCE.NS at 2,500 INR with the
rupee at 0.012 USD; 100,000 INR of cash. Scenario: US stocks -20%, Indian
stocks -20%, rupee 10% weaker, applied instantly.

| Holding | Value (USD) | Move | Change (USD) |
| --- | ---: | --- | ---: |
| AAPL | 100 x 100 = 10,000 | -20% | -2,000.00 |
| RELIANCE.NS | 166 x 2,500 x 0.012 = 4,980 | (0.8 x 0.9) - 1 = -28% | -1,394.40 |
| INR cash | 100,000 x 0.012 = 1,200 | -10% | -120.00 |
| **Total** | | | **-3,514.40** |

A historical window (`test_historical_window_uses_own_history_or_a_beta_proxy`):
AAPL fell from 100 to 70 over the COVID window, so 10 shares lose 300; MSFT
has no bar then and moves twice the index day by day over its recent
history (beta 2), so it takes the index's -20% x 2 = -40%.
