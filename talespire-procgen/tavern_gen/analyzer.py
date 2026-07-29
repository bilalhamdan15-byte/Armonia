"""
Tavern Analyzer — Extrait le vocabulaire complet d'une taverne de référence.
Détecte : sol principal, murs, coins, portes, fenêtres, toits, props, clusters.
"""
import base64, zlib, struct, uuid, json, os
from collections import Counter, defaultdict


def decode_slab_lenient(b64):
    """Décode un slab v2 même si le trailer gzip est corrompu (CRC ignoré)."""
    raw = base64.b64decode(b64)
    data = zlib.decompress(raw[10:], -15)
    _, _, num_layouts, _ = struct.unpack_from('<IHHH', data, 0)
    offset = 10
    layouts = []
    for _ in range(num_layouts):
        uid = str(uuid.UUID(bytes_le=data[offset:offset+16]))
        count = struct.unpack_from('<H', data, offset+16)[0]
        layouts.append((uid, count))
        offset += 20
    placements = []
    for guid, count in layouts:
        for _ in range(count):
            if offset + 8 > len(data): break
            v = struct.unpack_from('<Q', data, offset)[0]
            offset += 8
            placements.append({
                'guid': guid,
                'x': (v & 0x3FFFF) / 100.0,
                'y': ((v >> 18) & 0x3FFFF) / 100.0,
                'z': ((v >> 36) & 0x3FFFF) / 100.0,
                'rot': (v >> 54) & 0x1F
            })
    return placements


def classify_assets(placements, box_max=25):
    """Classifie chaque asset par son rôle : floor, wall, corner, roof, prop, etc."""
    in_box = [p for p in placements if 0<=p['x']<=box_max and 0<=p['z']<=box_max and 0<=p['y']<=15]
    by_guid = defaultdict(list)
    for p in in_box:
        by_guid[p['guid']].append(p)

    # Bounding box du bâtiment
    xs = [p['x'] for p in in_box]
    zs = [p['z'] for p in in_box]
    min_x, max_x = int(min(xs)), int(max(xs))
    min_z, max_z = int(min(zs)), int(max(zs))
    building_w = max_x - min_x + 1
    building_d = max_z - min_z + 1

    classified = {}
    for guid, pls in by_guid.items():
        # Grid alignment: fraction on integer x,z
        grid_pct = sum(1 for p in pls if p['x']==int(p['x']) and p['z']==int(p['z'])) / len(pls) * 100
        # Y levels this asset appears at
        ys_int = sorted(set(round(p['y']) for p in pls))
        # Fraction on perimeter (x==min or max, or z==min or max)
        perimeter = sum(1 for p in pls if int(p['x']) in (min_x, max_x) or int(p['z']) in (min_z, max_z))
        peri_pct = perimeter / len(pls) * 100
        # Fraction at corners of building
        corners_count = sum(1 for p in pls if (int(p['x']),int(p['z'])) in [(min_x,min_z),(min_x,max_z),(max_x,min_z),(max_x,max_z)])
        # Rotation patterns
        rots = Counter(p['rot'] for p in pls)

        # Y=0 typically ground floor tiles
        # Y=1 or Y=4/5 or Y=7/8 = walls (they span vertically)
        # Y=3, 6, 9 = between-floor structures (upper walls?)
        appears_on_ground = 0 in ys_int
        multi_level = len([y for y in ys_int if y < 12]) >= 2

        # Rules
        role = 'unknown'
        if grid_pct > 90:
            if appears_on_ground and len(pls) >= 50:
                role = 'floor'
            elif corners_count >= 2 and len(pls) <= 10:
                role = 'corner'
            elif peri_pct > 60:
                role = 'wall'
            elif ys_int and min(ys_int) >= 4 and len(pls) >= 5:
                role = 'roof'
            elif appears_on_ground and len(pls) <= 20 and len(rots) <= 2:
                role = 'ground_outdoor'
            else:
                role = 'tile'
        elif grid_pct > 40:
            # Half-grid: often walls (placed on edge between tiles)
            if peri_pct > 40 or multi_level:
                role = 'wall'
            else:
                role = 'tile'
        else:
            role = 'prop'

        classified[guid] = {
            'role': role,
            'count': len(pls),
            'grid_pct': round(grid_pct, 1),
            'peri_pct': round(peri_pct, 1),
            'y_levels': ys_int,
            'rotations': dict(rots),
        }

    return classified, in_box, (min_x, min_z, max_x, max_z)


def extract_prop_clusters(placements, classified, cluster_dist=1.6):
    """Regroupe les props proches en clusters (bar+tabourets, table+chaises, chambre)."""
    props = [p for p in placements if classified.get(p['guid'], {}).get('role') == 'prop']
    if not props:
        return []
    # Simple union-find clustering by distance
    n = len(props)
    parent = list(range(n))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def union(a,b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb

    for i in range(n):
        for j in range(i+1, n):
            dx = props[i]['x'] - props[j]['x']
            dz = props[i]['z'] - props[j]['z']
            dy = abs(props[i]['y'] - props[j]['y'])
            if dx*dx + dz*dz <= cluster_dist*cluster_dist and dy < 2:
                union(i, j)

    groups = defaultdict(list)
    for i, p in enumerate(props):
        groups[find(i)].append(p)

    clusters = []
    for root, items in groups.items():
        if len(items) < 1: continue
        # Cluster origin = min corner
        ox = min(p['x'] for p in items)
        oy = min(p['y'] for p in items)
        oz = min(p['z'] for p in items)
        # Normalized props (relative to origin)
        norm = [{
            'guid': p['guid'],
            'dx': round(p['x'] - ox, 2),
            'dy': round(p['y'] - oy, 2),
            'dz': round(p['z'] - oz, 2),
            'rot': p['rot']
        } for p in items]
        clusters.append({
            'size': len(items),
            'origin': [round(ox,2), round(oy,2), round(oz,2)],
            'extent': [
                round(max(p['x'] for p in items) - ox, 2),
                round(max(p['y'] for p in items) - oy, 2),
                round(max(p['z'] for p in items) - oz, 2),
            ],
            'y_floor': int(oy // 3),  # Which floor (0, 1, 2)
            'props': norm,
            'guid_composition': dict(Counter(p['guid'] for p in items)),
        })
    # Sort by size desc
    clusters.sort(key=lambda c: -c['size'])
    return clusters


if __name__ == '__main__':
    with open('/tmp/tavern_slab.txt') as f:
        code = f.read().strip()
    pls = decode_slab_lenient(code)
    print(f"Total placements: {len(pls)}")
    cls, in_box, bbox = classify_assets(pls)
    print(f"In-box: {len(in_box)}, bounding: {bbox}")
    # Count by role
    role_counts = Counter(v['role'] for v in cls.values())
    role_totals = defaultdict(int)
    for guid, v in cls.items():
        role_totals[v['role']] += v['count']
    print(f"\nRôles détectés:")
    for role in ['floor', 'wall', 'corner', 'roof', 'ground_outdoor', 'tile', 'prop', 'unknown']:
        if role_counts[role]:
            print(f"  {role:16s}: {role_counts[role]:3d} assets uniques, {role_totals[role]:4d} placements")

    clusters = extract_prop_clusters(in_box, cls, cluster_dist=1.8)
    print(f"\nClusters de props détectés: {len(clusters)}")
    print(f"Top 10 clusters (par taille):")
    for i, c in enumerate(clusters[:10]):
        print(f"  [{i+1}] étage {c['y_floor']} · {c['size']} props · {c['extent'][0]:.1f}×{c['extent'][2]:.1f} tiles · origine {c['origin']}")
        # Show composition
        for g, cnt in list(c['guid_composition'].items())[:3]:
            print(f"        - {g[:8]}... × {cnt}")

    # Save full analysis
    out = {
        'source': 'https://talestavern.com/slab/large-tavern-and-inn/',
        'building_bbox': bbox,
        'classified_assets': cls,
        'placements': in_box,
        'prop_clusters': clusters,
    }
    with open('/sessions/optimistic-peaceful-davinci/mnt/Jeu de rôle/talespire-procgen/tavern_gen/vocabulary.json', 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\n✅ Vocabulaire sauvegardé dans vocabulary.json")
