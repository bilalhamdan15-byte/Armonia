"""
Tavern Generator — Génère un slab TaleSpire à partir d'un vocabulaire extrait.
"""
import json, random, struct, gzip, base64, uuid
from collections import defaultdict, Counter


def analyze_wall_directions(vocab):
    """Pour chaque wall, détermine son orientation dominante (EW vs NS) et sa rotation par défaut."""
    walls_ew = []  # walls that go along X axis (rows)
    walls_ns = []  # walls that go along Z axis (columns)
    corners = []
    
    for guid, meta in vocab['classified_assets'].items():
        if meta['role'] not in ('wall', 'corner'): continue
        # Look at all placements of this wall
        pls = [p for p in vocab['placements'] if p['guid'] == guid]
        # For each placement, count if it's on a horizontal edge (min/max Z) vs vertical edge (min/max X)
        bx = vocab['building_bbox']
        on_horizontal = sum(1 for p in pls if int(p['z']) in (bx[1], bx[3]))
        on_vertical = sum(1 for p in pls if int(p['x']) in (bx[0], bx[2]))
        on_corner = sum(1 for p in pls if (int(p['x']),int(p['z'])) in [(bx[0],bx[1]),(bx[0],bx[3]),(bx[2],bx[1]),(bx[2],bx[3])])
        # Dominant rotation
        rot_counter = Counter(p['rot'] for p in pls)
        dominant_rot = rot_counter.most_common(1)[0][0]
        
        info = {
            'guid': guid, 'count': meta['count'], 'dominant_rot': dominant_rot,
            'rotations': meta['rotations'],
            'y_levels': meta['y_levels']
        }
        if meta['role'] == 'corner' or on_corner > len(pls) * 0.3:
            corners.append(info)
        elif on_horizontal > on_vertical * 1.5:
            walls_ew.append(info)
        elif on_vertical > on_horizontal * 1.5:
            walls_ns.append(info)
        else:
            # ambiguous — could be a wall that appears in both orientations with different rots
            walls_ew.append(info)  # assume EW default
    return walls_ew, walls_ns, corners


def pick_wall_set(walls_ew, walls_ns, corners):
    """Choisit le mur EW, mur NS et corner les plus utilisés = le vocabulaire principal."""
    ew = max(walls_ew, key=lambda w: w['count']) if walls_ew else None
    ns = max(walls_ns, key=lambda w: w['count']) if walls_ns else None
    cn = max(corners, key=lambda w: w['count']) if corners else None
    return ew, ns, cn


def pick_floor_and_roof(vocab):
    floors = [(g, m) for g, m in vocab['classified_assets'].items() if m['role']=='floor']
    roofs = [(g, m) for g, m in vocab['classified_assets'].items() if m['role']=='roof']
    ground = [(g, m) for g, m in vocab['classified_assets'].items() if m['role']=='ground_outdoor']
    floor_guid = max(floors, key=lambda x: x[1]['count'])[0] if floors else None
    roof_guid = max(roofs, key=lambda x: x[1]['count'])[0] if roofs else None
    ground_guid = max(ground, key=lambda x: x[1]['count'])[0] if ground else None
    return floor_guid, roof_guid, ground_guid


def generate_building(vocab, w, d, num_floors=2, seed=42):
    """Génère un bâtiment de dimensions w×d avec num_floors étages.
    Retourne une liste de placements (guid, x, y, z, rot)."""
    random.seed(seed)
    walls_ew, walls_ns, corners = analyze_wall_directions(vocab)
    ew, ns, cn = pick_wall_set(walls_ew, walls_ns, corners)
    floor_guid, roof_guid, ground_guid = pick_floor_and_roof(vocab)
    
    print(f"[GEN] Wall EW: {ew['guid'][:8]}... rot={ew['dominant_rot']}")
    print(f"[GEN] Wall NS: {ns['guid'][:8]}... rot={ns['dominant_rot']}")
    print(f"[GEN] Corner : {cn['guid'][:8] if cn else '-'}... rot={cn['dominant_rot'] if cn else '-'}")
    print(f"[GEN] Floor  : {floor_guid[:8]}...")
    print(f"[GEN] Roof   : {roof_guid[:8]}...")
    
    placements = []
    FLOOR_H = 3  # 3 tiles per floor (as observed in tavern)
    
    for floor in range(num_floors):
        y_base = floor * FLOOR_H
        
        # 1. Floor tiles (interior only, exclude perimeter which will be walls)
        for x in range(1, w-1):
            for z in range(1, d-1):
                placements.append({'guid': floor_guid, 'x': float(x), 'y': float(y_base), 'z': float(z), 'rot': 0})
        
        # 2. Corners
        if cn:
            for cx, cz in [(0,0),(w-1,0),(0,d-1),(w-1,d-1)]:
                placements.append({'guid': cn['guid'], 'x': float(cx), 'y': float(y_base), 'z': float(cz), 'rot': cn['dominant_rot']})
        
        # 3. Walls — EW (top and bottom edges)
        for x in range(1, w-1):
            # Top edge (z=0)
            placements.append({'guid': ew['guid'], 'x': float(x), 'y': float(y_base), 'z': 0.0, 'rot': ew['dominant_rot']})
            # Bottom edge (z=d-1)
            placements.append({'guid': ew['guid'], 'x': float(x), 'y': float(y_base), 'z': float(d-1), 'rot': (ew['dominant_rot']+12)%24})
        
        # 4. Walls — NS (left and right edges)
        for z in range(1, d-1):
            placements.append({'guid': ns['guid'], 'x': 0.0, 'y': float(y_base), 'z': float(z), 'rot': ns['dominant_rot']})
            placements.append({'guid': ns['guid'], 'x': float(w-1), 'y': float(y_base), 'z': float(z), 'rot': (ns['dominant_rot']+12)%24})
    
    # 5. Roof over top floor
    if roof_guid:
        top_y = num_floors * FLOOR_H
        for x in range(w):
            for z in range(d):
                placements.append({'guid': roof_guid, 'x': float(x), 'y': float(top_y), 'z': float(z), 'rot': 0})
    
    # 6. Ground floor: place a few prop clusters inside
    clusters = vocab.get('prop_clusters', [])
    # Filter to small-medium furniture clusters that fit inside w-2 × d-2
    good_clusters = [c for c in clusters if 1 <= c['size'] <= 8 and c['w'] <= w-4 and c['d'] <= d-4 and c['y_floor'] == 0]
    # Place some randomly on ground floor
    num_props_to_place = min(6, len(good_clusters))
    placed_positions = []
    for _ in range(num_props_to_place):
        c = random.choice(good_clusters)
        # Find a valid position — try 10 times
        for _ in range(10):
            px = random.randint(2, w-3 - int(c['w']))
            pz = random.randint(2, d-3 - int(c['d']))
            # Check not too close to existing
            too_close = any(abs(px-x)+abs(pz-z) < 3 for x, z in placed_positions)
            if not too_close:
                placed_positions.append((px, pz))
                for prop in c['props']:
                    placements.append({
                        'guid': prop['guid'],
                        'x': px + prop['dx'],
                        'y': prop['dy'],  # keep original Y
                        'z': pz + prop['dz'],
                        'rot': prop['rot']
                    })
                break
    
    print(f"[GEN] Total placements: {len(placements)} ({num_props_to_place} clusters placed)")
    return placements


def encode_slab_v2(placements):
    """Encode une liste de placements en code slab v2 base64."""
    by_guid = defaultdict(list)
    for p in placements:
        by_guid[p['guid']].append(p)
    
    binary = struct.pack('<IHHH', 0xD1CEFACE, 2, len(by_guid), 0)
    assets_data = b''
    for guid, instances in by_guid.items():
        uid = uuid.UUID(guid)
        binary += uid.bytes_le + struct.pack('<HH', len(instances), 0)
        for inst in instances:
            sx = max(0, int(round(inst['x'] * 100))) & 0x3FFFF
            sy = max(0, int(round(inst['y'] * 100))) & 0x3FFFF
            sz = max(0, int(round(inst['z'] * 100))) & 0x3FFFF
            rot = inst['rot'] % 24
            value = (rot << 54) | (sz << 36) | (sy << 18) | sx
            assets_data += struct.pack('<Q', value)
    binary += assets_data
    compressed = gzip.compress(binary, compresslevel=9)
    return base64.b64encode(compressed).decode('ascii')


if __name__ == '__main__':
    with open('vocabulary.json') as f:
        vocab = json.load(f)
    
    print("="*70)
    print("  Génération de 3 tavernes de tailles différentes")
    print("="*70)
    
    for i, (name, w, d, floors) in enumerate([
        ('Petite taverne 8×8', 8, 8, 2),
        ('Taverne moyenne 12×10', 12, 10, 2),
        ('Grande taverne 16×14', 16, 14, 3),
    ]):
        print(f"\n--- {name} ({floors} étages) ---")
        pls = generate_building(vocab, w, d, num_floors=floors, seed=i*11+7)
        code = encode_slab_v2(pls)
        print(f"  Taille slab code: {len(code)} chars")
        print(f"  CODE (première ligne):\n  {code[:120]}...")
        # Save to file
        outpath = f'/sessions/optimistic-peaceful-davinci/mnt/Jeu de rôle/talespire-procgen/tavern_gen/generated_{i+1}_{w}x{d}.txt'
        with open(outpath, 'w') as f:
            f.write(code)
        print(f"  Sauvé: generated_{i+1}_{w}x{d}.txt")
