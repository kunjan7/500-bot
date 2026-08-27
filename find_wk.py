import pathlib, re, sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
js = pathlib.Path('vo_squads.js').read_text(encoding='utf-8', errors='replace')

# Find WK entries - must have wk:true flag
wk = re.findall(r'\{n:"([^"]+)",r:\[(\d+),(\d+)\],b:(\d+),p:(\d+),bl:(\d+),wk:true\}', js)
print(f"WK players found: {len(wk)}")
for p in sorted(wk, key=lambda x: int(x[4])*0.6+int(x[3])*0.4, reverse=True):
    score = int(x[4])*0.6+int(x[3])*0.4
    print(f"  {p[0]:28} slots {p[1]}-{p[2]}  BAT={p[3]} POW={p[4]} BWL={p[5]}")

# Find WHICH squad each WK belongs to
print("\n--- WK by squad ---")
squad_blocks = re.split(r'(?=\{id:")', js)
for block in squad_blocks:
    sid_m = re.search(r'id:"([^"]+)"', block)
    if not sid_m: continue
    sid = sid_m.group(1)
    wk_in = re.findall(r'\{n:"([^"]+)",r:\[(\d+),(\d+)\],b:(\d+),p:(\d+),bl:(\d+),wk:true\}', block)
    for w in wk_in:
        print(f"  [{sid}] {w[0]:25} BAT={w[3]} POW={w[4]}")

# Now find the BEST team from same-squad constraint isn't needed (game allows any combination)
# Extract all players with full data
print("\n--- Best combos for sub-35-over chase ---")
all_players = []
for block in squad_blocks:
    sid_m = re.search(r'id:"([^"]+)"', block)
    name_m = re.search(r'name:"([^"]+)"', block)
    season_m = re.search(r'season:"([^"]+)"', block)
    if not sid_m: continue
    sid = sid_m.group(1)
    sname = name_m.group(1) if name_m else ""
    season = season_m.group(1) if season_m else ""
    pats = re.findall(r'\{n:"([^"]+)",r:\[(\d+),(\d+)\],b:(\d+),p:(\d+),bl:(\d+)(,wk:true)?\}', block)
    for pt in pats:
        all_players.append({
            'name': pt[0], 'lo': int(pt[1]), 'hi': int(pt[2]),
            'b': int(pt[3]), 'p': int(pt[4]), 'bl': int(pt[5]),
            'wk': bool(pt[6]), 'squad': sid, 'squad_label': f"{sname} {season}"
        })

# Find squads that have the best SINGLE player to target during spin
# We want to force spins to bring squads with specific elite players
print("\n=== SQUADS WITH THE MOST ELITE PLAYERS ===")
squad_value = {}
for p in all_players:
    sid = p['squad']
    if sid not in squad_value:
        squad_value[sid] = {'sid': sid, 'label': p['squad_label'], 'top_bat': 0, 'top_pow': 0, 'top_bwl': 0, 'wk_pow': 0, 'players': []}
    sq = squad_value[sid]
    sq['players'].append(p)
    if p['lo'] <= 7:
        sq['top_pow'] = max(sq['top_pow'], p['p'])
        sq['top_bat'] = max(sq['top_bat'], p['b'])
    if p['hi'] >= 8:
        sq['top_bwl'] = max(sq['top_bwl'], p['bl'])
    if p['wk']:
        sq['wk_pow'] = max(sq['wk_pow'], p['p'])

# Score each squad by value it adds
for sid, sq in squad_value.items():
    sq['score'] = sq['top_pow'] * 0.5 + sq['top_bat'] * 0.2 + sq['top_bwl'] * 0.2 + sq['wk_pow'] * 0.1

ranked = sorted(squad_value.values(), key=lambda x: x['score'], reverse=True)
print(f"{'Rank':4} {'Squad':30} {'MAX_POW':8} {'MAX_BAT':8} {'MAX_BWL':8} {'WK_POW':7}")
print("-"*70)
for i, sq in enumerate(ranked[:20], 1):
    print(f"{i:4} {sq['label']:30} {sq['top_pow']:8} {sq['top_bat']:8} {sq['top_bwl']:8} {sq['wk_pow']:7}")

print("\n=== TOP 10 SQUADS TO TARGET IN SPIN INTERCEPTION ===")
top10 = [sq['sid'] for sq in ranked[:10]]
print(json.dumps(top10, indent=2))
pathlib.Path('top_squads.json').write_text(json.dumps(top10), encoding='utf-8')
