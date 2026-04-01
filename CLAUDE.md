# Claude Code Instructions - Polymarket Trading Bot

## Project Overview

This is a **Polymarket prediction market trading bot** that:
- Scans live markets via Polymarket Gamma API and CLOB API
- Estimates true probabilities using custom models (weather, crypto, sports)
- Identifies mispriced opportunities using Kelly criterion and EV math
- Executes trades (paper or live) with comprehensive risk management
- Tracks performance via SQLite database with Brier score calibration

**Current Phase**: Phase 3 (Live Trading) - Bot supports both paper trading and live execution

**Deployment**: Runs in Docker on a NAS, stores data in persistent volume

---

## Project Structure

```
/home/dias/polymarket-bot/
├── phase1_bot.py              # Main bot (all-in-one file, ~3200 lines)
├── docker-compose.yml         # Docker deployment config
├── Dockerfile                 # Container build instructions
├── .env.example               # Environment variable template
├── GETTING_STARTED.md         # Initial setup guide (paper trading)
├── LIVE_TRADING_GUIDE.md      # Live trading setup (Phase 3)
├── QUICK_START_LIVE.md        # Quick reference for live trading
└── polybot_trades.db          # SQLite database (in Docker volume: /data/)
```

**Note**: This is a monolithic architecture - all code is in `phase1_bot.py` by design for simplicity.

---

## Architecture (phase1_bot.py)

The bot is organized into modules (all in one file):

### Core Components

1. **Config** (line ~242)
   - All tunable parameters
   - Loads from environment variables via `Config.from_env()`
   - Key fields: `private_key`, `paper_trading`, `min_edge`, `kelly_fraction`, risk limits

2. **MarketFetcher** (line ~393)
   - Fetches markets from Gamma API (paginated)
   - Fetches order books from CLOB API
   - Fetches real-time prices for position updates
   - Health checks for API connectivity

3. **ProbabilityEstimator** (line ~800+)
   - **WeatherModel**: Uses NOAA/NWS API for temperature forecasts
   - **CryptoModel**: Uses Binance spot + Deribit options for binary pricing
   - **SportsModel**: Uses The Odds API for moneyline/spread pricing
   - Fallback heuristics for other markets (fade extremes, structural arbitrage)

4. **MathEngine** (embedded in estimator)
   - Kelly criterion for position sizing
   - Expected value calculations
   - Bayesian shrinkage for overconfidence correction

5. **EdgeScanner** (line ~2100+)
   - Combines markets + probability estimates → signals
   - Filters by minimum edge and EV thresholds
   - Ranks by EV per dollar

6. **RiskManager** (line ~2500+)
   - Position limits (max positions, max single position %)
   - Exposure caps (correlated markets, total exposure)
   - Daily drawdown limits
   - Liquidity checks

7. **TradeDB** (line ~2350+)
   - SQLite database for logging
   - Tables: `signals`, `paper_trades`, `forecasts`, `resolutions`
   - Brier score computation for calibration tracking
   - Performance statistics

8. **PaperTrader** (line ~2625)
   - Simulates order execution at market prices
   - Tracks unrealized P&L
   - No real API calls

9. **LiveTrader** (line ~2690+) ⚠️ PRODUCTION
   - Real order execution via py-clob-client
   - Maker-only strategy (limit orders, no market orders)
   - Order tracking and fill monitoring
   - Stale order cancellation (5min timeout)

10. **PolymarketBot** (line ~2900+)
    - Main orchestrator
    - Selects PaperTrader or LiveTrader based on `--live` flag
    - Run loop: Fetch → Scan → Risk check → Execute → Update → Log

---

## Data Flow

```
┌─────────────────┐
│  Market APIs    │
│ (Gamma + CLOB)  │
└────────┬────────┘
         │
         ▼
   MarketFetcher ──────┐
         │             │
         ▼             ▼
  ProbabilityEstimator  │
    (Weather/Crypto/    │
     Sports models)     │
         │              │
         ▼              │
    EdgeScanner ◄───────┘
         │
         ▼
    RiskManager
         │
         ▼
   ┌────┴────┐
   │         │
   ▼         ▼
PaperTrader  LiveTrader ──► Polymarket CLOB API
   │         │
   └────┬────┘
        │
        ▼
     TradeDB (SQLite)
```

---

## Development Workflow

### Making Changes to the Bot

1. **Read the relevant module first**
   ```bash
   # Find the module you need to edit
   grep -n "class MarketFetcher\|class EdgeScanner" phase1_bot.py

   # Read that section
   # Use Read tool with offset/limit for large file
   ```

2. **Test changes locally** (if possible)
   ```bash
   # Syntax check
   python3 -m py_compile phase1_bot.py

   # Test specific component
   python3 phase1_bot.py --test-weather
   python3 phase1_bot.py --test-crypto
   python3 phase1_bot.py --test-sports

   # Test full scan (paper mode)
   python3 phase1_bot.py --scan --debug
   ```

3. **Deploy to Docker**
   ```bash
   docker-compose down
   docker-compose build
   docker-compose up -d
   docker logs -f polymarket-bot
   ```

4. **Monitor for issues**
   ```bash
   # Check logs for errors
   docker logs polymarket-bot --tail 100

   # Verify bot is running
   docker ps | grep polymarket

   # Check performance
   docker exec polymarket-bot python3 phase1_bot.py --report --db /data/polybot_trades.db
   ```

### Common Tasks

#### Adding a New Probability Model

1. Create model class in the ProbabilityEstimator section
2. Add keyword detection in `estimate()` method
3. Add test function at bottom of file (e.g., `test_mymodel()`)
4. Update `--test-mymodel` argument in main()
5. Test: `python3 phase1_bot.py --test-mymodel`

Example structure:
```python
class MyModel:
    def estimate(self, market: Market) -> Optional[tuple[float, float, str]]:
        # Returns: (p_true, confidence, reasoning) or None
        pass
```

#### Adjusting Risk Parameters

Edit the `Config` class (line ~242):
- `min_edge`: Minimum edge to trade (default 0.05 = 5%)
- `min_ev_per_dollar`: Minimum ROI (default 0.08 = 8%)
- `kelly_fraction`: Kelly fraction (default 0.25 = quarter-Kelly)
- `max_single_position_pct`: Max % of bankroll per position (default 0.07 = 7%)
- `max_total_exposure_pct`: Max total capital at risk (default 0.50 = 50%)

Can override via CLI:
```bash
python3 phase1_bot.py --scan --min-edge 0.03 --bankroll 1000
```

#### Querying the Database

The database is at `/data/polybot_trades.db` inside the Docker container.

```bash
# Access from Docker
docker exec polymarket-bot sqlite3 /data/polybot_trades.db "SELECT * FROM signals LIMIT 10;"

# Tables
docker exec polymarket-bot sqlite3 /data/polybot_trades.db ".tables"
# Output: forecasts  paper_trades  resolutions  signals

# Useful queries
docker exec polymarket-bot sqlite3 /data/polybot_trades.db "
  SELECT source, COUNT(*), AVG(brier_score)
  FROM forecasts
  WHERE resolved = 1
  GROUP BY source;
"
```

#### Debugging Signal Rejections

```bash
# Run with debug logging
python3 phase1_bot.py --scan --debug

# Check signals table for rejection reasons
docker exec polymarket-bot sqlite3 /data/polybot_trades.db "
  SELECT question, edge, ev_per_dollar, approved, rejection_reason
  FROM signals
  ORDER BY timestamp DESC
  LIMIT 20;
"
```

---

## Important Patterns & Conventions

### Error Handling

- All API calls have try/except blocks
- Failed API calls return None and log warnings
- Bot continues running even if individual markets fail
- Never crash the main loop

### Logging

- Use module-specific loggers: `logging.getLogger("ModuleName")`
- Log levels:
  - DEBUG: Verbose details, market-by-market processing
  - INFO: Key events (trades, signals, cycle summaries)
  - WARNING: Recoverable errors, rejected signals
  - ERROR: Failed API calls, exceptions

### Code Style

- Dataclasses for data models (Market, Signal, etc.)
- Type hints where practical
- Docstrings for all classes and complex functions
- Keep functions focused (single responsibility)

### Configuration

- **Never hardcode API keys or private keys**
- Always use environment variables
- Provide sensible defaults in Config class
- Allow CLI overrides for testing

---

## Testing & Validation

### Before Deploying Changes

1. **Syntax check**: `python3 -m py_compile phase1_bot.py`
2. **Test scan**: `python3 phase1_bot.py --scan --debug`
3. **Check database**: Verify signals are logged correctly
4. **Monitor first cycle**: Watch Docker logs after deployment

### Regression Testing

After major changes, verify:
- Paper trading still works: `python3 phase1_bot.py --scan`
- Report generation works: `python3 phase1_bot.py --report`
- Brier score works: `python3 phase1_bot.py --brier`
- All model tests pass:
  - `python3 phase1_bot.py --test-weather`
  - `python3 phase1_bot.py --test-crypto`
  - `python3 phase1_bot.py --test-sports`

---

## Docker Deployment

### Current Setup

- **Container**: `polymarket-bot` (runs 24/7 on NAS)
- **Volume**: `polybot-data` → `/data/` (persistent SQLite database)
- **Process**: Runs as root inside container
- **Command**: `--loop --interval 300 --min-edge 0.03 --db /data/polybot_trades.db`

### Accessing the Container

```bash
# View logs
docker logs polymarket-bot --tail 100 --follow

# Execute commands inside container
docker exec polymarket-bot python3 phase1_bot.py --report --db /data/polybot_trades.db

# Access shell (for debugging)
docker exec -it polymarket-bot /bin/bash

# Check process
ps aux | grep phase1_bot
```

### Updating the Bot

```bash
cd /home/dias/polymarket-bot
docker-compose down
docker-compose build  # Only needed if dependencies changed
docker-compose up -d
docker logs -f polymarket-bot
```

### Environment Variables (via docker-compose.yml)

```yaml
environment:
  - POLYMARKET_PRIVATE_KEY=        # Empty = paper trading
  - POLYMARKET_BANKROLL=10000      # Starting capital
  - ODDS_API_KEY=                  # For sports model (optional)
```

---

## Live Trading Specifics ⚠️

### When Live Trading is ENABLED

Requires:
- `POLYMARKET_PRIVATE_KEY` set
- `--live` flag in command
- `py-clob-client` installed

Bot behavior changes:
- Uses `LiveTrader` instead of `PaperTrader`
- Places real limit orders on Polymarket
- Monitors order fills every cycle
- Cancels stale orders after 5 minutes
- Logs show `🔴 PLACING LIVE ORDER` and `✅ ORDER FILLED`

### Safety Checks Before Live Trading

User MUST verify:
1. Paper trading P&L is positive for 4+ weeks
2. Brier score beats market baseline
3. Win rate above 50%
4. Starting with small bankroll ($100-500)
5. Private key is secure (never in git)

### Monitoring Live Trading

```bash
# Watch for order placements and fills
docker logs -f polymarket-bot | grep "LIVE ORDER\|FILLED\|ERROR"

# Check daily performance
docker exec polymarket-bot python3 phase1_bot.py --report --db /data/polybot_trades.db

# Check weekly calibration
docker exec polymarket-bot python3 phase1_bot.py --brier --db /data/polybot_trades.db
```

### Emergency Stop

```bash
docker-compose down
```

Or edit docker-compose.yml to remove `--live` flag and restart.

---

## Troubleshooting Guide

### "No markets fetched"

- Check Gamma API is reachable: `curl https://gamma-api.polymarket.com/markets`
- Check rate limiting: Increase `--interval`
- Check logs for API errors

### "0 tradeable signals"

Normal if:
- Markets are efficient (no mispriced opportunities)
- `min_edge` threshold is too high

Try:
- Lower threshold: `--min-edge 0.03`
- Check if probability models are working: `--test-weather`

### "Live trading requires py-clob-client"

```bash
pip install py-clob-client
```

### "Live trading requires POLYMARKET_PRIVATE_KEY"

Set in docker-compose.yml or:
```bash
export POLYMARKET_PRIVATE_KEY="0xYourKey"
```

### "Order submission failed"

Check:
- Wallet has USDC balance on Polygon
- Wallet has MATIC for gas fees
- Order size is reasonable ($1-$10,000)
- Polygon network is not congested

### Performance Worse Than Paper Trading

Expected differences:
- Fill rate: 70-90% (maker-only orders)
- Execution time: 1-5 minutes (vs instant)
- Slippage: Minimal (actually better due to maker rebate)

If significantly worse:
- Check Brier score is still good
- Increase `min_edge` threshold
- Verify markets are liquid (>$10k volume)

---

## Database Schema

### signals
- `id`: Auto-increment
- `timestamp`: When signal was detected
- `market_id`, `question`, `side`, `edge`, `ev_per_dollar`
- `approved`: Boolean (passed risk checks)
- `rejection_reason`: Why signal was rejected

### paper_trades
- `id`: Auto-increment
- `signal_id`: Foreign key to signals
- `timestamp`, `market_id`, `question`, `side`
- `entry_price`, `shares`, `size_usd`
- `p_true`: Our estimated probability
- `pnl`: Realized P&L (NULL until closed)

### forecasts
- Used for Brier score tracking
- `market_id`, `question`, `p_true`, `market_price`, `source`
- `outcome`: NULL until resolved (0 or 1)
- `resolved`: Boolean
- `brier_score`: (p_true - outcome)²

### resolutions
- Tracks when markets are resolved
- Links `market_id` to final outcome

---

## Key Files Reference

| File | Purpose | When to Edit |
|------|---------|--------------|
| `phase1_bot.py` | Main bot code | Adding features, fixing bugs, new models |
| `docker-compose.yml` | Deployment config | Changing env vars, command args |
| `Dockerfile` | Container build | Adding system dependencies |
| `GETTING_STARTED.md` | Paper trading guide | Never (user-facing docs) |
| `LIVE_TRADING_GUIDE.md` | Live trading setup | Adding safety info, troubleshooting |
| `QUICK_START_LIVE.md` | Quick reference | Updating commands, adding tips |
| `CLAUDE.md` | This file | Updating workflows, architecture changes |

---

## Best Practices for Claude Code

### When User Asks to...

**"Add a new feature"**
1. Read relevant sections of phase1_bot.py first
2. Understand existing patterns before modifying
3. Test changes with `--scan --debug` before deploying
4. Update this CLAUDE.md if workflow changes

**"Fix a bug"**
1. Check Docker logs: `docker logs polymarket-bot --tail 200`
2. Reproduce locally if possible
3. Add error handling if bug is in API calls
4. Test fix with `--scan` before deploying

**"Check performance"**
1. Run: `docker exec polymarket-bot python3 phase1_bot.py --report --db /data/polybot_trades.db`
2. Check Brier score: `docker exec polymarket-bot python3 phase1_bot.py --brier --db /data/polybot_trades.db`
3. Query database for specific metrics

**"Deploy changes"**
1. Verify syntax: `python3 -m py_compile phase1_bot.py`
2. Run: `docker-compose down && docker-compose up -d`
3. Monitor: `docker logs -f polymarket-bot`
4. Verify first cycle completes successfully

**"Understand how X works"**
1. Use Grep to find relevant code: `grep -n "class X\|def X" phase1_bot.py`
2. Read with context (50-100 lines)
3. Check for related functions/classes
4. Explain data flow, not just code structure

### What NOT to Do

- ❌ Don't modify code without reading it first
- ❌ Don't deploy to Docker without local testing
- ❌ Don't hardcode API keys or secrets
- ❌ Don't break backward compatibility (paper trading must always work)
- ❌ Don't suggest changes without understanding risk implications
- ❌ Don't recommend live trading unless user has validated paper trading results

---

## User Preferences

- **Deployment**: Docker on NAS (not local machine)
- **Database**: SQLite in Docker volume `/data/polybot_trades.db`
- **Trading mode**: Currently paper trading, moving to live trading
- **Risk tolerance**: Conservative (starting with $100-500 for live)
- **Communication style**: Technical, concise, actionable

---

## Future Enhancements (Ideas for Next Phases)

- Phase 4: Monitoring & alerts (Telegram, Discord webhooks)
- Position closing strategies (take profit, stop loss)
- Multi-market arbitrage detection
- Real-time websocket streaming (already has imports)
- Backtesting framework using historical data
- Portfolio rebalancing logic
- More sophisticated probability models (ML, ensemble methods)

---

## Contact & Support

- **User**: dias
- **Project Location**: `/home/dias/polymarket-bot`
- **Issues**: Not specified (this is a personal project)
- **Documentation**: GETTING_STARTED.md, LIVE_TRADING_GUIDE.md, QUICK_START_LIVE.md

---

## Version History

- **v1.0** (Phase 1): Paper trading with basic heuristics
- **v1.1** (Phase 2): Weather, crypto, sports probability models
- **v2.0** (Phase 3): Live trading with LiveTrader class ← **CURRENT**

---

## Quick Command Reference

```bash
# Paper trading
python3 phase1_bot.py --scan
python3 phase1_bot.py --loop --interval 120

# Live trading
python3 phase1_bot.py --live --scan --bankroll 500
python3 phase1_bot.py --live --loop --interval 300 --min-edge 0.04

# Reports
python3 phase1_bot.py --report
python3 phase1_bot.py --brier

# Testing
python3 phase1_bot.py --test-weather
python3 phase1_bot.py --test-crypto
python3 phase1_bot.py --test-sports

# Docker
docker-compose up -d
docker-compose down
docker logs -f polymarket-bot
docker exec polymarket-bot python3 phase1_bot.py --report --db /data/polybot_trades.db
```

---

**Last Updated**: 2025-04-01
**Bot Status**: Production-ready (Phase 3 - Live Trading)
**Deployment**: Docker on NAS, running 24/7
