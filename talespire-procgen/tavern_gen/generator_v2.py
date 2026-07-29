"""Générateur V2 : corners via extension, wall_set robuste, escaliers, toit ajusté."""
import json, random, struct, gzip, base64, uuid
from collections import defaultdict, Counter


def load_vocab():
    with open('vocabulary.json') as f:
        return json.load(f)


def build_wall_set(vocab):
    """Détecte le mur principal et ses 4 rotations (W=0, N=6, E=12, S=18 typiques)."""
    placements = vocab['placements']
    walls = [p for p in placements if 0 <= p['y'] < 3 and vocab['classified_assets'].get(p['guid'],{}).get('role') == 'wall']
    
    # Le mur le plus utilisé au RDC
    guid_counts = Counter(p['guid'] for p in walls)
    main_guid = guid_counts.most_common(1)[0][0]
    
    # Ses rotations avec leurs positions moyennes en X et Z
    main_pls = [p for p in walls if p['guid'] == main_guid]
    by_rot = defaultdict(list)
    for p in main_pls:
        by_rot[p['rot']].append(p)
    
    # Pour chaque rotation, identifier son côté par position moyenne
    sides = {}  # side_name → (guid, rot)
    for rot, pls in by_rot.items():
        avg_x = sum(p['x'] for p in pls) / len(pls)
        avg_z = sum(p['z'] for p in pls) / len(pls)
        # Compare to building center
        xs_all = [p['x'] for p in walls]; zs_all = [p['z'] for p in walls]
        cx = (min(xs_all) + max(xs_all)) / 2
        cz = (min(zs_all) + max(zs_all)) / 2
        # Which side is this rotation on?
        dx = avg_x - cx
        dz = avg_z - cz
        # Weight by count
        sides.setdefault((rot,), (0, main_guid, rot, avg_x, avg_z))
    
    # Simpler assignment: 4 rotations = 4 sides. Sort by avg_z first (N vs S), then avg_x (W vs E)
    rot_list = sorted(by_rot.items(), key=lambda x: -len(x[1]))[:4]
    if len(rot_list) < 4:
        # Fill missing rotations by inferring (rot + 6, +12, +18)
        base = rot_list[0][0]
        rot_list = [(base, by_rot.get(base, [])),
                    ((base+6)%24, by_rot.get((base+6)%24, [])),
                    ((base+12)%24, by_rot.get((base+12)%24, [])),
                    ((base+18)%24, by_rot.get((base+18)%24, []))]
    
    # For each rotation, average Z tells us N (low Z) vs S (high Z), average X tells W vs E
    sides_detail = []
    for rot, pls in rot_list:
        if not pls:
            sides_detail.append((rot, 999, 999))  # unknown
            continue
        avg_x = sum(p['x'] for p in pls) / len(pls)
        avg_z = sum(p['z'] for p in pls) / len(pls)
        sides_detail.append((rot, avg_x, avg_z))
    
    # Assign: smallest avg_z → NORTH, largest → SOUTH, smallest avg_x → WEST, largest → EAST
    by_avg_z = sorted(sides_detail, key=lambda s: s[2])
    by_avg_x = sorted(sides_detail, key=lambda s: s[1])
    
    north = by_avg_z[0][0]
    south = by_avg_z[-1][0]
    west = by_avg_x[0][0]
    east = by_avg_x[-1][0]
    
    return {
        'guid': main_guid,
        'north': north,
        'south': south,
        'west': west,
        'east': east,
    }


def find_stair_asset(vocab):
    """Cherche un asset qui pourrait être un escalier (Y non entier, spanning multiple levels)."""
    placements = vocab['placements']
    by_guid = defaultdict(list)
    for p in placements:
        by_guid[p['guid']].append(p)
    
    # Un vrai escalier : plusieurs instances aux mêmes XZ mais Y différents, ou Y intermédiaires
    best = None
    best_score = 0
    for guid, pls in by_guid.items():
        if len(pls) < 3 or len(pls) > 30: continue
        ys = sorted(set(round(p['y'],2) for p in pls))
        # Score: has multiple Y levels including intermediate ones
        intermediate = [y for y in ys if 0.3 < y < 2.7 or 3.3 < y < 5.7]
        if len(intermediate) >= 1 and len(ys) >= 2:
            score = len(pls) * len(ys)
            if score > best_score:
                best_score = score
                best = guid
    return best


def pick_floor_and_roof(vocab):
    floors = [(g, m) for g, m in vocab['classified_assets'].items() if m['role']=='floor']
    roofs = [(g, m) for g, m in vocab['classified_assets'].items() if m['role']=='roof']
    floor_guid = max(floors, key=lambda x: x[1]['count'])[0] if floors else None
    roof_guid = max(roofs, key=lambda x: x[1]['count'])[0] if roofs else None
    return floor_guid, roof_guid


def generate_building_v2(vocab, w, d, num_floors=2, seed=42):
    """V2 : corners par extension, 4 rotations murs, escaliers, toit ajusté."""
    random.seed(seed)
    ws = build_wall_set(vocab)
    floor_guid, roof_guid = pick_floor_and_roof(vocab)
    stair_guid = find_stair_asset(vocab)
    
    print(f"[GEN V2] Wall: {ws['guid'][:8]}  rots N={ws['north']} S={ws['south']} W={ws['west']} E={ws['east']}")
    print(f"[GEN V2] Floor: {floor_guid[:8] if floor_guid else '-'}   Roof: {roof_guid[:8] if roof_guid else '-'}")
    print(f"[GEN V2] Stair: {stair_guid[:8] if stair_guid else '-'}")
    
    placements = []
    FLOOR_H = 3
    
    for floor in range(num_floors):
        y_base = floor * FLOOR_H
        
        # 1. Floor tiles (interior, all cells)
        for x in range(1, w-1):
            for z in range(1, d-1):
                placements.append({'guid': floor_guid, 'x': float(x), 'y': float(y_base), 'z': float(z), 'rot': 0})
        
        # 2. Walls — perimeter with corners INCLUDED (no separate corner asset)
        wg = ws['guid']
        # North side (z=0): full width including corners
        for x in range(0, w):
            placements.append({'guid': wg, 'x': float(x), 'y': float(y_base), 'z': 0.0, 'rot': ws['north']})
        # South side (z=d-1): full width including corners
        for x in range(0, w):
            placements.append({'guid': wg, 'x': float(x), 'y': float(y_base), 'z': float(d-1), 'rot': ws['south']})
        # West side (x=0): interior only, corners already done above
        for z in range(1, d-1):
            placements.append({'guid': wg, 'x': 0.0, 'y': float(y_base), 'z': float(z), 'rot': ws['west']})
        # East side (x=w-1): interior only
        for z in range(1, d-1):
            placements.append({'guid': wg, 'x': float(w-1), 'y': float(y_base), 'z': float(z), 'rot': ws['east']})
    
    # 3. Roof: only over the top floor's building footprint (not extending)
    if roof_guid:
        top_y = num_floors * FLOOR_H
        for x in range(0, w):
            for z in range(0, d):
                placements.append({'guid': roof_guid, 'x': float(x), 'y': float(top_y), 'z': float(z), 'rot': 0})
    
    # 4. Stairs between floors (interior, near a wall for visual)
    if stair_guid and num_floors >= 2:
        for floor in range(num_floors - 1):
            y_base = floor * FLOOR_H
            # Place stair at position (2, y_base + 1.5, d-3) — middle of building near south wall
            stair_x = 2
            stair_z = d - 3
            # Place a few tiles going up
            for step in range(3):
                placements.append({
                    'guid': stair_guid,
                    'x': float(stair_x + step),
                    'y': y_base + step * 0.9,  # gradual rise
                    'z': float(stair_z),
                    'rot': 0
                })
    
    # 5. Props: place a few clusters on ground floor
    clusters = vocab.get('prop_clusters', [])
    good_clusters = [c for c in clusters if 1 <= c['size'] <= 6 and c['w'] <= w-4 and c['d'] <= d-4 and c['y_floor'] == 0]
    num_props = min(5, len(good_clusters))
    placed_pos = []
    for _ in range(num_props):
        c = random.choice(good_clusters)
        for _ in range(15):
            px = random.randint(2, max(2, w-3 - int(c['w'])))
            pz = random.randint(2, max(2, d-3 - int(c['d'])))
            too_close = any(abs(px-x)+abs(pz-z) < 3 for x, z in placed_pos)
            if not too_close:
                placed_pos.append((px, pz))
                for prop in c['props']:
                    placements.append({
                        'guid': prop['guid'],
                        'x': px + prop['dx'],
                        'y': prop['dy'],
                        'z': pz + prop['dz'],
                        'rot': prop['rot']
                    })
                break
    
    print(f"[GEN V2] Total: {len(placements)} placements ({num_props} clusters)")
    return placements


def encode_slab_v2(placements):
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
    return base64.b64encode(gzip.compress(binary, compresslevel=9)).decode('ascii')


if __name__ == '__main__':
    vocab = load_vocab()
    print("="*70)
    print("  V2 : Génération de 3 tavernes")
    print("="*70)
    
    codes = []
    for i, (name, w, d, floors) in enumerate([
        ('Petite 8×8 2 étages', 8, 8, 2),
        ('Moyenne 12×10 2 étages', 12, 10, 2),
        ('Grande 16×14 3 étages', 16, 14, 3),
    ]):
        print(f"\n--- {name} ---")
        pls = generate_building_v2(vocab, w, d, num_floors=floors, seed=i*13+3)
        code = encode_slab_v2(pls)
        print(f"  Code: {len(code)} chars")
        codes.append((name, w, d, floors, len(pls), code))
        with open(f'/sessions/optimistic-peaceful-davinci/mnt/Jeu de rôle/talespire-procgen/tavern_gen/generated_v2_{i+1}_{w}x{d}.txt','w') as f:
            f.write(code)
    
    # Save codes for the HTML
    with open('/tmp/v2_codes.json', 'w') as f:
        json.dump([{'name': c[0], 'w': c[1], 'd': c[2], 'floors': c[3], 'count': c[4], 'code': c[5]} for c in codes], f)
    print(f"\n✅ 3 slabs V2 sauvés")
