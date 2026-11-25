"""Each study's canonical signal, as a Rule DSL rule (A3.4, M2.6).

The evidence badge on a study grades this rule with the A2.4 evidence study
(``services/checklist/evidence.py::study``): the first bar it is true after
a bar it was false, the forward 20-session return net of the venue's fees,
against the same-date base rate of the universe. Every rule uses the
study's **default parameters**; a study the user has re-parametrised shows
the default's grade and says so.

A study with no textbook single-bar signal (OBV, ATR, pivots, the RS line,
...) has no entry and shows "No grade". Never invent one to fill the badge.
Wording is neutral: a signal "crosses up through", never "buy".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Signal:
    rule: str
    description: str
    source: str = ""


SIGNALS: dict[str, Signal] = {
    "rsi": Signal("rsi(14) crosses_above 30", "RSI(14) crosses up through 30", "Wilder, 1978"),
    "macd": Signal(
        "macd(12, 26, 9) crosses_above macd(12, 26, 9).signal",
        "MACD line crosses above its signal line",
        "Appel",
    ),
    "ppo": Signal(
        "ppo(12, 26, 9) crosses_above ppo(12, 26, 9).signal",
        "PPO crosses above its signal line",
    ),
    "sma": Signal("close crosses_above sma(close, 20)", "Close crosses above its 20-bar SMA"),
    "ema": Signal("close crosses_above ema(close, 20)", "Close crosses above its 20-bar EMA"),
    "hma": Signal("close crosses_above hma(20)", "Close crosses above the Hull MA(20)"),
    "dema": Signal("close crosses_above dema(20)", "Close crosses above DEMA(20)"),
    "tema": Signal("close crosses_above tema(20)", "Close crosses above TEMA(20)"),
    "kama": Signal("close crosses_above kama(10, 2, 30)", "Close crosses above KAMA(10, 2, 30)"),
    "supertrend": Signal(
        "supertrend(10, 3).direction crosses_above 0", "Supertrend(10, 3) flips up"
    ),
    "psar": Signal(
        "psar(0.02, 0.2).direction crosses_above 0", "Parabolic SAR flips below price", "Wilder"
    ),
    "ichimoku": Signal(
        "close crosses_above max(ichimoku(9, 26, 52, 26).senkou_a, "
        "ichimoku(9, 26, 52, 26).senkou_b)",
        "Close crosses above the cloud",
    ),
    "donchian": Signal(
        "close > donchian(20).upper[1]", "Close above the prior 20-bar high (breakout)", "Donchian"
    ),
    "aroon": Signal(
        "aroon(25).up crosses_above aroon(25).down", "Aroon up crosses above Aroon down", "Chande"
    ),
    "adx": Signal(
        "adx(14).plus_di crosses_above adx(14).minus_di", "+DI crosses above -DI", "Wilder"
    ),
    "vortex": Signal("vortex(14).plus crosses_above vortex(14).minus", "+VI crosses above -VI"),
    "cci": Signal("cci(20) crosses_above -100", "CCI(20) crosses up through -100", "Lambert"),
    "stoch": Signal("stoch(14, 3) crosses_above 20", "Stochastic %K crosses up through 20"),
    "stochrsi": Signal(
        "stochrsi(14, 14, 3, 3) crosses_above 20", "StochRSI %K crosses up through 20"
    ),
    "willr": Signal("willr(14) crosses_above -80", "Williams %R crosses up through -80"),
    "mfi": Signal("mfi(14) crosses_above 20", "MFI(14) crosses up through 20"),
    "cmo": Signal("cmo(9) crosses_above -50", "Chande momentum crosses up through -50"),
    "roc": Signal("roc(12) crosses_above 0", "ROC(12) crosses above zero"),
    "tsi": Signal(
        "tsi(25, 13, 7) crosses_above tsi(25, 13, 7).signal", "TSI crosses above its signal"
    ),
    "trix": Signal("trix(15) crosses_above 0", "TRIX(15) crosses above zero", "Hutson"),
    "coppock": Signal(
        "coppock(14, 11, 10) < 0 and change(coppock(14, 11, 10)) > 0",
        "Coppock curve turns up below zero",
        "Coppock, 1962 (on daily bars here)",
    ),
    "bb": Signal("close crosses_above bb(20, 2).lower", "Close crosses back above the lower band"),
    "keltner": Signal(
        "close crosses_above keltner(20, 2, 10).upper", "Close crosses above the upper channel"
    ),
    "cmf": Signal("cmf(20) crosses_above 0", "Chaikin money flow crosses above zero"),
    "chaikin": Signal("chaikin(3, 10) crosses_above 0", "Chaikin oscillator crosses above zero"),
    "force": Signal("force(13) crosses_above 0", "Force index(13) crosses above zero", "Elder"),
    "eom": Signal("eom(14) crosses_above 0", "Ease of movement crosses above zero"),
}


__all__ = ["SIGNALS", "Signal"]
