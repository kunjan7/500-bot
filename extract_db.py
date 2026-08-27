import re, sys, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

src = open(r'C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot\live\app.js', encoding='utf-8').read()

# 1) Extract all team definitions: {id:"...",name:"...",season:"...",tag:"...",players:[...]}
team_pat = re.compile(
    r'\{id:"(?P<id>[^"]+)",name:"(?P<name>[^"]+)",season:"(?P<season>[^"]+)",tag:"(?P<tag>[^"]*)",players:\[(?P<players>.*?)\]\}',
    re.S)
player_pat = re.compile(r'\{n:"(?P<n>[^"]+)",r:\[(?P<r0>\d+),(?P<r1>\d+)\],b:(?P<b>\d+),p:(?P<p>\d+),bl:(?P<bl>\d+)(?:,wk:(?P<wk>\d))?(?:,ar:(?P<ar>\d))?\}')

teams = []
for m in team_pat.finditer(src):
    players = []
    for pm in player_pat.finditer(m.group('players')):
        players.append({
            "n": pm.group('n'), "r": [int(pm.group('r0')), int(pm.group('r1'))],
            "b": int(pm.group('b')), "p": int(pm.group('p')), "bl": int(pm.group('bl')),
            "wk": bool(int(pm.group('wk') or 0)), "ar": bool(int(pm.group('ar') or 0)),
        })
    if players:
        teams.append({"id": m.group('id'), "name": m.group('name'),
                      "season": m.group('season'), "tag": m.group('tag'), "players": players})

print("TEAMS FOUND:", len(teams))
total_players = sum(len(t['players']) for t in teams)
print("TOTAL PLAYERS:", total_players)
for t in teams:
    print(f"  {t['id']:28s} {t['name']:18s} {t['season']:6s} tag={t['tag'][:30]:32s} players={len(t['players'])}")

json.dump(teams, open(r'C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot\live\player_db.json', 'w', encoding='utf-8'), indent=1, ensure_ascii=False)

# 2) Hunt the sim engine: search for ball-by-ball loop indicators
for kw in ['"OUT"', 'OUT!', 'SIX', 'FOUR', '.out=', 'out:!0', 'runs:', 'balls:', 'sr:', 'rr:', 'crr',
           'target:', 'won:', 'wonBy']:
    idxs = [m.start() for m in re.finditer(re.escape(kw), src)]
    print(kw, '->', len(idxs), idxs[:12])
