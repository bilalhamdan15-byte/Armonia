"""V3 : garde le wall_set V1 (qui fonctionnait), fixe corners + trou + toit + ajoute escaliers."""
import json, random, struct, gzip, base64, uuid
from collections import defaultdict, Counter


def load_vocab():
    with open('vocabulary.json') as f:
        return json.load(f)


def find_wall_ew_ns_v1(vocab):
    """V1 approach: identifie wall EW (le plus fréquent classé wall placé horizontalement)
    et wall NS séparément."""
    placements = vocab['placements']
    walls_by_guid = defaultdict(list)
    for p in placements:
        if 0 <= p['y'] < 3 and vocab['classified_assets'].get(p['guid'],{}).get('role') == 'wall':
            walls_by_guid[p['guid']].append(p)
    
    # Score each wall guid: is it more used horizontally (EW) or vertically (NS)?
    walls_ew, walls_ns = [], []
    for guid, pls in walls_by_guid.items():
        # For each placement look at neighbors of same guid
        # Simple heuristic: does this wall's rotations suggest EW or NS orientation?
        rots = Counter(p['rot'] for p in pls)
        dominant = rots.most_common(1)[0][0]
        # rot 0/12 = one axis, rot 6/18 = other axis (in most TS assets)
        # Empirically from screenshot V1 that worked: dominant_rot=6 was good
        info = {'guid': guid, 'count': len(pls), 'dominant_rot': dominant, 'rots': rots}
        # From V1 that worked: 82b03fd9 was EW, 55421077 was NS
        # We fallback to counting: assets with rot in {0,12} are EW, {6,18} are NS
        ew_count = rots.get(0,0) + rots.get(12,0)
        ns_count = rots.get(6,0) + rots.get(18,0)
        if ew_count > ns_count:
            walls_ew.append(info)
        else:
            walls_ns.append(info)
    
    ew = max(walls_ew, key=lambda w: w['count']) if walls_ew else None
    ns = max(walls_ns, key=lambda w: w['count']) if walls_ns else None
    return ew, ns


def find_stair(vocab):
    """Trouve un asset avec pattern d'escalier : plusieurs Y intermédiaires ou séquence de Y croissants."""
    placements = vocab['placements']
    by_guid = defaultdict(list)
    for p in placements:
        by_guid[p['guid']].append(p)
    
    candidates = []
    for guid, pls in by_guid.items():
        if len(pls) < 2 or len(pls) > 20: continue
        role = vocab['classified_assets'].get(guid, {}).get('role')
        if role in ('floor', 'roof', 'ground_outdoor'): continue  # exclude common
        # Check if Y values span multiple levels with intermediates
        ys = sorted(set(round(p['y'],2) for p in pls))
        # Escalier: au moins 2 Y différents, dont un intermédiaire (0.3-2.7)
        intermediate = [y for y in ys if 0.5 <= y <= 2.5]
        if len(intermediate) >= 1:
            candidates.append((guid, len(pls), intermediate, role))
    candidates.sort(key=lambda c: -c[1])
    return candidates[0][0] if candidates else None


def pick_floor_and_roof(vocab):
    floors = [(g, m) for g, m in vocab['classified_assets'].items() if m['role']=='floor']
    roofs = [(g, m) for g, m in vocab['classified_assets'].items() if m['role']=='roof']
    floor_guid = max(floors, key=lambda x: x[1]['count'])[0] if floors else None
    roof_guid = max(roofs, key=lambda x: x[1]['count'])[0] if roofs else None
    return floor_guid, roof_guid


def generate_v3(vocab, w, d, num_floors=2, seed=42):
    random.seed(seed)
    ew, ns = find_wall_ew_ns_v1(vocab)
    floor_guid, roof_guid = pick_floor_and_roof(vocab)
    stair_guid = find_stair(vocab)
    
    print(f"[V3] Wall EW: {ew['guid'][:8]} rot={ew['dominant_rot']}  Wall NS: {ns['guid'][:8]} rot={ns['dominant_rot']}")
    print(f"[V3] Floor: {floor_guid[:8]}   Roof: {roof_guid[:8]}   Stair: {stair_guid[:8] if stair_guid else '-'}")
    
    placements = []
    FLOOR_H = 3
    
    for floor in range(num_floors):
        y = floor * FLOOR_H
        
        # Sols intérieurs (tout l'intérieur, excluant le périmètre)
        for x in range(1, w-1):
            for z in range(1, d-1):
                placements.append({'guid': floor_guid, 'x': float(x), 'y': float(y), 'z': float(z), 'rot': 0})
        
        # PÉRIMÈTRE COMPLET — pas de trous
        # Nord (z=0): toute la ligne y compris coins
        for x in range(0, w):
            placements.append({'guid': ew['guid'], 'x': float(x), 'y': float(y), 'z': 0.0, 'rot': ew['dominant_rot']})
        # Sud (z=d-1): toute la ligne
        for x in range(0, w):
            placements.append({'guid': ew['guid'], 'x': float(x), 'y': float(y), 'z': float(d-1), 'rot': (ew['dominant_rot']+12)%24})
        # Ouest (x=0): interior (corners already covered by nord/sud)
        for z in range(1, d-1):
            placements.append({'guid': ns['guid'], 'x': 0.0, 'y': float(y), 'z': float(z), 'rot': ns['dominant_rot']})
        # Est (x=w-1)
        for z in range(1, d-1):
            placements.append({'guid': ns['guid'], 'x': float(w-1), 'y': float(y), 'z': float(z), 'rot': (ns['dominant_rot']+12)%24})
    
    # Toit — aligné exactement sur le bâtiment (pas de dépassement)
    if roof_guid:
        top_y = num_floors * FLOOR_H
        for x in range(0, w):
            for z in range(0, d):
                placements.append({'guid': roof_guid, 'x': float(x), 'y': float(top_y), 'z': float(z), 'rot': 0})
    
    # Escalier — au milieu du bâtiment, montant à chaque étage
    if stair_guid and num_floors >= 2:
        for floor in range(num_floors - 1):
            y_base = floor * FLOOR_H
            # Placer 3 marches
            for step in range(3):
                placements.append({
                    'guid': stair_guid,
                    'x': float(w // 2),
                    'y': y_base + 0.5 + step * 0.8,
                    'z': float(d // 2 + step),
                    'rot': 0
                })
    
    # Props RDC — quelques clusters
    clusters = vocab.get('prop_clusters', [])
    good = [c for c in clusters if 1 <= c['size'] <= 6 and c['w'] <= max(1, w-4) and c['d'] <= max(1, d-4) and c['y_floor'] == 0]
    placed = []
    for _ in range(min(5, len(good))):
        c = random.choice(good)
        for _ in range(15):
            px = random.randint(2, max(2, w-3-int(c['w'])))
            pz = random.randint(2, max(2, d-3-int(c['d'])))
            if not any(abs(px-x)+abs(pz-z)<3 for x,z in placed):
                placed.append((px,pz))
                for prop in c['props']:
                    placements.append({
                        'guid': prop['guid'],
                        'x': px + prop['dx'],
                        'y': prop['dy'],
                        'z': pz + prop['dz'],
                        'rot': prop['rot']
                    })
                break
    
    print(f"[V3] Total: {len(placements)} placements")
    return placements


def encode_slab(placements):
    by_guid = defaultdict(list)
    for p in placements:
        by_guid[p['guid']].append(p)
    binary = struct.pack('<IHHH', 0xD1CEFACE, 2, len(by_guid), 0)
    for guid, instances in by_guid.items():
        binary += uuid.UUID(guid).bytes_le + struct.pack('<HH', len(instances), 0)
        for i in instances:
            sx = max(0, int(round(i['x']*100))) & 0x3FFFF
            sy = max(0, int(round(i['y']*100))) & 0x3FFFF
            sz = max(0, int(round(i['z']*100))) & 0x3FFFF
            r = i['rot'] % 24
            v = (r << 54) | (sz << 36) | (sy << 18) | sx
            binary += struct.pack('<Q', v)
    return base64.b64encode(gzip.compress(binary, compresslevel=9)).decode('ascii')


if __name__ == '__main__':
    vocab = load_vocab()
    print("="*70)
    print("  V3 : périmètre complet, toit aligné, escaliers, wall_set V1")
    print("="*70)
    
    results = []
    for i, (name, w, d, floors) in enumerate([
        ('Petite 8×8 · 2 étages', 8, 8, 2),
        ('Moyenne 12×10 · 2 étages', 12, 10, 2),
        ('Grande 16×14 · 3 étages', 16, 14, 3),
    ]):
        print(f"\n--- {name} ---")
        pls = generate_v3(vocab, w, d, num_floors=floors, seed=i*7+11)
        code = encode_slab(pls)
        results.append({'name': name, 'w': w, 'd': d, 'floors': floors, 'count': len(pls), 'code': code})
        with open(f'generated_v3_{i+1}_{w}x{d}.txt', 'w') as f:
            f.write(code)
        print(f"  Code: {len(code)} chars, saved")
    
    # HTML page
    html = f'''<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Générateur Tavernes V3</title>
<style>
body {{ font-family:system-ui,sans-serif; background:#1a1611; color:#e8dfc9; padding:24px; }}
h1 {{ color:#d4a13a; border-bottom:2px solid #5c3a1a; padding-bottom:8px; }}
h2 {{ color:#c07a2a; }}
.card {{ background:#2a2418; border:1px solid #4a3820; border-radius:8px; padding:20px; margin:20px 0; }}
.stats {{ display:flex; gap:16px; margin:12px 0; font-size:14px; }}
.stat {{ background:#1a1611; padding:6px 12px; border-radius:4px; border-left:3px solid #d4a13a; }}
.code-box {{ background:#0f0d08; padding:12px; border-radius:4px; font-family:'Courier New',monospace; font-size:11px; word-break:break-all; max-height:140px; overflow-y:auto; }}
button.copy {{ background:#5c3a1a; color:#e8dfc9; border:none; padding:8px 16px; border-radius:4px; cursor:pointer; margin-top:8px; }}
button.copy:hover {{ background:#7c4a2a; }}
.fixes {{ background:#2a3a1a; border-left:4px solid #a8c060; padding:12px; border-radius:4px; }}
.fixes ul {{ margin:8px 0; padding-left:20px; }}
</style></head><body>
<h1>Générateur Tavernes — V3</h1>
<div class="fixes">
<strong>✅ Corrections V3 vs V1</strong>
<ul>
<li>Coins fermés (extension des murs nord/sud sur toute la largeur)</li>
<li>Plus de trou dans le mur (périmètre complet, pas de gaps)</li>
<li>Toit aligné exactement sur le bâtiment (pas de dépassement)</li>
<li>Escaliers ajoutés entre chaque paire d'étages</li>
</ul>
</div>
'''
    for i, r in enumerate(results):
        html += f'''<h2>Taverne #{i+1} — {r["name"]}</h2>
<div class="card">
<div class="stats">
<div class="stat">{r["count"]} placements</div>
<div class="stat">Code: {len(r["code"])} chars</div>
<div class="stat">{r["floors"]} étages</div>
</div>
<div class="code-box" id="c{i}">{r["code"]}</div>
<button class="copy" onclick="navigator.clipboard.writeText(document.getElementById('c{i}').innerText); this.textContent='✓ Copié'">Copier</button>
</div>'''
    html += '</body></html>'
    with open('results_v3.html', 'w') as f:
        f.write(html)
    print(f"\n✅ Page V3 sauvegardée")
