# Options hand check (Phase 9 acceptance)

16 Nov 2026. Phase 9's acceptance: **"A covered call and a vertical spread can
be modelled, traded on paper and settled."** Each figure below is worked by
hand and asserted by `apps/api/tests/test_options_hand_check.py`.

The Black-Scholes figures in section 1 come from a separate implementation
using Python's `statistics.NormalDist` for N(x) and n(x), not the engine's
`math.erf` version; the arithmetic is shown so it can be checked on a
calculator. Sections 2 to 4 use round premiums set by hand, so every cash
movement is plain arithmetic. All amounts are USD; one contract is 100 shares.

## 1. One price, its Greeks, and implied volatility

A call with S = 100, K = 105, T = 0.25 years, σ = 20%, r = 5%.

| Step | Working | Value |
| --- | --- | --- |
| ln(S/K) | ln(100/105) | -0.048790 |
| (r + σ²/2)T | (0.05 + 0.02) × 0.25 | 0.017500 |
| σ√T | 0.20 × 0.5 | 0.100000 |
| d1 | (-0.048790 + 0.017500) / 0.1 | -0.312902 |
| d2 | d1 - 0.1 | -0.412902 |
| N(d1), N(d2) | normal CDF | 0.377178, 0.339839 |
| e^(-rT) | e^(-0.0125) | 0.987578 |
| **Call** | 100 × 0.377178 - 105 × 0.987578 × 0.339839 | **2.477902** |
| **Put** | 105 × 0.987578 × N(-d2) - 100 × N(-d1) | **6.173571** |
| Parity check | C - P = S - K e^(-rT) | -3.695669 both sides |
| Delta | N(d1) | 0.377178 |
| Gamma | n(d1) / (S σ √T), n(d1) = 0.379883 | 0.037988 |
| Vega (per 1.00 of σ) | S n(d1) √T | 18.994145 |
| Theta (per calendar day) | (-S n(d1) σ / (2√T) - r K e^(-rT) N(d2)) / 365 | -0.025643 |
| Rho (per 1.00 of r) | K T e^(-rT) N(d2) | 8.809967 |

Implied volatility: solving for the σ that prices the call at 2.477902 gives
back 20.0000% (Newton on vega; within 1e-6).

## 2. Covered call: 2 contracts on 200 shares

200 shares held at an average cost of 90. Write 2 calls at K = 110 for 2.50 a
share: **premium received 2 × 100 × 2.50 = 500**. The 200 shares are held back
while the call is open.

| Expiry close | What happens | Cash | Realized |
| --- | --- | --- | --- |
| 120 (in the money) | Assigned: the 200 shares are sold at 110, not 120 | +22,000 (200 × 110) | shares (110 - 90) × 200 = **+4,000**; option leg **+500** |
| 105 (out of the money) | Expires; the shares are released | 0 | option leg **+500** |

## 3. Bull call spread 100/110, 1 contract (a debit vertical)

Buy the 100 call for 6.00, write the 110 call for 2.00: **net debit
(6 - 2) × 100 = 400**. The long call covers the short one, so nothing is held
back. Most it can lose 400; most it can gain (110 - 100) × 100 - 400 = 600;
breakeven 100 + 4 = 104.

Settled in cash at intrinsic value; long legs receive it, short legs pay it.

| Expiry close | Long 100 call | Short 110 call | Net cash | Realized (long + short) |
| --- | --- | --- | --- | --- |
| 115 (both in) | +1,500 | -500 | **+1,000** | (1,500 - 600) + (200 - 500) = **+600** (the most it can gain) |
| 105 (one in) | +500 | 0 | **+500** | (500 - 600) + 200 = **+100** |
| 95 (neither) | 0 | 0 | **0** | -600 + 200 = **-400** (the most it can lose) |

## 4. Bear call spread 100/110, 1 contract (a credit vertical)

Write the 100 call for 6.00, buy the 110 call for 2.00: **net credit 400**.
The most the legs can cost at expiry is the width, (110 - 100) × 100 =
**1,000, held back** while it is open (the 400 credit stays spendable). Most
it can lose 1,000 - 400 = 600; most it can gain 400.

| Expiry close | Short 100 call | Long 110 call | Net cash | Realized |
| --- | --- | --- | --- | --- |
| 115 | -1,500 | +500 | **-1,000** (paid from the held-back cash) | (600 - 1,500) + (500 - 200) = **-600** |

After settlement nothing is held back: available cash equals cash again.
