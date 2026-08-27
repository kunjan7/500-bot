"""
Analyze 500-0.com JavaScript to find:
1. The seed/RNG mechanism 
2. The squad selection logic
3. The simulation scoring engine
4. Whether we can override Math.random() to control spins
"""
import pathlib, re, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

js = pathlib.Path('app.js').read_text(encoding='utf-8', errors='replace')

def show(label, txt, n=600):
    print(f"\n{'='*70}")
    print(f"  {label}")
    print('='*70)
    print(txt[:n])

# 1. Find f6 - the main simulate/score function that uses the seed
m = js.find('function f6(')
if m < 0: m = js.find(',f6(')
if m < 0: m = js.find('f6=')
show("f6 FUNCTION (seed-based simulator)", js[m:m+1000])

# 2. Find the seeding formula - seed post-fetch
m2 = js.find('Dt.seed')
show("SEED USAGE + f6 call", js[max(0,m2-50):m2+800])

# 3. API base URL
for pat in ['const Fn=', 'var Fn=', 'let Fn=']:
    m3 = js.find(pat)
    if m3 >= 0:
        show("API BASE URL (Fn)", js[m3:m3+200])
        break

# 4. Squad picker - find 'vo' list (reel squads)
m4 = js.find('vo[Math.floor')
show("SPIN REEL PICKER (vo)", js[max(0,m4-500):m4+200])

# 5. Seeded RNG - look for mulberry/xorshift/lcg patterns
for seed_pat in ['mulberry', 'xorshift', 'lcg', 'xoshiro', 'pcg', 'splitmix', 'uint32', '>>>']:
    pos = js.find(seed_pat)
    if pos >= 0:
        show(f"SEEDED RNG ({seed_pat})", js[max(0,pos-100):pos+300])

# 6. Find the squad/player data arrays
# Look for arrays with player names
era_positions = []
for era in ['1970s', '1980s', '1990s', '2000s', '2010s', '2020s']:
    pos = 0
    while True:
        pos = js.find(era, pos)
        if pos < 0: break
        era_positions.append((pos, era))
        pos += 1

era_positions.sort()
print(f"\n{'='*70}")
print(f"  ERA REFERENCES ({len(era_positions)} total)")
print('='*70)
for pos, era in era_positions[:10]:
    print(f"  [{pos}] {era}: ...{js[max(0,pos-60):pos+100]}...")

# 7. Find submit endpoint to understand what's validated server-side
m5 = js.find('/submit')
show("SUBMIT ENDPOINT + PAYLOAD", js[max(0,m5-100):m5+400])

# 8. Find seed endpoint  
m6 = js.find('/seed')
show("SEED ENDPOINT", js[max(0,m6-100):m6+400])

# 9. Count Math.random() calls
rand_calls = re.findall(r'Math\.random\(\)', js)
print(f"\nTotal Math.random() calls: {len(rand_calls)}")

# 10. Find the scoring/simulation logic around 'runs' 
m7 = js.find('runs:')
show("RUNS/SCORE DATA STRUCTURE", js[max(0,m7-50):m7+400])
