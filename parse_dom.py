import pathlib, re, sys

html = pathlib.Path('initial_dom.html').read_text(encoding='utf-8')
classes = re.findall(r'class="([^"]+)"', html)
keywords = ['player','squad','card','draft','slot','pick','name','spin','wheel','team','btn','button']
player_classes = [c for c in classes if any(k in c.lower() for k in keywords)]
print("=== Relevant CSS classes from initial DOM ===")
for c in sorted(set(player_classes))[:50]:
    print(f"  {c[:120]}")

# Also extract all text content
texts = re.findall(r'>([^<>]{3,50})<', html)
texts = [t.strip() for t in texts if t.strip() and re.match(r'^[A-Za-z]', t.strip())]
print("\n=== Text content (first 60 items) ===")
for t in texts[:60]:
    print(f"  {t}")
