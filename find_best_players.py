"""
Parse vo_squads.js to find the best players across all squads.
Identify dream team composition for fastest 500 chase.
"""
import pathlib, re, json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

js = pathlib.Path('vo_squads.js').read_text(encoding='utf-8', errors='replace')

# Parse all players: {n:"Name", r:[lo,hi], b:BAT, p:POW, bl:BWL}
players_raw = re.findall(
    r'\{n:"([^"]+)",r:\[(\d+),(\d+)\],b:(\d+),p:(\d+),bl:(\d+)(?:,wk:true)?\}',
    js
)

wk_names = set(re.findall(r'"([^"]+)"(?=.*?,wk:true)', js))

# Also find wk by role tag
squad_data = {}
squad_blocks = re.split(r'\{id:"', js)[1:]
for block in squad_blocks:
    sid_m = re.match(r'([^"]+)"', block)
    if not sid_m: continue
    sid = sid_m.group(1)
    name_m = re.search(r'name:"([^"]+)"', block)
    season_m = re.search(r'season:"([^"]+)"', block)
    sname = name_m.group(1) if name_m else ''
    season = season_m.group(1) if season_m else ''
    
    players = []
    pats = re.findall(
        r'\{n:"([^"]+)",r:\[(\d+),(\d+)\],b:(\d+),p:(\d+),bl:(\d+)(,wk:true)?\}',
        block
    )
    for p in pats:
        players.append({
            'name': p[0], 'lo': int(p[1]), 'hi': int(p[2]),
            'b': int(p[3]), 'p': int(p[4]), 'bl': int(p[5]),
            'wk': bool(p[6])
        })
    squad_data[sid] = {'name': sname, 'season': season, 'players': players}

print(f"Parsed {len(squad_data)} squads")

# ── FIND BEST BATTERS (slots 1-7): highest POW + BAT ─────────────────────────
all_batters = []
for sid, sq in squad_data.items():
    for p in sq['players']:
        if p['lo'] <= 7:  # can play in top 7
            all_batters.append({**p, 'squad': sid, 'squad_name': sq['name'], 'squad_season': sq['season']})

all_batters.sort(key=lambda x: x['p']*0.6 + x['b']*0.4, reverse=True)

print("\n🏆 TOP 30 BATTERS/WK (by POW*0.6 + BAT*0.4) for slots 1-7:")
print(f"{'Rank':4} {'Name':22} {'Squad':25} {'BAT':4} {'POW':4} {'BWL':4} {'WK':4} {'Slots':8}")
print("-"*80)
for i, p in enumerate(all_batters[:30], 1):
    wk_str = "WK" if p['wk'] else ""
    squad_str = f"{p['squad_name']} {p['squad_season']}"
    print(f"{i:4} {p['name']:22} {squad_str:25} {p['b']:4} {p['p']:4} {p['bl']:4} {wk_str:4} {p['lo']}-{p['hi']}")

# ── FIND BEST BOWLERS (slots 8-11): highest BWL ────────────────────────────
all_bowlers = []
for sid, sq in squad_data.items():
    for p in sq['players']:
        if p['hi'] >= 8 and p['bl'] >= 70:  # can play in bowler slots, and has bowling ability
            all_bowlers.append({**p, 'squad': sid, 'squad_name': sq['name'], 'squad_season': sq['season']})

all_bowlers.sort(key=lambda x: x['bl'], reverse=True)

print("\n\n🏆 TOP 25 BOWLERS (by BWL) for slots 8-11:")
print(f"{'Rank':4} {'Name':22} {'Squad':25} {'BWL':4} {'BAT':4} {'POW':4} {'Slots':8}")
print("-"*75)
for i, p in enumerate(all_bowlers[:25], 1):
    squad_str = f"{p['squad_name']} {p['squad_season']}"
    print(f"{i:4} {p['name']:22} {squad_str:25} {p['bl']:4} {p['b']:4} {p['p']:4} {p['lo']}-{p['hi']}")

# ── FIND BEST WK ──────────────────────────────────────────────────────────────
wk_players = [p for p in all_batters if p['wk']]
wk_players.sort(key=lambda x: x['p']*0.6 + x['b']*0.4, reverse=True)
print("\n\n🏆 TOP 15 WICKETKEEPERS (by POW+BAT):")
print(f"{'Rank':4} {'Name':22} {'Squad':25} {'BAT':4} {'POW':4} {'BWL':4} {'Slots':8}")
print("-"*75)
for i, p in enumerate(wk_players[:15], 1):
    squad_str = f"{p['squad_name']} {p['squad_season']}"
    print(f"{i:4} {p['name']:22} {squad_str:25} {p['b']:4} {p['p']:4} {p['bl']:4} {p['lo']}-{p['hi']}")

# ── OPTIMAL TEAM BUILDER ──────────────────────────────────────────────────────
# Build the theoretical BEST XI for fastest 500 chase
# Constraint: must pick 1 WK, need >=3 with BWL>=70

print("\n\n🚀 THEORETICAL OPTIMAL XI FOR FASTEST 500 CHASE:")
print("(Picks highest POW batters + elite bowlers from ANY squad)")
print()

# Slot assignments:
# 1-3: Highest POW openers/top-order batters
# 4-6: High BAT + POW middle order + WK
# 7: AR or high-POW late order
# 8-11: Highest BWL bowlers

# Best openers (slots 1-3)
top3 = [p for p in all_batters if p['lo'] <= 3][:10]
mid = [p for p in all_batters if p['lo'] <= 5 and p['hi'] >= 4][:15]
wk_top = wk_players[:5]
bowlers_top = [p for p in all_bowlers if p['lo'] >= 7][:10]

print("THEORETICAL BEST XI (no constraint on same squad):")
theoretical_xi = []
used_names = set()

# Slot 1-2: Highest POW batters who can open
openers = sorted([p for p in all_batters if p['lo'] <= 2 and p['name'] not in used_names],
                 key=lambda x: x['p'], reverse=True)
for p in openers[:2]:
    theoretical_xi.append((len(theoretical_xi)+1, p))
    used_names.add(p['name'])

# Slot 3-4: Next best batters
mid_bat = sorted([p for p in all_batters if p['lo'] <= 4 and p['name'] not in used_names],
                 key=lambda x: x['p']*0.6+x['b']*0.4, reverse=True)
for p in mid_bat[:2]:
    theoretical_xi.append((len(theoretical_xi)+1, p))
    used_names.add(p['name'])

# Slot 5-6: WK + one more batter
wk_avail = sorted([p for p in wk_players if p['lo'] <= 6 and p['name'] not in used_names],
                  key=lambda x: x['p'], reverse=True)
for p in wk_avail[:2]:
    theoretical_xi.append((len(theoretical_xi)+1, p))
    used_names.add(p['name'])

# Slot 7: AR or power hitter
ar = sorted([p for p in all_batters if p['lo'] <= 7 and p['hi'] >= 6 and p['name'] not in used_names],
            key=lambda x: x['p']+x['bl'], reverse=True)
if ar:
    theoretical_xi.append((7, ar[0]))
    used_names.add(ar[0]['name'])

# Slots 8-11: Best bowlers
top_bowlers = sorted([p for p in all_bowlers if p['name'] not in used_names and p['lo'] >= 7],
                     key=lambda x: x['bl'], reverse=True)
for p in top_bowlers[:4]:
    theoretical_xi.append((len(theoretical_xi)+1, p))
    used_names.add(p['name'])

print(f"\n{'Slot':5} {'Name':22} {'Squad':25} {'BAT':4} {'POW':4} {'BWL':4} {'Role':12}")
print("-"*80)
sum_bat = sum_pow = sum_bwl_4 = 0
for slot, p in theoretical_xi[:11]:
    role = "WK" if p['wk'] else ""
    if slot >= 8: sum_bwl_4 += p['bl']
    else: sum_bat += p['b']; sum_pow += p['p']
    squad_str = f"{p['squad_name']} {p['squad_season']}"
    print(f"{slot:5} {p['name']:22} {squad_str:25} {p['b']:4} {p['p']:4} {p['bl']:4} {role:12}")

n_top = min(7, len([x for x in theoretical_xi if x[0] <= 7]))
n_bot = len([x for x in theoretical_xi if x[0] >= 8])
avg_bat = sum_bat / max(1, n_top)
avg_pow = sum_pow / max(1, n_top)
avg_bwl = sum_bwl_4 / max(1, n_bot)
N_speed = max(0, (avg_bat-86) + (avg_pow-89) + (avg_bwl-90))
B_speed = min(1.0, N_speed/16.5)
exp_balls = round(282 - B_speed*72)

print(f"\nTeam stats: AVG_BAT={avg_bat:.1f} AVG_POW={avg_pow:.1f} AVG_BWL={avg_bwl:.1f}")
print(f"Speed formula: N={N_speed:.2f}, B={B_speed:.3f}")
print(f"Expected balls: {exp_balls} ({exp_balls/6:.1f} overs)")
print(f"\n✅ WIN chance: {'YES - 70% chance of exactly 500' if avg_bat>=86 and avg_pow>=89 and avg_bwl>=90 else 'NO - below threshold'}")

# Save results
results = {
    'top_batters': all_batters[:20],
    'top_bowlers': all_bowlers[:15],
    'top_wk': wk_players[:10],
    'theoretical_xi': [(s, p) for s, p in theoretical_xi[:11]]
}
pathlib.Path('best_players.json').write_text(
    json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
print("\nSaved to best_players.json")
