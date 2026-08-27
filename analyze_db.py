import json, sys, itertools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

db = json.load(open(r'C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot\live\player_db.json', encoding='utf-8'))

# Flatten unique players (same player may appear in multiple squads with same/diff ratings?)
players = {}
for t in db:
    for p in t['players']:
        key = p['n']
        if key not in players:
            players[key] = dict(p)
            players[key]['teams'] = [t['id']]
        else:
            if (players[key]['b'], players[key]['p'], players[key]['bl'], tuple(players[key]['r'])) != (p['b'], p['p'], p['bl'], tuple(p['r'])):
                print("DIFF RATINGS:", key, players[key]['b'], players[key]['p'], players[key]['bl'], players[key]['r'],
                      "VS", p['b'], p['p'], p['bl'], p['r'], "in", t['id'])
            players[key]['teams'].append(t['id'])

print("\nUNIQUE PLAYERS:", len(players))

def show(label, lst):
    print("\n=== %s ===" % label)
    for p in lst[:25]:
        print(f"  {p['n']:24s} r={p['r'][0]}-{p['r'][1]}  b={p['b']} p={p['p']} bl={p['bl']} wk={int(p['wk'])} ar={int(p['ar'])} teams={len(set(p['teams']))}")

# Keepers sorted by bat+pow
keepers = sorted([p for p in players.values() if p['wk']], key=lambda x: -(x['b']+x['p']))
show("KEEPERS by BAT+POW", keepers)

# Top POW non-keeper
nonwk = sorted([p for p in players.values() if not p['wk']], key=lambda x: -(x['b']+x['p']))
show("NON-WK BATTERS by BAT+POW", nonwk)

# Bowlers by BWL
bowlers = sorted([p for p in players.values() if p['bl'] >= 70], key=lambda x: -x['bl'])
show("BOWLERS by BWL (>=70)", bowlers)

# ARs
ars = sorted([p for p in players.values() if p['ar']], key=lambda x: -(x['b']+x['bl']))
show("ALL-ROUNDERS", ars)

json.dump(list(players.values()), open(r'C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot\live\players_unique.json', 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
