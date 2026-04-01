# Quick Start: Live Trading

## TL;DR - Minimum Steps to Go Live

### 1. Install dependencies
```bash
pip install py-clob-client
```

### 2. Set your private key
```bash
export POLYMARKET_PRIVATE_KEY="0xYourKeyHere"
```

### 3. Test connection (paper mode)
```bash
python3 phase1_bot.py --scan --bankroll 500
```

### 4. Enable live trading
```bash
python3 phase1_bot.py --live --loop --interval 300 --bankroll 500 --min-edge 0.04
```

### 5. Monitor
```bash
# Watch logs
docker logs -f polymarket-bot

# Check performance
python3 phase1_bot.py --report

# Check calibration
python3 phase1_bot.py --brier
```

---

## Docker Setup (Recommended)

Edit `docker-compose.yml`:

```yaml
environment:
  - POLYMARKET_PRIVATE_KEY=0xYourKey
  - POLYMARKET_BANKROLL=500

command: ["--live", "--loop", "--interval", "300", "--min-edge", "0.04", "--db", "/data/polybot_trades.db"]
```

Then:
```bash
docker-compose down
docker-compose up -d
docker logs -f polymarket-bot
```

---

## Safety Checklist

Before going live:
- [ ] Paper trading P&L is **positive** for 4+ weeks
- [ ] Brier score **beats the market baseline**
- [ ] Win rate **above 50%**
- [ ] Starting bankroll is **small** ($100-500)
- [ ] Private key is **stored securely**
- [ ] Understand **you can lose all capital**

---

## Key Commands

| Command | Description |
|---------|-------------|
| `--live` | Enable live trading (⚠️ real money) |
| `--scan` | Run one scan cycle |
| `--loop` | Run continuously |
| `--interval 300` | Scan every 300 seconds (5 min) |
| `--bankroll 500` | Set starting bankroll to $500 |
| `--min-edge 0.04` | Require 4% minimum edge |
| `--report` | Show performance report |
| `--brier` | Show forecast calibration |

---

## What to Expect

**Live trading differences from paper trading:**

| Aspect | Paper Trading | Live Trading |
|--------|---------------|--------------|
| Orders | Fill instantly at market price | Fill when limit price is met (1-5 min) |
| Fill rate | 100% | 70-90% |
| Execution | Immediate | Delayed (maker-only) |
| Prices | Market price | Slightly better (maker rebate) |
| Risk | None | Real money at risk |

---

## Monitoring Guide

### Daily
```bash
docker logs polymarket-bot --tail 100 --since 24h
docker exec polymarket-bot python3 phase1_bot.py --report --db /data/polybot_trades.db
```

### Weekly
```bash
docker exec polymarket-bot python3 phase1_bot.py --brier --db /data/polybot_trades.db
```

### What to watch for
- ✅ Orders filling (not all will fill - that's normal)
- ✅ Positive P&L trend
- ✅ Win rate staying above 50%
- ✅ Brier score staying positive
- ⚠️ Daily drawdown exceeding -10%
- ⚠️ Multiple days of losses
- ⚠️ Win rate dropping below 45%

---

## Emergency Stop

```bash
# Stop the bot
docker-compose down

# Or switch back to paper mode
# (remove --live flag from docker-compose.yml)
docker-compose restart
```

---

## Scaling Schedule

| Timeframe | Bankroll | Min Edge | Notes |
|-----------|----------|----------|-------|
| Week 1-2 | $100-500 | 0.04-0.05 | Validate fills, monitor closely |
| Week 3-4 | $500 | 0.04 | Compare to paper trading |
| Month 2 | $500-1000 | 0.03-0.04 | Scale if profitable |
| Month 3+ | Scale gradually | 0.03-0.04 | Proven track record only |

---

## Read the Full Guide

For complete details, safety considerations, and troubleshooting:

👉 **[LIVE_TRADING_GUIDE.md](LIVE_TRADING_GUIDE.md)**
