# Polymarket Trading Bot

A fully-automated prediction market trading bot for Polymarket that identifies mispriced opportunities using custom probability models and Kelly criterion position sizing.

**Current Status**: ✅ Phase 3 Complete - Live Trading Ready

---

## Features

- 🤖 **Automated Market Scanning** - Monitors all active Polymarket markets
- 📊 **Custom Probability Models**
  - Weather forecasts (NOAA/NWS API)
  - Crypto prices (Binance + Deribit options)
  - Sports betting odds (The Odds API)
  - Heuristic fallbacks for other markets
- 💰 **Kelly Criterion Sizing** - Optimal position sizing with quarter-Kelly
- 🛡️ **Risk Management** - Position limits, exposure caps, drawdown protection
- 📈 **Performance Tracking** - SQLite database with Brier score calibration
- 🔴 **Live Trading** - Real execution via Polymarket CLOB API (Phase 3)
- 📝 **Paper Trading** - Safe backtesting mode (default)

---

## Quick Start

### Paper Trading (Safe Mode)
```bash
# Install dependencies
pip install requests

# Run a single scan
python3 phase1_bot.py --scan

# Run continuously
python3 phase1_bot.py --loop --interval 120

# Check performance
python3 phase1_bot.py --report
python3 phase1_bot.py --brier
```

### Live Trading ⚠️
```bash
# Install live trading client
pip install py-clob-client

# Set credentials
export POLYMARKET_PRIVATE_KEY="0xYourKey"

# Start live trading with small bankroll
python3 phase1_bot.py --live --loop --interval 300 --bankroll 500
```

**⚠️ Read [LIVE_TRADING_GUIDE.md](LIVE_TRADING_GUIDE.md) before enabling live trading!**

---

## Documentation

| Document | Purpose | For Who |
|----------|---------|---------|
| [GETTING_STARTED.md](GETTING_STARTED.md) | Initial setup, paper trading | New users |
| [LIVE_TRADING_GUIDE.md](LIVE_TRADING_GUIDE.md) | Complete live trading setup | Users ready to go live |
| [QUICK_START_LIVE.md](QUICK_START_LIVE.md) | Quick reference card | Live traders |
| [CLAUDE.md](CLAUDE.md) | Development guide, architecture | Developers / Claude Code |

---

## Architecture

**Monolithic Design** - All code in `phase1_bot.py` (~3200 lines)

**Core Modules**:
1. **MarketFetcher** - Fetches markets and prices from Polymarket APIs
2. **ProbabilityEstimator** - Estimates true probabilities using custom models
3. **EdgeScanner** - Identifies mispriced opportunities
4. **RiskManager** - Enforces position limits and risk rules
5. **PaperTrader** - Simulates trades (default mode)
6. **LiveTrader** - Executes real trades (requires `--live` flag)
7. **TradeDB** - Logs all activity to SQLite database

**Data Flow**:
```
Polymarket APIs → MarketFetcher → ProbabilityEstimator → EdgeScanner
                                                            ↓
                                                       RiskManager
                                                            ↓
                                                   PaperTrader/LiveTrader
                                                            ↓
                                                        TradeDB
```

---

## Deployment

### Docker (Recommended)
```bash
# Build and run
docker-compose up -d

# View logs
docker logs -f polymarket-bot

# Check performance
docker exec polymarket-bot python3 phase1_bot.py --report --db /data/polybot_trades.db
```

### Local
```bash
python3 phase1_bot.py --loop --interval 300 --db ~/polybot_trades.db
```

---

## Configuration

**Environment Variables**:
```bash
POLYMARKET_PRIVATE_KEY       # Required for live trading
POLYMARKET_BANKROLL=10000    # Starting capital
POLYMARKET_FUNDER_ADDRESS    # Optional (proxy wallets)
POLYMARKET_SIGNATURE_TYPE=0  # 0=EOA, 1=Magic
ODDS_API_KEY                 # Optional (for sports model)
```

**Command-Line Flags**:
```bash
--scan                   # Run one cycle
--loop                   # Run continuously
--live                   # Enable live trading ⚠️
--interval 300           # Seconds between scans
--min-edge 0.05          # Minimum edge threshold (5%)
--bankroll 10000         # Starting bankroll
--debug                  # Verbose logging
--db path/to/db.db       # Database location
--report                 # Show performance report
--brier                  # Show Brier score calibration
```

---

## Performance Tracking

### Metrics

- **Total P&L** - Realized profits/losses
- **Win Rate** - Percentage of profitable trades
- **Brier Score** - Forecast calibration (lower is better)
- **Skill Score** - Brier score vs market baseline (positive = beating market)

### Reports

```bash
# Overall performance
python3 phase1_bot.py --report

# Forecast calibration
python3 phase1_bot.py --brier

# Database queries
sqlite3 polybot_trades.db "SELECT * FROM signals WHERE approved=1 LIMIT 10"
```

---

## Safety Features

### Risk Management
- ✅ Kelly criterion position sizing (quarter-Kelly default)
- ✅ Maximum single position: 7% of bankroll
- ✅ Maximum total exposure: 50% of bankroll
- ✅ Maximum open positions: 10
- ✅ Daily drawdown limit: -10%

### Live Trading Safety
- ✅ Maker-only orders (no market orders)
- ✅ Stale order cancellation (5min timeout)
- ✅ Order fill monitoring
- ✅ Position tracking and reconciliation
- ✅ Comprehensive logging

---

## Development

### Project Structure
```
polymarket-bot/
├── phase1_bot.py           # Main bot (all code)
├── docker-compose.yml      # Docker deployment
├── Dockerfile              # Container build
├── CLAUDE.md               # Developer guide
├── GETTING_STARTED.md      # User guide (paper)
├── LIVE_TRADING_GUIDE.md   # User guide (live)
└── QUICK_START_LIVE.md     # Quick reference
```

### Testing
```bash
# Syntax check
python3 -m py_compile phase1_bot.py

# Test probability models
python3 phase1_bot.py --test-weather
python3 phase1_bot.py --test-crypto
python3 phase1_bot.py --test-sports

# Test full scan (paper mode)
python3 phase1_bot.py --scan --debug
```

### Contributing to the Bot

1. Read [CLAUDE.md](CLAUDE.md) for architecture and patterns
2. Make changes to `phase1_bot.py`
3. Test locally: `python3 phase1_bot.py --scan --debug`
4. Deploy: `docker-compose down && docker-compose up -d`
5. Monitor: `docker logs -f polymarket-bot`

---

## Troubleshooting

### Common Issues

**"No markets fetched"**
- Check internet connection
- Verify Polymarket APIs are reachable
- Increase scan interval to avoid rate limiting

**"0 tradeable signals"**
- Normal if markets are efficient
- Lower `--min-edge` threshold (e.g., `--min-edge 0.03`)
- Check if probability models are working (`--test-weather`)

**"Live trading requires py-clob-client"**
```bash
pip install py-clob-client
```

**"Order submission failed"**
- Check wallet has USDC on Polygon
- Check wallet has MATIC for gas
- Verify private key is correct
- Check Polygon network status

See [LIVE_TRADING_GUIDE.md](LIVE_TRADING_GUIDE.md) for complete troubleshooting guide.

---

## Probability Models

### Weather Model
- **Data Source**: NOAA/NWS API (free)
- **Accuracy**: 85-93% for 24-48h forecasts
- **Markets**: Temperature buckets, precipitation, weather events
- **Edge**: Polymarket often uses consumer weather apps vs official forecasts

### Crypto Model
- **Data Source**: Binance (spot), Deribit (options IV)
- **Method**: Black-Scholes for binary options pricing
- **Markets**: "Will BTC hit $X by date Y?"
- **Edge**: Options-implied probabilities vs Polymarket prices

### Sports Model
- **Data Source**: The Odds API (requires free API key)
- **Method**: Convert moneyline/spread odds to probabilities
- **Markets**: Game outcomes, player props
- **Edge**: Sportsbook consensus vs Polymarket recreational bettors

### Heuristic Fallback
- Fade extreme prices (>0.95 or <0.05)
- Structural arbitrage detection
- Confidence: Low (use as last resort)

---

## Roadmap

- [x] **Phase 1**: Paper trading, API integration, basic heuristics
- [x] **Phase 2**: Weather, crypto, sports probability models
- [x] **Phase 3**: Live trading with CLOB API
- [ ] **Phase 4**: Monitoring & alerts (Telegram, Discord)
- [ ] **Phase 5**: Position management (take profit, stop loss)
- [ ] **Phase 6**: Multi-market arbitrage, portfolio optimization

---

## Disclaimer

⚠️ **Important Disclaimers**:

- This software is provided "as is" without warranty of any kind
- Trading prediction markets involves substantial risk of loss
- Past performance (including paper trading) does not guarantee future results
- Most traders lose money - only trade with money you can afford to lose
- Always verify Polymarket's legality in your jurisdiction
- The authors are not responsible for any financial losses
- This is educational software, not financial advice

**Use at your own risk.**

---

## License

This is a personal project. All rights reserved.

---

## Contact

- **Issues**: See troubleshooting guides or review logs
- **Documentation**: See guides in repository
- **Development**: See [CLAUDE.md](CLAUDE.md)

---

**Version**: 2.0 (Phase 3 - Live Trading)
**Last Updated**: 2025-04-01
**Status**: Production Ready
