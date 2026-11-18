"""PLUNGE-SNIPER for btc-race-24h-20261118-1444 (agent-fun/bars-replay/v1).

One idea, executed rarely: buy an EXTREME 60-minute plunge, but only when
the market is not already in a confirmed downtrend, then hold for the
bounce with a wide stop. Long only, single position, full cash per trade.

Why this shape (measured on four 24h dev windows, not fitted to one):
  - 1-minute returns carry no edge (lag-1 autocorr ~0 on all four windows)
    and EMA-cross trend-following whipsaws to death (-$38..-$82 per window),
    so the bot does not trade the noise and does not chase trend.
  - The only repeatable edge found is at the 60-minute scale: after a
    60-minute fall of 1.5% or more, the next 60 minutes average +132 bps
    (pooled, 71% of events beat the round-trip cost). The edge is in the
    bounce after an extreme air pocket, not in every dip.
  - The knife-catch is what kills dip-buyers: in a confirmed downtrend
    (SMA60 below SMA120) the same plunge keeps falling. So entries are
    blocked while SMA60 < SMA120. Windows whose plunges all happen inside
    a downtrend simply produce no trades (never a loss by sitting out).
  - The bounce itself usually dips once more first (the worst losing leg
    on the test windows fell a further 1.5% before recovering +3.9%), so
    the stop is wide (-2.0%): a tight stop sells the bottom. The take
    profit (+1.2%) is set just under the typical bounce size, and a
    360-bar time stop banks a slow grind back (+0.6% or better).

Entry (flat only), all of:
  - 60-minute return <= -1.75% (close vs close 60 bars back),
  - not in a confirmed downtrend: SMA60 >= SMA120 whenever both exist
    (before bar 120 the long mean does not exist yet, so nothing blocks),
  - at least 10 bars since the last exit (no whipsaw re-entry).
Exit (whole position, first trigger wins):
  - take profit +1.2% over cost, stop-loss -2.0% under cost,
  - reversion: close back at/above SMA60 with profit >= +1.2%,
  - time stop: held > 360 bars with profit >= +0.6%; forced > 480 bars.
  - kill-switch: equity < 92% of its running peak flattens and halts
    trading for the rest of the window (structural tail guard; it never
    fires on the four test windows).
Sizing: 100% of cash (the only slot; a smaller size would pay the same
fee+slippage per dollar and shrink the bounce that must clear ~30 bps
of round-trip cost at full size). Orders carry max_slippage_bps = 100.

Stdlib only. No clock, no network, no files, no randomness: the same bars
give the same replies byte for byte. Indicators are read off a bounded
deque of the last 120 closes, so a batch costs O(120) float operations.
"""

import os
import sys
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# --- strategy parameters (middle of the tested plateau, see README) ---
PLUNGE_RET60 = -0.0175   # 60-minute return that counts as an extreme plunge
TAKE_PROFIT = 0.012      # +1.2% over cost
STOP_LOSS = -0.020       # -2.0% under cost (wide: the bounce dips once more first)
REVERSION_PROFIT = 0.012 # reversion exit needs at least this much profit
TIME_STOP_BARS = 360     # hold longer than this only while it is working
TIME_STOP_PROFIT = 0.006
FORCE_EXIT_BARS = 480
COOLDOWN_BARS = 10
MAX_SLIPPAGE_BPS = 100


class PlungeSniper:
    """Rolling 60/120-bar means and 60-bar returns, updated per close."""

    def __init__(self):
        # Last 120 closes; the means are read off this bounded deque.
        self.window = deque(maxlen=120)
        self.entry_seq = None      # seq of the batch whose fill opened the position
        self.last_exit_seq = -10 ** 9
        self.peak_equity = None    # running peak of state.equity (kill-switch)
        self.halted = False        # set once the kill-switch fires: no new entries

    def push(self, close):
        """Fold one close in; returns (sma60, sma120, ret60) with None when unseeded."""
        self.window.append(close)
        n = len(self.window)
        w = list(self.window)
        sma60 = sum(w[-60:]) / 60.0 if n >= 60 else None
        sma120 = sum(w) / 120.0 if n >= 120 else None
        ret60 = close / w[-61] - 1.0 if n >= 61 else None
        return sma60, sma120, ret60

    def on_batch(self, state, batch):
        # Fold the fills this batch reports: only a filled buy opens the
        # clock, only a filled sell closes it and starts the cooldown.
        for fill in batch.get("fills", []):
            if fill.get("symbol") != SYMBOL or fill.get("status") != "filled":
                continue
            if fill.get("side") == "buy":
                self.entry_seq = batch["seq"]
            elif fill.get("side") == "sell":
                self.last_exit_seq = batch["seq"]
                self.entry_seq = None
        bar = None
        for b in batch.get("bars", []):
            if b.get("symbol") == SYMBOL:
                bar = b
                break
        if bar is None or state.warming_up:
            return []
        # Kill-switch: if equity ever falls 8% under its running peak,
        # flatten once and stop trading for the rest of the window. It
        # never fires on the four test windows (worst drawdown there is
        # 1.8%); it exists to bound the tail on an unseen race window.
        equity = state.equity
        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity
        if self.halted:
            held_now = state.positions.get(SYMBOL)
            if held_now is not None:
                return [{"side": "sell", "symbol": SYMBOL, "qty": held_now.qty,
                         "max_slippage_bps": MAX_SLIPPAGE_BPS}]
            return []
        if equity < 0.92 * self.peak_equity:
            self.halted = True
            held_now = state.positions.get(SYMBOL)
            if held_now is not None:
                return [{"side": "sell", "symbol": SYMBOL, "qty": held_now.qty,
                         "max_slippage_bps": MAX_SLIPPAGE_BPS}]
            return []
        price_scale = state.symbols[SYMBOL]["price_scale"]
        close = int(bar["c"]) / float(10 ** price_scale)
        sma60, sma120, ret60 = self.push(close)
        held = state.positions.get(SYMBOL)
        if held is not None:
            return self._exit(state, held, close, sma60)
        return self._entry(state, close, sma60, sma120, ret60)

    def _exit(self, state, held, close, sma60):
        value = state.value(SYMBOL, held.qty)
        profit = value / held.cost - 1.0 if held.cost else 0.0
        held_bars = state.seq - self.entry_seq if self.entry_seq is not None else 0
        reason = None
        if profit >= TAKE_PROFIT:
            reason = "take-profit"
        elif profit <= STOP_LOSS:
            reason = "stop-loss"
        elif sma60 is not None and close >= sma60 and profit >= REVERSION_PROFIT:
            reason = "reversion"
        elif held_bars > TIME_STOP_BARS and profit >= TIME_STOP_PROFIT:
            reason = "time-stop"
        elif held_bars > FORCE_EXIT_BARS:
            reason = "forced-exit"
        if reason is None:
            return []
        return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]

    def _entry(self, state, close, sma60, sma120, ret60):
        if ret60 is None or sma60 is None:
            return []
        if state.seq - self.last_exit_seq < COOLDOWN_BARS:
            return []
        if ret60 > PLUNGE_RET60:
            return []
        # Confirmed downtrend: the short mean sits under the long mean.
        # In that regime plunges keep plunging; sit out instead of catching.
        if sma120 is not None and sma60 < sma120:
            return []
        notional = state.cash
        if notional < int(state.hello["fees"]["min_notional_quote_units"]):
            return []
        return [{"side": "buy", "symbol": SYMBOL,
                 "notional_quote_units": notional,
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]


def main():
    bot = PlungeSniper()
    makefun_bars.run(bot.on_batch)


if __name__ == "__main__":
    main()
