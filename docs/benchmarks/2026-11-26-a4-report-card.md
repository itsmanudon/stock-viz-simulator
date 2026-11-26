# A4.3 report card: PSR, DSR and PBO worked by hand

Date: 2026-11-26. The A4 acceptance: **"Its report card's DSR and PSR match a
worked example in `docs/benchmarks/<date>-a4-report-card.md`."** Each example
below is asserted by a test in `apps/api/tests/test_report_card.py`, to the
precision stated, so a change to the method that moves a figure fails the
build. The code is `apps/api/src/stockviz/services/backtest/report.py`.

Sources:

- D. H. Bailey and M. López de Prado, "The Sharpe Ratio Efficient Frontier",
  *Journal of Risk* 15(2), 2012: the Probabilistic Sharpe Ratio (PSR).
- D. H. Bailey and M. López de Prado, "The Deflated Sharpe Ratio: Correcting
  for Selection Bias, Backtest Overfitting and Non-Normality", *Journal of
  Portfolio Management* 40(5), 2014: the expected maximum Sharpe of N trials
  and the DSR.
- D. H. Bailey, J. Borwein, M. López de Prado and Q. J. Zhu, "The Probability
  of Backtest Overfitting", *Journal of Computational Finance* 20(4), 2017:
  combinatorially symmetric cross-validation (CSCV) and PBO.

## Conventions

- Returns are daily. In a run they are the equity curve's net returns minus
  the daily risk-free rate (5% / 252), the same excess returns the
  summary's Sharpe uses. The example below gives excess returns directly.
- `SR` is the **per-day** Sharpe: mean / sample standard deviation (n - 1).
  The annualised Sharpe the page shows is `SR x sqrt(252)`.
- Skewness `g3 = m3 / m2^1.5` and kurtosis `g4 = m4 / m2^2` from population
  moments `mk = sum((x - mean)^k) / n`. `g4` is not excess: 3 for a normal.
- `T` is the number of daily returns.

## 1. PSR (`test_psr_matches_the_worked_example`, to 1e-6)

Ten daily excess returns:

`0.010, -0.005, 0.007, 0.002, -0.012, 0.015, 0.004, -0.003, 0.009, 0.001`

| Step | Arithmetic | Value |
| --- | --- | ---: |
| Mean | 0.028 / 10 | 0.0028 |
| Deviations squared, summed | 0.0005756 | |
| m2 | 0.0005756 / 10 | 5.756e-5 |
| Sample std | sqrt(0.0005756 / 9) | 0.0079972 |
| m3 | sum(d^3) / 10 | -1.41456e-7 |
| m4 | sum(d^4) / 10 | 7.94542e-9 |
| SR | 0.0028 / 0.0079972 | 0.3501216 |
| g3 | -1.41456e-7 / (5.756e-5)^1.5 | -0.3239218 |
| g4 | 7.94542e-9 / (5.756e-5)^2 | 2.3981439 |
| Denominator | sqrt(1 - g3 SR + (g4 - 1)/4 SR^2) = sqrt(1 + 0.113412 + 0.042849) | sqrt(1.1562599) |
| z | (0.3501216 - 0) x sqrt(9) / sqrt(1.1562599) | 0.9768152 |
| **PSR(0)** | Phi(0.9768152) | **0.835670** |

PSR(0) = 0.8357: about an 84% chance the true Sharpe of this track is above
zero, given its length, skew and fat or thin tails.

## 2. DSR (`test_dsr_matches_the_worked_example`, to 1e-6)

The same track, chosen as the best of **N = 5** variants whose per-day
Sharpes have variance **V = 0.01** (the trial ledger supplies both). With
the Euler-Mascheroni constant `g = 0.5772157`:

| Step | Arithmetic | Value |
| --- | --- | ---: |
| a | inv_Phi(1 - 1/5) = inv_Phi(0.8) | 0.8416212 |
| b | inv_Phi(1 - 1/(5e)) = inv_Phi(0.9264241) | 1.4496657 |
| SR0 | sqrt(0.01) x ((1 - g) a + g b) = 0.1 x (0.355824 + 0.836770) | 0.1192594 |
| z | (0.3501216 - 0.1192594) x 3 / sqrt(1.1562599) | 0.6440897 |
| **DSR** | Phi(0.6440897) | **0.740241** |

SR0 is the per-day Sharpe the best of five no-skill variants would be
expected to show (1.89 annualised). Measured against that bar instead of
zero, the probability drops from 0.836 to 0.740.

**One trial.** With N = 1 there is no maximum to deflate: SR0 = 0 and
DSR = PSR(0) (the test checks it), and the page says so. The same holds when
every variant had the same Sharpe (V = 0).

## 3. PBO by CSCV (`test_pbo_matches_the_worked_example`, logits to 1e-9)

Three settings A, B, C over eight sessions, split into S = 4 blocks of two
(the API uses S = 16 and at least 4 sessions a block; the test passes
`blocks=4, min_rows=2`).

| Session | A | B | C |
| ---: | ---: | ---: | ---: |
| 1 | 0.02 | 0.004 | -0.01 |
| 2 | 0.01 | -0.002 | -0.02 |
| 3 | 0.03 | 0.003 | -0.01 |
| 4 | 0.01 | -0.001 | 0.00 |
| 5 | -0.02 | 0.002 | 0.01 |
| 6 | -0.01 | -0.001 | 0.02 |
| 7 | -0.02 | 0.003 | 0.03 |
| 8 | 0.00 | -0.002 | 0.01 |

Blocks: 1 = sessions 1-2, 2 = 3-4, 3 = 5-6, 4 = 7-8. Each of the C(4, 2) = 6
choices of two blocks is the in-sample set; the other two are out of sample.
The setting with the best in-sample Sharpe is ranked among the three out of
sample (1 = worst, ties averaged), `w = rank / (N + 1)`, logit
`l = ln(w / (1 - w))`.

| In sample | In-sample Sharpe A, B, C | Best | Out-of-sample Sharpe A, B, C | Rank | w | Logit |
| --- | --- | --- | --- | ---: | ---: | ---: |
| 1, 2 | 1.8278, 0.3397, -1.2247 | A | -1.3056, 0.2100, 1.8278 | 1 | 0.25 | -1.0986 |
| 1, 3 | 0.0000, 0.2724, 0.0000 | B | 0.2402, 0.2852, 0.4392 | 2 | 0.50 | 0.0000 |
| 1, 4 | 0.1464, 0.2343, 0.1127 | B | 0.1127, 0.3638, 0.3873 | 2 | 0.50 | 0.0000 |
| 2, 3 | 0.1127, 0.3638, 0.3873 | C | 0.1464, 0.2343, 0.1127 | 1 | 0.25 | -1.0986 |
| 2, 4 | 0.2402, 0.2852, 0.4392 | C | 0.0000, 0.2724, 0.0000 | 1.5 | 0.375 | -0.5108 |
| 3, 4 | -1.3056, 0.2100, 1.8278 | C | 1.8278, 0.3397, -1.2247 | 1 | 0.25 | -1.0986 |

In the (2, 4) row C ties A out of sample at 0, so its rank is 1 + 0.5 = 1.5.
**PBO = share of logits <= 0 = 6 / 6 = 1.0**: every in-sample winner did no
better than the median out of sample. A and C trade the same swings in
opposite directions, so whichever half looks best in sample is the one that
reverses.

## 4. The other report-card figures (`test_metrics_on_a_hand_series`)

NAV 100, 110, 99, 121 on four consecutive days (three calendar days), cash
100, max drawdown 10%; three closed trades of +10 (R +2), -5 (R -1) and +20
(no stop).

| Metric | Formula | Value |
| --- | --- | ---: |
| CAGR | 1.21^(365.25 / 3) - 1 | (very large: three days) |
| Calmar | CAGR / 0.10 | |
| Win rate | 2 / 3 | 66.7% |
| Payoff ratio | mean win 15 / mean loss 5 | 3.0 |
| Profit factor | 30 / 5 | 6.0 |
| Expectancy | 25 / 3 | 8.33 |
| Expectancy (R) | (2 - 1) / 2 trades with a stop | 0.5 R |
| Exposure | held at the close of 3 of 4 sessions | 75% |
| Average holding | 1 calendar day each | 1 day |
| Sortino | mean(e) / sqrt(mean(min(e, 0)^2)) x sqrt(252) | per the test |
