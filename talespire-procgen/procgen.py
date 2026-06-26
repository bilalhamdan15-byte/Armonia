#!/usr/bin/env python3
"""
TaleSpire Procedural Map Generator — Armonia Edition v2
=======================================================
Génère des maps TaleSpire à partir d'une bibliothèque de slabs communautaires.

Requiert : Python 3.8+  (aucune dépendance externe)

Usages :
  python procgen.py --config configs/village.json
  python procgen.py --size 40x40 --ground grass --add taverne:1 --add maison:3
  python procgen.py library --list
  python procgen.py library --add "Mon Slab" --type maison --code "H4sI..."
"""

import json, struct, gzip, base64, uuid, random, argparse, os, sys, heapq
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict


# ═══════════════════════════════════════════════════════════════════════════════
#  ENCODEUR / DÉCODEUR  SLAB FORMAT V2
# ═══════════════════════════════════════════════════════════════════════════════

SLAB_MAGIC     = 0xD1CEFACE
SLAB_VERSION   = 2
MAX_SLAB_BYTES = 30720


@dataclass
class AssetPlacement:
    guid : str
    x    : float
    y    : float
    z    : float
    rot  : int = 0   # 0-23, chaque pas = 15°


def encode_slab(placements: List[AssetPlacement]) -> str:
    """Liste d'AssetPlacement → code slab TaleSpire (base64)."""
    if not placements:
        raise ValueError("Aucun asset à encoder.")

    by_guid: Dict[str, List[AssetPlacement]] = defaultdict(list)
    for p in placements:
        by_guid[p.guid].append(p)

    binary = struct.pack('<IHHH', SLAB_MAGIC, SLAB_VERSION, len(by_guid), 0)
    assets_data = b''

    for guid_str, instances in by_guid.items():
        uid = uuid.UUID(guid_str)
        binary += uid.bytes_le + struct.pack('<HH', len(instances), 0)
        for inst in instances:
            sx  = max(0, int(round(inst.x * 100))) & 0x3FFFF
            sy  = max(0, int(round(inst.y * 100))) & 0x3FFFF
            sz  = max(0, int(round(inst.z * 100))) & 0x3FFFF
            rot = inst.rot & 0x1F
            value = (rot << 54) | (sz << 36) | (sy << 18) | sx
            assets_data += struct.pack('<Q', value)

    binary += assets_data
    compressed = gzip.compress(binary, compresslevel=9)
    if len(compressed) > MAX_SLAB_BYTES:
        raise ValueError(
            f"Slab trop grand ({len(compressed):,} B > {MAX_SLAB_BYTES:,} B). "
            "Réduis la taille ou le nombre de bâtiments."
        )
    return base64.b64encode(compressed).decode('ascii')


def decode_slab(code: str) -> List[AssetPlacement]:
    """Code slab TaleSpire (base64) → liste d'AssetPlacement."""
    code = code.strip().strip('`')
    raw  = base64.b64decode(code)
    data = gzip.decompress(raw)

    magic, version, layout_count, _ = struct.unpack_from('<IHHH', data, 0)
    if magic != SLAB_MAGIC:
        raise ValueError(f"Magic invalide : 0x{magic:08X}")

    offset   = 10
    layouts  = []
    for _ in range(layout_count):
        uid_bytes = data[offset:offset+16]
        uid       = uuid.UUID(bytes_le=uid_bytes)
        count, _  = struct.unpack_from('<HH', data, offset+16)
        layouts.append((str(uid), count))
        offset   += 20

    placements = []
    for guid_str, count in layouts:
        for _ in range(count):
            value = struct.unpack_from('<Q', data, offset)[0]
            offset += 8
            sx  = (value      ) & 0x3FFFF
            sy  = (value >> 18) & 0x3FFFF
            sz  = (value >> 36) & 0x3FFFF
            rot = (value >> 54) & 0x1F
            placements.append(AssetPlacement(
                guid=guid_str,
                x=sx / 100.0,
                y=sy / 100.0,
                z=sz / 100.0,
                rot=rot
            ))
    return placements


def slab_bounding_box(placements: List[AssetPlacement]) -> Tuple[float,float,float,float,float,float]:
    """Retourne (min_x, min_y, min_z, max_x, max_y, max_z) d'un ensemble de placements."""
    xs = [p.x for p in placements]
    ys = [p.y for p in placements]
    zs = [p.z for p in placements]
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def offset_placements(placements: List[AssetPlacement],
                      dx: float, dy: float, dz: float) -> List[AssetPlacement]:
    """Décale tous les placements d'un vecteur (dx, dy, dz)."""
    return [
        AssetPlacement(p.guid, p.x + dx, p.y + dy, p.z + dz, p.rot)
        for p in placements
    ]


# ═══════════════════════════════════════════════════════════════════════════════
#  CATALOGUE DE SOL  (assets individuels TaleSpire)
# ═══════════════════════════════════════════════════════════════════════════════

_cat_cache: Optional[Dict] = None

def _cat_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'catalogue.json')

def load_catalogue() -> Dict:
    global _cat_cache
    if _cat_cache is None:
        with open(_cat_path(), 'r', encoding='utf-8') as f:
            data = json.load(f)
        _cat_cache = {
            cat: [a for a in assets if 'guid' in a]
            for cat, assets in data.items()
            if not cat.startswith('_')
        }
    return _cat_cache


def pick(cat: Dict, category: str, tag: Optional[str] = None) -> Optional[str]:
    assets = cat.get(category, [])
    if tag:
        assets = [a for a in assets if tag in a.get('tags', [])]
    return random.choice(assets)['guid'] if assets else None

def pick_named(cat: Dict, name: str) -> Optional[str]:
    """Cherche un asset par nom (insensible à la casse) dans toutes les catégories."""
    for assets in cat.values():
        for a in assets:
            if a.get('name','').lower() == name.lower():
                return a['guid']
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  BIBLIOTHÈQUE DE SLABS
# ═══════════════════════════════════════════════════════════════════════════════

_lib_cache: Optional[List[Dict]] = None

def _lib_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'library.json')

def load_library() -> List[Dict]:
    global _lib_cache
    if _lib_cache is None:
        path = _lib_path()
        if not os.path.exists(path):
            _lib_cache = []
        else:
            with open(path, 'r', encoding='utf-8') as f:
                _lib_cache = json.load(f)
    return _lib_cache

def save_library(lib: List[Dict]):
    global _lib_cache
    _lib_cache = lib
    with open(_lib_path(), 'w', encoding='utf-8') as f:
        json.dump(lib, f, ensure_ascii=False, indent=2)

def library_entry_placements(entry: Dict) -> List[AssetPlacement]:
    """Décode le slab d'une entrée de bibliothèque et le ramène à l'origine (0,0,0)."""
    placements = decode_slab(entry['slab_code'])
    if not placements:
        return []
    min_x, min_y, min_z, _, _, _ = slab_bounding_box(placements)
    return offset_placements(placements, -min_x, -min_y, -min_z)

def get_entry_size(entry: Dict) -> Tuple[int, int]:
    """Retourne (width, depth) d'un slab en tiles (arrondi au supérieur)."""
    if 'width' in entry and 'depth' in entry:
        return entry['width'], entry['depth']
    placements = decode_slab(entry['slab_code'])
    if not placements:
        return 1, 1
    min_x, _, min_z, max_x, _, max_z = slab_bounding_box(placements)
    return max(1, int(max_x - min_x) + 2), max(1, int(max_z - min_z) + 2)

def find_entries(lib: List[Dict], type_name: str) -> List[Dict]:
    """Retourne les entrées de la bibliothèque correspondant à un type."""
    t = type_name.lower().strip()
    return [e for e in lib if e.get('type','').lower() == t or e.get('name','').lower() == t]


# ═══════════════════════════════════════════════════════════════════════════════
#  PLACEMENT SANS CHEVAUCHEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PlacedBuilding:
    entry      : Dict
    x          : int    # coin supérieur gauche sur la grille
    z          : int
    width      : int
    depth      : int
    door_x     : int    # point de connexion pour les chemins
    door_z     : int

def _find_slot(occupied: Set[Tuple[int,int]],
               map_w: int, map_h: int,
               bw: int, bh: int,
               margin: int = 1,
               attempts: int = 200) -> Optional[Tuple[int,int]]:
    """Trouve aléatoirement une position libre sur la grille."""
    for _ in range(attempts):
        x = random.randint(margin, map_w - bw - margin)
        z = random.randint(margin, map_h - bh - margin)
        cells = {(x+dx, z+dz) for dx in range(-margin, bw+margin)
                               for dz in range(-margin, bh+margin)}
        if not cells & occupied:
            return x, z
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  CHEMINS  (A* grille 2D)
# ═══════════════════════════════════════════════════════════════════════════════

def _astar(grid_blocked: Set[Tuple[int,int]],
           start: Tuple[int,int], end: Tuple[int,int],
           map_w: int, map_h: int) -> List[Tuple[int,int]]:
    """A* entre start et end sur une grille. Retourne la liste de cases du chemin."""
    def h(a, b):
        return abs(a[0]-b[0]) + abs(a[1]-b[1])

    open_heap = [(h(start, end), 0, start)]
    came_from: Dict[Tuple[int,int], Optional[Tuple[int,int]]] = {start: None}
    g_score   = {start: 0}

    while open_heap:
        _, g, current = heapq.heappop(open_heap)
        if current == end:
            path = []
            while current is not None:
                path.append(current)
                current = came_from[current]
            return path[::-1]
        for dx, dz in ((0,1),(0,-1),(1,0),(-1,0)):
            nb = (current[0]+dx, current[1]+dz)
            if not (0 <= nb[0] < map_w and 0 <= nb[1] < map_h):
                continue
            # Les bâtiments sont traversables avec un coût élevé (contournement)
            extra = 50 if nb in grid_blocked else 0
            new_g = g + 1 + extra
            if new_g < g_score.get(nb, 10**9):
                g_score[nb] = new_g
                came_from[nb] = current
                heapq.heappush(open_heap, (new_g + h(nb, end), new_g, nb))
    return []   # pas de chemin


# ═══════════════════════════════════════════════════════════════════════════════
#  GÉNÉRATEUR DE MAP PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

class MapGenerator:
    """
    Génère une map à partir d'une liste de bâtiments (slabs bibliothèque).

    Étapes :
      1. Sol sur toute la surface
      2. Placement des bâtiments sans chevauchement
      3. Chemins A* entre les entrées de bâtiments
      4. Fusion + encodage en un slab unique
    """

    def __init__(self,
                 map_w   : int,
                 map_h   : int,
                 ground_guid : Optional[str],
                 path_guid   : Optional[str],
                 seed    : Optional[int] = None):
        self.map_w       = map_w
        self.map_h       = map_h
        self.ground_guid = ground_guid
        self.path_guid   = path_guid
        if seed is not None:
            random.seed(seed)
        self.placements  : List[AssetPlacement] = []
        self.occupied    : Set[Tuple[int,int]]  = set()

    # ── Sol ──────────────────────────────────────────────────────────────────
    def _place_ground(self):
        if not self.ground_guid:
            return
        for x in range(self.map_w):
            for z in range(self.map_h):
                self.placements.append(
                    AssetPlacement(self.ground_guid, float(x), 0.0, float(z))
                )

    # ── Bâtiments ─────────────────────────────────────────────────────────────
    def _place_buildings(self, requests: List[Tuple[Dict, int]]) -> List[PlacedBuilding]:
        """
        requests = [(entry_dict, count), ...]
        Retourne la liste des bâtiments placés.
        """
        placed_buildings: List[PlacedBuilding] = []

        for entry, count in requests:
            for _ in range(count):
                bw, bh = get_entry_size(entry)
                slot = _find_slot(self.occupied, self.map_w, self.map_h, bw, bh)
                if slot is None:
                    print(f"  ⚠️  Impossible de placer « {entry['name']} » (map trop petite ?)")
                    continue

                sx, sz = slot

                # Réserver les cases
                for dx in range(bw):
                    for dz in range(bh):
                        self.occupied.add((sx+dx, sz+dz))

                # Décoder + placer le slab à (sx, 0, sz)
                slab_placements = library_entry_placements(entry)
                for p in slab_placements:
                    self.placements.append(
                        AssetPlacement(p.guid, p.x + sx, p.y, p.z + sz, p.rot)
                    )

                # Point d'entrée = milieu de la face avant du bâtiment
                pb = PlacedBuilding(
                    entry=entry, x=sx, z=sz, width=bw, depth=bh,
                    door_x=sx + bw // 2, door_z=sz
                )
                placed_buildings.append(pb)
                print(f"  ✅  « {entry['name']} » placé à ({sx}, {sz})")

        return placed_buildings

    # ── Chemins ───────────────────────────────────────────────────────────────
    def _place_paths(self, buildings: List[PlacedBuilding]):
        if not self.path_guid or len(buildings) < 2:
            return

        # Relier chaque bâtiment au suivant (chaîne simple)
        path_cells: Set[Tuple[int,int]] = set()
        for i in range(len(buildings) - 1):
            a = (buildings[i].door_x,   buildings[i].door_z)
            b = (buildings[i+1].door_x, buildings[i+1].door_z)
            path = _astar(self.occupied, a, b, self.map_w, self.map_h)
            for cell in path:
                path_cells.add(cell)

        # Relier aussi le dernier au premier (boucle)
        if len(buildings) >= 3:
            a = (buildings[-1].door_x, buildings[-1].door_z)
            b = (buildings[0].door_x,  buildings[0].door_z)
            for cell in _astar(self.occupied, a, b, self.map_w, self.map_h):
                path_cells.add(cell)

        for (px, pz) in path_cells:
            if 0 <= px < self.map_w and 0 <= pz < self.map_h:
                self.placements.append(
                    AssetPlacement(self.path_guid, float(px), 0.02, float(pz))
                )

    # ── Point d'entrée public ─────────────────────────────────────────────────
    def generate(self, requests: List[Tuple[Dict, int]]) -> List[AssetPlacement]:
        print("  🌿  Placement du sol …")
        self._place_ground()

        print("  🏠  Placement des bâtiments …")
        placed = self._place_buildings(requests)

        print("  🛤️   Tracé des chemins …")
        self._place_paths(placed)

        return self.placements


# ═══════════════════════════════════════════════════════════════════════════════
#  RÉSOLUTION DE LA CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

def resolve_ground(cat: Dict, ground_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Retourne (ground_guid, path_guid) depuis un nom lisible ('grass', 'stone', …)
    ou un GUID direct.
    """
    GROUND_PRESETS = {
        'herbe':  (None, 'path'),
        'grass':  (None, 'path'),
        'pierre': ('stone', 'stone'),
        'stone':  ('stone', 'stone'),
        'terre':  (None, 'path'),
        'dirt':   (None, 'path'),
        'bois':   ('indoor', None),
        'wood':   ('indoor', None),
    }
    key = ground_name.lower()

    # GUID direct ?
    if '-' in ground_name and len(ground_name) == 36:
        return ground_name, pick(cat, 'ground', 'path')

    # Nom d'asset ?
    named = pick_named(cat, ground_name)
    if named:
        return named, pick(cat, 'ground', 'path')

    # Preset
    ground_tag, path_tag = GROUND_PRESETS.get(key, (None, 'path'))
    ground_guid = pick(cat, 'ground', ground_tag) if ground_tag else pick(cat, 'ground')
    path_guid   = pick(cat, 'ground', path_tag)   if path_tag   else None
    return ground_guid, path_guid


def parse_size(size_str: str) -> Tuple[int, int]:
    """'40x40' → (40, 40).  'large' → (48, 48). etc."""
    PRESETS = {'small': (20,20), 'medium': (32,32), 'large': (48,48), 'xl': (64,64)}
    if size_str.lower() in PRESETS:
        return PRESETS[size_str.lower()]
    if 'x' in size_str:
        parts = size_str.lower().split('x')
        return int(parts[0]), int(parts[1])
    n = int(size_str)
    return n, n


def resolve_requests(lib: List[Dict],
                     adds: List[str]) -> List[Tuple[Dict, int]]:
    """
    'taverne:1', 'maison:3' → [(entry_dict, 1), (entry_dict, 3), ...]
    Si l'entrée est introuvable, elle est ignorée avec un avertissement.
    """
    requests = []
    for spec in adds:
        if ':' in spec:
            type_name, count_str = spec.rsplit(':', 1)
            count = int(count_str)
        else:
            type_name, count = spec, 1

        entries = find_entries(lib, type_name)
        if not entries:
            print(f"  ⚠️  Type « {type_name} » introuvable dans la bibliothèque.")
            continue
        for _ in range(count):
            requests.append((random.choice(entries), 1))
    return requests


# ═══════════════════════════════════════════════════════════════════════════════
#  COMMANDE  library
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_library(args):
    lib = load_library()

    if args.list:
        if not lib:
            print("📚  Bibliothèque vide. Ajoutez des slabs avec --add.")
            return
        print(f"{'#':<4} {'Nom':<30} {'Type':<15} {'Taille':>10}")
        print("─" * 65)
        for i, e in enumerate(lib):
            w, d = get_entry_size(e)
            print(f"{i:<4} {e['name']:<30} {e.get('type','?'):<15} {w}×{d:>4}")
        return

    if args.add:
        if not args.code:
            print("❌  --code requis pour ajouter un slab.")
            sys.exit(1)
        code = args.code.strip()

        # Valider + auto-détecter les dimensions
        try:
            ps = decode_slab(code)
            w, d = get_entry_size({'slab_code': code})
            print(f"  ✅  Slab valide — {len(ps)} assets, dimensions détectées : {w}×{d}")
        except Exception as e:
            print(f"  ❌  Slab invalide : {e}")
            sys.exit(1)

        entry = {
            'name'     : args.add,
            'type'     : (args.type or 'custom').lower(),
            'slab_code': code,
            'width'    : w,
            'depth'    : d,
        }
        lib.append(entry)
        save_library(lib)
        print(f"  💾  « {args.add} » ajouté à la bibliothèque ({args.type or 'custom'}, {w}×{d}).")
        return

    if args.remove is not None:
        if args.remove >= len(lib):
            print(f"❌  Index {args.remove} invalide (bibliothèque : {len(lib)} entrées).")
            sys.exit(1)
        removed = lib.pop(args.remove)
        save_library(lib)
        print(f"  🗑️   « {removed['name']} » supprimé.")
        return

    print("Utilisez --list, --add, ou --remove.")


# ═══════════════════════════════════════════════════════════════════════════════
#  COMMANDE  generate
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_generate(args):
    # ── Charger config JSON si fournie ────────────────────────────────────────
    config: Dict = {}
    if args.config:
        with open(args.config, 'r', encoding='utf-8') as f:
            config = json.load(f)

    # Les args CLI écrasent la config
    size_str   = args.size   or config.get('size',   '32x32')
    ground_str = args.ground or config.get('ground', 'grass')
    seed       = args.seed   if args.seed is not None else config.get('seed', None)
    adds       = list(args.add or []) or config.get('add', [])
    output     = args.output or config.get('output', None)

    map_w, map_h = parse_size(size_str)

    try:
        cat = load_catalogue()
    except FileNotFoundError:
        print("❌  catalogue.json introuvable.")
        sys.exit(1)

    lib = load_library()

    ground_guid, path_guid = resolve_ground(cat, ground_str)
    requests = resolve_requests(lib, adds)

    if not requests:
        print("⚠️  Aucun bâtiment à placer. Utilisez --add type:count ou remplissez la bibliothèque.")

    print(f"\n🗺️  Génération — {map_w}×{map_h}, sol : {ground_str}")
    if seed is not None:
        random.seed(seed)

    gen = MapGenerator(map_w, map_h, ground_guid, path_guid, seed=seed)
    placements = gen.generate(requests)

    print(f"\n✅  {len(placements):,} assets au total")
    print("🔧  Encodage slab …")

    try:
        code = encode_slab(placements)
    except ValueError as e:
        print(f"❌  {e}")
        sys.exit(1)

    if output:
        with open(output, 'w', encoding='utf-8') as f:
            f.write(code)
        print(f"💾  Slab → {output}")
    else:
        print()
        print("═" * 60)
        print("📋  CODE SLAB — copiez-collez dans TaleSpire :")
        print("═" * 60)
        print(code)
        print("═" * 60)
        print("\n💡  Ctrl+V dans TaleSpire pour coller.")


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='procgen',
        description='TaleSpire Procedural Map Generator — Armonia Edition v2',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  # Générer depuis un fichier de config
  python procgen.py --config configs/village.json

  # Générer en ligne de commande
  python procgen.py --size 40x40 --ground stone --add taverne:1 --add maison:3

  # Gérer la bibliothèque de slabs
  python procgen.py library --list
  python procgen.py library --add "Cat and Mutton" --type taverne --code "H4sI..."
  python procgen.py library --remove 0
        """
    )
    sub = p.add_subparsers(dest='cmd')

    # ── Sous-commande : library ───────────────────────────────────────────────
    sl = sub.add_parser('library', aliases=['lib'], help='Gérer la bibliothèque de slabs')
    sl.add_argument('--list',   action='store_true', help='Lister les slabs')
    sl.add_argument('--add',    metavar='NOM',       help='Ajouter un slab')
    sl.add_argument('--type',   metavar='TYPE',      help='Type du slab (maison, taverne, forge…)')
    sl.add_argument('--code',   metavar='SLAB_CODE', help='Code slab base64')
    sl.add_argument('--remove', type=int, metavar='INDEX', help='Supprimer le slab #INDEX')

    # ── Commande principale : generate (défaut) ───────────────────────────────
    # Arguments au niveau racine (pas de sous-commande) ET dans une sous-commande explicite
    for parser in [p, sub.add_parser('generate', aliases=['gen'], help='Générer une map')]:
        parser.add_argument('--config', '-c', metavar='FICHIER.json',
                            help='Fichier de configuration JSON')
        parser.add_argument('--size', metavar='WxH',
                            help='Taille de la map ex: 40x40 ou small/medium/large/xl')
        parser.add_argument('--ground', metavar='NOM',
                            help='Type de sol : grass, stone, dirt, wood — ou GUID direct')
        parser.add_argument('--add', metavar='TYPE:N', action='append',
                            help='Ajouter des bâtiments ex: --add taverne:1 --add maison:3')
        parser.add_argument('--seed', type=int, metavar='N',
                            help='Graine aléatoire')
        parser.add_argument('--output', '-o', metavar='FICHIER',
                            help='Fichier de sortie (sinon : terminal)')

    return p


def main():
    parser = build_parser()
    args   = parser.parse_args()

    if args.cmd in ('library', 'lib'):
        cmd_library(args)
    else:
        # generate (défaut si aucune sous-commande)
        cmd_generate(args)


if __name__ == '__main__':
    main()
