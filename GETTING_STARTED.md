# Phase 1: Getting Started Guide

## What You're Building

A paper-trading bot that connects to Polymarket's live API, scans all active markets for mispriced opportunities using the LMSR/EV/Kelly math framework, and logs every signal and simulated trade to a SQLite database — so you can validate your strategy before risking real money.

---

## Step 0: Prerequisites

You need **Python 3.9+** installed. Check with:

```bash
python --version
# Should show Python 3.9 or higher
```

---

## Step 1: Install Dependencies

```bash
# Core (required)
pip install requests

# Real-time streaming (recommended)
pip install websockets

# For live trading later in Phase 3 (optional for now)
pip install py-clob-client
```

That's it. The bot uses the **Gamma API** (free, no auth needed) for market data and the **CLOB API** (free for reads) for order books and prices.

---

## Step 2: Run Your First Scan

```bash
python phase1_bot.py --scan
```

This will:
1. Connect to `gamma-api.polymarket.com` (health check)
2. Fetch all active markets (paginated, sorted by 24h volume)
3. Run the probability estimator on each market
4. Filter for opportunities with ≥5¢ edge and ≥8% EV/dollar
5. Run risk checks (position limits, exposure caps)
6. Paper-execute approved trades
7. Print a performance summary

**Expected output** — you'll see something like:

```
12:30:01 | MarketFetcher    | INFO  | Gamma API: OK
12:30:01 | MarketFetcher    | INFO  | CLOB API: OK
12:30:05 | MarketFetcher    | INFO  | Fetched 347 active markets
12:30:05 | EdgeScanner      | INFO  | Found 3 tradeable signals from 347 markets
12:30:05 | PaperTrader      | INFO  | 📝 PAPER TRADE #1: NO Will X happen? | 142.3 shares @ $0.07 = $9.96 | Edge: 0.062
...
```

---

## Step 3: Run Continuously

```bash
# Scan every 60 seconds (default)
python phase1_bot.py --loop

# Scan every 2 minutes
python phase1_bot.py --loop --interval 120

# Run 10 cycles then stop
python phase1_bot.py --loop --cycles 10

# Enable debug logging for troubleshooting
python phase1_bot.py --loop --debug
```

Press `Ctrl+C` to stop. All data is saved to `polybot_trades.db`.

---

## Step 4: Check Your Results

```bash
# Print performance summary
python phase1_bot.py --report
```

Or query the database directly:

```bash
# View all signals found
sqlite3 polybot_trades.db "SELECT timestamp, question, side, edge, ev_per_dollar, approved FROM signals ORDER BY timestamp DESC LIMIT 20;"

# View all paper trades
sqlite3 polybot_trades.db "SELECT timestamp, question, side, entry_price, shares, size_usd, pnl FROM paper_trades ORDER BY timestamp DESC;"

# Signals approval rate
sqlite3 polybot_trades.db "SELECT approved, COUNT(*) FROM signals GROUP BY approved;"
```

---

## Step 5: Understanding the Code Architecture

```
phase1_bot.py
│
├── Config              — All parameters (edge thresholds, Kelly fraction, limits)
│
├── MarketFetcher       — Connects to Gamma API + CLOB API, fetches markets
│   ├── fetch_all_active_markets()   — Paginated market discovery
│   ├── fetch_order_book()           — Order book depth (for sizing)
│   └── fetch_price()                — Real-time midpoint prices
│
├── MathEngine          — All the math from the article
│   ├── expected_value()             — EV = p_true - market_price
│   ├── kelly_quarter()              — Quarter-Kelly position sizing
│   ├── position_size()              — Final size with all caps
│   └── bayesian_shrink()            — Combat overconfidence
│
├── ProbabilityEstimator — ⚠️ THIS IS WHERE YOUR EDGE LIVES ⚠️
│   └── estimate()                   — Returns (p_true, confidence, reasoning)
│
├── EdgeScanner         — Combines markets + probabilities → signals
│   └── scan()                       — Filter & rank by EV/dollar
│
├── RiskManager         — Enforces all risk rules
│   └── check()                      — Drawdown limits, exposure caps
│
├── TradeDB             — SQLite logging for all signals + trades
│
├── PaperTrader         — Simulated execution engine
│
└── PolymarketBot       — Main loop tying everything together
```

---

## Step 6: Build Your Actual Edge (The Hard Part)

The default `ProbabilityEstimator` uses simple heuristics (structural arbitrage, extreme price fading). **This won't make money consistently.** You need to replace it with real data-driven models.

### Where to start:

**Weather markets** (easiest edge — data is public and free):
```python
# In ProbabilityEstimator.estimate():
if "temperature" in market.question.lower() or "weather" in market.category:
    # Fetch NOAA forecast
    noaa_prob = fetch_noaa_probability(market)  # You build this
    if noaa_prob is not None:
        return (noaa_prob, 0.85, f"NOAA forecast: {noaa_prob:.0%}")
```

NOAA publishes 24-48h forecasts with 93%+ accuracy. Polymarket weather buckets are often priced by people checking casual weather apps.

**Crypto markets** (fast-moving, latency matters):
```python
if "bitcoin" in market.question.lower() or "btc" in market.question.lower():
    # Fetch Binance/Deribit implied volatility
    # Calculate binary option probability using Black-Scholes
    strike = parse_strike_from_question(market.question)
    iv = fetch_implied_vol("BTCUSDT")
    p = black_scholes_binary(current_price, strike, iv, time_to_expiry)
    return (p, 0.6, f"Options-implied: {p:.0%}, IV={iv:.0%}")
```

**Political/event markets** (hardest — requires qualitative judgment):
```python
if market.category == "politics":
    # Aggregate multiple polling sources
    polls = fetch_538_average(market)
    models = fetch_prediction_models(market)
    p = aggregate_with_shrinkage(polls, models, base_rate=0.5)
    return (p, 0.5, f"Poll aggregate: {p:.0%}")
```

---

## Step 7: What's Next (Phase 2-4)

| Phase | Goal | Timeline |
|-------|------|----------|
| **Phase 1** (you are here) | Connect to API, paper trade, validate pipeline | Week 1-2 |
| **Phase 2** | Build real probability models (NOAA, crypto feeds, polls) | Week 3-4 |
| **Phase 3** | Live execution with `py-clob-client`, maker orders only | Week 5-6 |
| **Phase 4** | Monitoring, Telegram alerts, calibration tracking | Week 7-8 |

### Before going live (Phase 3), you need:
1. A **Polymarket account** with USDC on Polygon
2. Your **private key** (export from Polymarket settings or MetaMask)
3. **4+ weeks of paper trading data** showing consistent positive EV
4. A **calibrated model** — when you predict 70%, you should win ~70% of the time

### To export your private key from Polymarket:
1. Go to polymarket.com → Settings → Private Key
2. Click "Start Export"
3. Authenticate via Magic.Link
4. Copy the private key (NEVER share it or commit it to git)
5. Set it as an environment variable:
   ```bash
   export POLYMARKET_PRIVATE_KEY="0xYourKeyHere"
   ```

---

## Common Issues

**"No markets fetched"**
→ API might be rate-limiting you. Try `--interval 120` for slower scanning.

**"0 tradeable signals"**
→ Normal! The default estimator is conservative. Lower the edge threshold:
  `--min-edge 0.03` (but expect lower quality signals).

**"requests.exceptions.ConnectionError"**
→ Check your internet. The Gamma API is at `gamma-api.polymarket.com`.

**"ImportError: py_clob_client"**
→ You only need this for live trading. Paper trading works with just `requests`.

---

## Important Disclaimers

- **This is educational software, not financial advice.**
- Paper trading performance does NOT guarantee live results.
- Prediction market trading involves real financial risk.
- Verify Polymarket's legality in your jurisdiction before trading.
- Never risk money you can't afford to lose.
- The 93% of wallets that lose money aren't all stupid — the market is genuinely hard to beat.
