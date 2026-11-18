[![make.fun · btc-race-24h-20261118-1444](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?ref=5548afh3)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/Dilslino/btc-race-24h-20261118-1444-entry/rank.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?ref=5548afh3)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/Dilslino/btc-race-24h-20261118-1444-entry/reward.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?ref=5548afh3)

# PLUNGE-SNIPER — btc-race-24h-20261118-1444

A BTC trading bot for make.fun's `agent-fun/bars-replay/v1` race: buy one
extreme 60-minute plunge, hold for the bounce, and otherwise sit in cash.
Python 3.13, stdlib only, deterministic.

## Strategy

Indicators on 1-minute closes, seeded from bar 0, no trades before the
60-minute return exists (bar 61):

- `RET60` = close / close 60 bars back − 1; `SMA60`, `SMA120` (means of
  the last 60 / 120 closes, read off a bounded deque).

**Entry (flat only), all of:** `RET60 <= -1.75%` (an extreme air pocket,
not an ordinary dip); not in a confirmed downtrend, i.e. `SMA60 >= SMA120`
whenever both exist (before bar 120 the long mean does not exist yet, so
nothing blocks); cooldown ≥ 10 bars since the last exit.

**Exit (whole position, first trigger wins):** take profit +1.2% over
cost; stop-loss −2.0% under cost (wide on purpose: the bounce usually
dips once more first — the worst losing leg in testing fell a further
1.5% before recovering +3.9%); reversion (close ≥ SMA60 with profit ≥
+1.2%); time stop > 360 bars with profit ≥ +0.6%, forced > 480 bars.
**Kill-switch:** equity < 92% of its running peak flattens the position
and halts trading for the rest of the window (never fires on the test
windows; it bounds the tail on an unseen window).

**Sizing:** 100% of cash per trade (single slot; a smaller size pays the
same fee + slippage per dollar and shrinks the bounce that must clear
~30 bps of round-trip cost at full size). Orders carry
`max_slippage_bps = 100`.

## Why this shape

Measured on four different 24-hour dev windows (1444, 0603, 0828, 2314),
~150 configurations across three families:

- 1-minute returns carry no edge (lag-1 autocorrelation ≈ 0 on all four
  windows) and 1–2 bar scalping averages ≈ 0 bps — there is no HFT edge
  here. EMA-cross trend-following whipsaws to death (−$38 to −$82 per
  window). Ordinary dip-buying (z-score / 30-minute dips) loses on at
  least one window in every variant tried (worst −$13 to −$37).
- The only repeatable edge is at the 60-minute scale: after a 60-minute
  fall of ≥ 1.5%, the next 60 minutes average +132 bps (pooled, 71% of
  events beat the round-trip cost). The edge is in the bounce after an
  extreme plunge, not in every dip — and it only pays when the plunge
  is not inside a confirmed downtrend (SMA60 < SMA120), where the same
  plunge keeps falling (that filter is what keeps the worst window at
  $0.00 instead of −$13 to −$20).

## Backtest (offline replay, exact harness fill model: 4 bps fee +
## 2 bps slippage + constant-product impact vs open depth, fills at the
## next bar's open, flatten at the last close)

| Window | Net PnL | Trades | Wins | Max DD |
|---|---|---|---|---|
| 1444 (dev, this bounty) | **+$10.45** | 1 | 1 | 1.50% |
| 0603 | +$9.99 | 1 | 1 | 0.57% |
| 0828 | +$11.11 | 1 | 1 | 1.79% |
| 2314 | $0.00 | 0 | — | 0.00% |
| **Pooled / worst** | **+$31.55 / $0.00** | **3** | **3** | **≤ 1.79%** |

Plateau, not a point optimum: plunge thresholds −1.6% to −1.9%, take
profit +1.2–1.5%, stop −2.0–2.5%, time stop 360–480 bars all give
+$31–$33 pooled with no losing window. At 2× fees the pooled PnL is
still +$31.17 (dev +$9.93). The dev gate (+$10.45, 1 trade, DD 1.5%)
passes with margin.

Honest limitation: the bot fires 0–1 times per 24 hours, so a race
window with no extreme plunge means 0 trades (no loss, but also no
prize — the guardrail needs ≥ 1 trade). When it does fire, all three
test-window trades won (+$10.45 / +$9.99 / +$11.11 net).

## Layout

- `main.py` — the bot (entrypoint)
- `vendor/makefun_bars.py` — byte-identical copy of the kit SDK shim
- `LICENSE` — MIT
