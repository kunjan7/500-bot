"""
DEEP ANALYSIS of 500-0.com spin mechanism.
Extracts:
1. All squad data (vo array) with player ratings
2. The a6 seeded RNG function  
3. Full f6 simulator
4. The seed API response format
"""
import pathlib, re, sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

js = pathlib.Path('app.js').read_text(encoding='utf-8', errors='replace')

# ── 1. Extract full vo squad array ────────────────────────────────────────────
print("=== EXTRACTING vo SQUAD ARRAY ===")
m = js.find('var vo=[')
if m < 0:
    m = js.find('vo=[{id:')
end = m
depth = 0
for i, ch in enumerate(js[m:], m):
    if ch == '[': depth += 1
    elif ch == ']': 
        depth -= 1
        if depth == 0:
            end = i + 1
            break

vo_str = js[m:end]
print(f"vo array: {len(vo_str)} chars, starts: {vo_str[:80]}")
pathlib.Path('vo_squads.js').write_text(vo_str, encoding='utf-8')
print("Saved to vo_squads.js")

# ── 2. Count squads and players ───────────────────────────────────────────────
squad_ids = re.findall(r'id:"([^"]+)"', vo_str)
print(f"\nTotal squads: {len(squad_ids)}")
for sid in squad_ids:
    print(f"  - {sid}")

# ── 3. Find a6 (seeded RNG) ───────────────────────────────────────────────────
print("\n=== SEEDED RNG (a6) ===")
m2 = js.find('function a6(')
if m2 < 0: m2 = js.find('a6=t=>')
if m2 < 0: m2 = js.find('a6=function')
print(js[m2:m2+500])

# ── 4. Find Ot() - the random() wrapper used in simulation ───────────────────
print("\n=== Ot() FUNCTION (RNG wrapper used in f6) ===")
m3 = js.find('let Ot=')
if m3 < 0: m3 = js.find('var Ot=')
if m3 < 0: m3 = js.find(',Ot=')
print(js[max(0,m3-20):m3+200])

# ── 5. Find k1 (the RNG state variable) ──────────────────────────────────────
print("\n=== k1 STATE VARIABLE ===")
for pat in ['let k1=', 'var k1=', 'k1=Math']:
    m4 = js.find(pat)
    if m4 >= 0:
        print(js[max(0,m4-20):m4+200])
        break

# ── 6. Full f6 simulator extraction ──────────────────────────────────────────
print("\n=== f6 SIMULATOR (first 2000 chars) ===")
m5 = js.find('function f6(')
end5 = m5
depth = 0
started = False
for i, ch in enumerate(js[m5:], m5):
    if ch == '{': depth += 1; started = True
    elif ch == '}':
        depth -= 1
        if started and depth == 0:
            end5 = i + 1
            break

f6_str = js[m5:end5]
print(f"f6 length: {len(f6_str)} chars")
print(f6_str[:2000])
pathlib.Path('f6_sim.js').write_text(f6_str, encoding='utf-8')
print("\nSaved to f6_sim.js")

# ── 7. Find n6() - the score calculation (target/win check) ──────────────────
print("\n=== n6() SCORE CHECKER ===")
m6 = js.find('function n6(')
print(js[m6:m6+800])

# ── 8. Understand submit payload validation ───────────────────────────────────
print("\n=== SUBMIT PAYLOAD ===")
m7 = js.find('/submit",{method')
print(js[max(0,m7-200):m7+400])
