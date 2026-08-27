# 500/0 Bot — Infinite Draft Automation

Automatically plays 500-0.com to maximize 500-chase success.

## Quick Start

```powershell
# Install (one-time)
python -m pip install playwright requests
python -m playwright install chromium

# Run analysis (fetch latest leaderboard data)
python analysis\analyze_leaderboard.py

# Run the bot
python bot_500.py
```

## Files

| File | What it does |
|------|-------------|
| `bot_500.py` | **Main bot** — infinite loop, spins/drafts/simulates |
| `analysis\analyze_leaderboard.py` | Fetches 500 Club top-250 & runs frequency analysis |
| `analysis\analysis_results.json` | Auto-generated analysis output |
| `data\leaderboard_raw.json` | Sample leaderboard data (top 20) |
| `run_log.json` | Auto-generated: log of every bot run |

## Strategy (from live analysis of 100 winning teams)

### Must-Have Players (keep spinning until squad has ≥1 of these)

| Player | Role | Freq |
|--------|------|------|
| AB de Villiers | WK | **86%** |
| Viv Richards | BAT | 77% |
| Muttiah Muralitharan | BWL | 65% |
| Virat Kohli | BAT | 53% |
| Sachin Tendulkar | BAT | 52% |
| Heinrich Klaasen | WK | 50% |
| Jos Buttler | WK | 43% |
| Shane Warne | BWL | 42% |

### Optimal Draft Order

```
Slot 1  → Rohit Sharma / Travis Head / Sachin Tendulkar
Slot 2  → Virat Kohli / Sachin Tendulkar / Chris Gayle
Slot 3  → Virat Kohli / Viv Richards / AB de Villiers
Slot 4  → Viv Richards / AB de Villiers / Brian Lara
Slot 5  → AB de Villiers / Heinrich Klaasen / Jos Buttler
Slot 6  → Heinrich Klaasen / Jos Buttler / Nicholas Pooran
Slot 7  → Shahid Afridi / Lance Klusener / Glenn Maxwell
Slot 8  → Wasim Akram / Shane Warne / Malcolm Marshall
Slot 9  → Shane Warne / Rashid Khan / Malcolm Marshall
Slot 10 → Muttiah Muralitharan / Malcolm Marshall / Shane Warne
Slot 11 → Muttiah Muralitharan / Mitchell Starc / Lasith Malinga
```

### Role Composition of Winning Teams

- **25%** → 1 AR + 4 BAT + 4 BWL + 2 WK  ← most common
- **23%** → 1 AR + 3 BAT + 4 BWL + 3 WK
- **10%** → 0 AR + 4 BAT + 4 BWL + 3 WK

### Fastest Chase Stats

- **World #1:** 216 balls (36.0 overs) — AutoPlayer
- **Average chase:** ~229.7 balls (~38.2 overs)
- **Slowest in top 100:** 234 balls (39.0 overs)

## Known Selectors (may need adjustment)

The React app renders player cards dynamically. If the bot can't find players,
open DevTools on 500-0.com and check the actual class names, then update
the selectors in `bot_500.py` → `get_squad_names()` and `click_player()`.
