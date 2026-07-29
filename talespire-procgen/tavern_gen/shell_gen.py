"""
Generateur parametrique de coquille de batiment TaleSpire (methode etalon).
Historique des corrections :
- 24/07 : CORNER = footprint 2x2 tuiles (pas 1x1), confirme par un slab 4x4
  construit a la main par Bilal (corners seuls, aucun mur necessaire).
- 25/07 : bug fenetre sur 1-slot (6x6) corrige ; ajout etage 2 (delta Y=2.5,
  valeur empirique confirmee sur les anciens slabs multi-etages de Bilal) et
  ajout de l'escalier (Tavern Stair), position/rotation reprise d'un ancien
  slab 8x6 deja valide en jeu (x=1,z=2,rot=6, Y = niveau des murs).
"""
import gzip, base64, struct, uuid

# --- GUIDs connus (guid_to_name.json) ---
FOUNDATION = 'cf6063bb-5c6e-4107-b3e9-9c0c5ac75768'  # Tavern Floor 01
DECK       = 'e62c6746-cecf-46bf-8b20-f81738f1d220'  # Tavern Floor 03 (plancher/toit plat)
WALL       = '55421077-5672-492d-9609-89befbf9eb9d'  # Tavern Wall 01
WIN        = '7c5edd5b-38fa-4c1a-aa39-99b5720a9171'  # Wall Only With Window
CORNER     = 'ce1e617e-f031-4011-b64e-ba262082b20f'  # Tavern Wall Corner (footprint 2x2 !)
STAIR      = '8a77baef-61e9-4a59-9591-70d5b0c6f1d6'  # Tavern Stair

CORNER_ROT = {'nw': 0, 'ne': 18, 'se': 12, 'sw': 6}
SIDE_ROT = {
    'north': {'wall': 0,  'win': 18},
    'south': {'wall': 0,  'win': 18},
    'west':  {'wall': 18, 'win': 0},
    'east':  {'wall': 6,  'win': 0},
}
FLOOR_H = 2.5           # delta Y entre etages, confirme empiriquement sur les anciens slabs de Bilal
WALL_Y_OFFSET = 0.5     # confirme par le slab 4x4 de Bilal (corner a Y=0.5 sur une fondation seule)
STAIR_REL = (1.0, 2.0, 6)  # (x,z,rot) relatif a l'origine du batiment, repris d'un ancien slab valide

def full_grid(guid, width, depth, y):
    return {guid: [(float(x), y, float(z), 0) for x in range(width) for z in range(depth)]}

def merge(*dicts):
    out = {}
    for d in dicts:
        for k, v in d.items():
            out.setdefault(k, []).extend(v)
    return out

def corners(width, depth, y):
    """Corner = footprint 2x2. Anchor NW/NE/SE/SW a (0,0)/(w-2,0)/(w-2,d-2)/(0,d-2)."""
    assert width >= 4 and depth >= 4, "corners (2x2 chacun) exigent au moins 4x4"
    x0, x1 = 0, width - 2
    z0, z1 = 0, depth - 2
    return {
        CORNER: [
            (float(x0), y, float(z0), CORNER_ROT['nw']),
            (float(x1), y, float(z0), CORNER_ROT['ne']),
            (float(x1), y, float(z1), CORNER_ROT['se']),
            (float(x0), y, float(z1), CORNER_ROT['sw']),
        ]
    }

def wall_slots(width, depth, y, use_windows=False):
    """Segments de mur (2 tuiles de large chacun) entre les 2 corners de chaque cote.
    n_slots = (longueur-4)/2 par cote, anchors 2,4,...,longueur-4."""
    assert (width - 4) % 2 == 0 and (depth - 4) % 2 == 0, "largeur/profondeur doivent etre paires"
    n_w = (width - 4) // 2
    n_d = (depth - 4) // 2
    out = {WALL: [], WIN: []}

    def piece(idx):
        # idx%2==0 -> fenetre si demande (corrige : un seul slot (idx=0) doit pouvoir etre fenetre)
        return WIN if use_windows and idx % 2 == 0 else WALL

    for i in range(n_w):
        x = 2 + 2 * i
        g = piece(i)
        rot = SIDE_ROT['north']['win' if g == WIN else 'wall']
        out[g].append((float(x), y, 0.0, rot))
        rot = SIDE_ROT['south']['win' if g == WIN else 'wall']
        out[g].append((float(x), y, depth - 1 + 0.5, rot))
    for i in range(n_d):
        z = 2 + 2 * i
        g = piece(i)
        rot = SIDE_ROT['west']['win' if g == WIN else 'wall']
        out[g].append((0.0, y, float(z), rot))
        rot = SIDE_ROT['east']['win' if g == WIN else 'wall']
        out[g].append((width - 1 + 0.5, y, float(z), rot))
    return {k: v for k, v in out.items() if v}

def build_shell(width, depth, floors=1, with_walls=True, use_windows=False, with_stair=False):
    d = {}
    for f in range(floors):
        floor_y = f * FLOOR_H
        d = merge(d, full_grid(FOUNDATION, width, depth, floor_y))
        d = merge(d, corners(width, depth, floor_y + WALL_Y_OFFSET))
        if with_walls:
            d = merge(d, wall_slots(width, depth, floor_y + WALL_Y_OFFSET, use_windows))
    if with_stair and floors >= 2:
        sx, sz, srot = STAIR_REL
        # un escalier par transition d'etage (floors-1 transitions)
        for f in range(floors - 1):
            floor_y = f * FLOOR_H
            d.setdefault(STAIR, []).append((sx, floor_y + WALL_Y_OFFSET, sz, srot))
    return d

def encode_full(data):
    guids_sorted = sorted(data.keys())
    header = struct.pack('<IHHH', 0xD1CEFACE, 2, len(guids_sorted), 0)
    layout_hdrs = b''
    placement_blocks = b''
    for g in guids_sorted:
        ub = uuid.UUID(g).bytes_le
        pls = data[g]
        layout_hdrs += ub + struct.pack('<HH', len(pls), 0)
        for (x, y, z, rot) in pls:
            xi = round(x * 100); yi = round(y * 100); zi = round(z * 100); ri = rot % 24
            val = (ri << 54) | (zi << 36) | (yi << 18) | xi
            placement_blocks += struct.pack('<Q', val)
    raw = header + layout_hdrs + placement_blocks
    comp = gzip.compress(raw, mtime=0)
    return base64.b64encode(comp).decode()

def decode_full(b64):
    raw = gzip.decompress(base64.b64decode(b64))
    magic, version, num_layouts, pad = struct.unpack_from('<IHHH', raw, 0)
    off = struct.calcsize('<IHHH')
    layouts = []
    for i in range(num_layouts):
        u = raw[off:off+16]; off += 16
        count, zero = struct.unpack_from('<HH', raw, off); off += 4
        layouts.append({'uuid': str(uuid.UUID(bytes_le=u)), 'count': count})
    data = {}
    for L in layouts:
        pls = []
        for i in range(L['count']):
            (val,) = struct.unpack_from('<Q', raw, off); off += 8
            rot = (val >> 54) & 0x3F; z = (val >> 36) & 0x3FFFF; y = (val >> 18) & 0x3FFFF; x = val & 0x3FFFF
            pls.append((x/100.0, y/100.0, z/100.0, rot))
        data[L['uuid']] = pls
    return data

# --- Escalier v2 (fourni par Bilal, remplace Tavern Stair) ---
STAIR2 = 'fd31ea7e-0b05-4caa-a3df-439c2e3b6a31'
STAIR2_ROT = 0  # corrige : confirme par le slab de Bilal (2 marches, rot=0 toutes les deux)

def full_grid_with_hole(guid, width, depth, y, hole_tiles):
    """Comme full_grid mais saute les tuiles listees dans hole_tiles (set de (x,z))."""
    pls = []
    for x in range(width):
        for z in range(depth):
            if (x, z) in hole_tiles:
                continue
            pls.append((float(x), y, float(z), 0))
    return {guid: pls}

def build_shell_v2(width, depth, floors=2, use_windows=True, stair_pos=(3, 6)):
    """Coquille multi-etages avec le nouvel escalier (STAIR2).
    CONFIRME par un slab construit et corrige a la main par Bilal :
    2 marches, meme rotation (0), la 2e decalee de -1 en X et +1.0 en Y par
    rapport a la 1ere (pas +1 en Z / +1.25 en Y comme suppose au depart).
    Le trou dans le plancher superieur correspond exactement aux 2 tuiles
    (x,z) et (x-1,z) occupees par les 2 marches."""
    sx, sz = stair_pos
    hole = {(sx, sz), (sx - 1, sz)}
    d = {}
    for f in range(floors):
        floor_y = f * FLOOR_H
        if f == 0:
            d = merge(d, full_grid(FOUNDATION, width, depth, floor_y))
        else:
            d = merge(d, full_grid_with_hole(FOUNDATION, width, depth, floor_y, hole))
        d = merge(d, corners(width, depth, floor_y + WALL_Y_OFFSET))
        d = merge(d, wall_slots(width, depth, floor_y + WALL_Y_OFFSET, use_windows))
    for f in range(floors - 1):
        floor_y = f * FLOOR_H
        d.setdefault(STAIR2, []).extend([
            (float(sx), WALL_Y_OFFSET + floor_y, float(sz), STAIR2_ROT),
            (float(sx - 1), WALL_Y_OFFSET + floor_y + 1.0, float(sz), STAIR2_ROT),
        ])
    return d

def add_flat_roof(d, width, depth, floors):
    """Toit plat = un plancher de plus (DECK, meme asset que les etages) au sommet
    du dernier etage. Valide visuellement en V24 (vue du dessus : planches propres,
    sans trou) - c'est la reference qui marche, contrairement a l'ancienne hypothese
    du "toit rouge" (asset 10727582) qui s'est averee fausse (voir memoire projet)."""
    roof_y = floors * FLOOR_H
    return merge(d, full_grid(DECK, width, depth, roof_y))

# --- Toit en pente (a partir d'un slab de maison simple envoye par Bilal) ---
ROOF_FLAT01 = '2e4e30de-485d-4f4c-a110-92ce364a2a6f'  # Tavern Roof flat 01 (NON UTILISE, voir 26/07 v3)

# 26/07 v3 : VALIDATION COMPLETE. Bilal a teste step13 en jeu et renvoye un
# slab rectifie en ENLEVANT la couche ROOF_FLAT01 (pans plats) car elle etait
# entierement cachee/inutilisee sous le systeme d'abouts+planches+mur de
# pignon+2e niveau. Comparaison programmatique : notre generateur (moins
# ROOF_FLAT01) reproduit EXACTEMENT (match octet pour octet sur les 9
# layouts, floor/mur/fenetre/coin/escalier/toit) le slab corrige de Bilal sur
# le 8x8. Le toit n'a donc PAS besoin des tuiles plates du tout - seul le
# systeme ci-dessous (about+planche+mur pignon+2e niveau) suffit a fermer
# completement le volume.
# Remarque de Bilal a prendre en compte pour la suite : la largeur du
# batiment determine la hauteur/complexite du faitage necessaire (un batiment
# plus large qu'un 8x8 aura probablement besoin de PLUS de 2 niveaux de
# faitage pour fermer le triangle, comme suggere par l'exemple de maison plus
# complexe decode plus tot dans le projet, avec plusieurs paliers). PAS
# ENCORE TESTE au-dela de width=8 - a valider avant de generaliser au-dela de
# cette taille.
ROOF_GABLE_END = '10727582-c251-4dc6-acbb-ec058d2bd80b'    # about de faitage (piece d'angle/pignon)
ROOF_RIDGE_BOARD = 'bd1e0ed2-3315-48bc-bdcb-37cf15cf934e'  # planche de faitage (comble entre 2 abouts)
GABLE_WALL = '1928adc8-1413-4026-ab36-d3db13415ed4'        # mur plat de pignon (ferme le bas du triangle)
ROOF_TIER2_END = 'baaf3839-0c43-42a2-9154-95f764b319a1'    # about du 2e niveau de faitage (surleve)

def add_pitched_roof(d, width, depth, floors, with_ridge_cap=True):
    """Toit fabrique UNIQUEMENT a partir du systeme de faitage (pas de tuiles
    ROOF_FLAT01 - confirme inutile par Bilal, voir commentaire 26/07 v3 ci-dessus) :
    about+planches sur les 2 colonnes exterieures (x=0 et width-2, alignees
    sur les ancres des CORNER), mur de pignon plat sur les 4 colonnes
    centrales, et un 2e niveau de faitage surleve sur les 2 colonnes internes
    (x=half-2 et half). VALIDE EN JEU par Bilal sur le 8x8 (match exact,
    round-trip inclus). Pas encore teste sur d'autres tailles que 8x8 - une
    largeur plus grande demandera probablement plus de 2 niveaux (a
    confirmer en jeu avant de l'assumer)."""
    assert width % 2 == 0, "largeur doit etre paire pour 2 pans symetriques"
    assert width >= 8, "le mur de pignon (4 colonnes centrales) exige au moins 8 de large"
    assert with_ridge_cap is False or (depth - 2) % 2 == 0, \
        "depth doit etre pair pour un nombre entier de planches de faitage (abouts + planches de 2)"
    roof_y = floors * FLOOR_H
    half = width // 2
    if with_ridge_cap:
        x0, x1 = 0, width - 2  # colonnes exterieures (= ancres des CORNER)

        ends = [
            (float(x0), roof_y, 0.0, 18),
            (float(x0), roof_y, float(depth - 1), 18),
            (float(x1), roof_y, 0.0, 6),
            (float(x1), roof_y, float(depth - 1), 6),
        ]
        boards = []
        z = 1
        while z <= depth - 3:
            boards.append((float(x0), roof_y, float(z), 12))
            boards.append((float(x1), roof_y, float(z), 0))
            z += 2
        d = merge(d, {ROOF_GABLE_END: ends})

        gable_wall = []
        for gx in range(half - 2, half + 2):
            gable_wall.append((float(gx), roof_y, 0.0, 0))
            gable_wall.append((float(gx), roof_y, depth - 1 + 0.5, 0))
        d = merge(d, {GABLE_WALL: gable_wall})

        tier2_y = roof_y + 1.75
        tier2_ends = [
            (float(half - 2), tier2_y, 0.0, 12),
            (float(half - 2), tier2_y, float(depth - 2), 12),
            (float(half), tier2_y, 0.0, 0),
            (float(half), tier2_y, float(depth - 2), 0),
        ]
        d = merge(d, {ROOF_TIER2_END: tier2_ends})
        z = 2
        while z <= depth - 4:
            boards.append((float(half - 2), tier2_y, float(z), 12))
            boards.append((float(half), tier2_y, float(z), 0))
            z += 2
        d = merge(d, {ROOF_RIDGE_BOARD: boards})
    return d

if __name__ == '__main__':
    d4 = build_shell(4, 4, floors=1, with_walls=True)
    ref_b64 = 'H4sIAAAAAAAACjv369xFJgYmBgaGukS5c4YfBB22+e1SU2jaxM8CFNudnHA+L4bdcfPLOTxRx8MzBIBiJ4CwgYeBmQFMNzCC+AwMDSwMYJqBQYeRgeGAEIQGqgPTDmwQmoEBogokD9bFA6FB8hDdDAwpUPkUqHwKVD6FAQFA8gxQeQaoPAIAANzIN/rUAAAA'
    ref = decode_full(ref_b64)
    for k in ref:
        assert sorted(ref[k]) == sorted(d4.get(k, [])), f'mismatch on {k}'
    print('4x4 reference MATCH ok')

    # test fenetre 1-slot (6x6) corrigee
    d6w = build_shell(6, 6, floors=1, with_walls=True, use_windows=True)
    assert len(d6w.get(WIN, [])) == 4, d6w.get(WIN, [])
    print('6x6 fenetre fix OK, WIN count=', len(d6w[WIN]))

    # test etage 2 + escalier
    d2f = build_shell(8, 8, floors=2, with_walls=True, use_windows=True, with_stair=True)
    b64 = encode_full(d2f)
    d2b = decode_full(b64)
    for k in d2f: assert sorted(d2f[k]) == sorted(d2b[k]), k
    print('8x8 2 etages + escalier round-trip OK', {k[:8]: len(v) for k, v in d2f.items()})
    open('/tmp/step5_2floors_stair_8x8.txt', 'w').write(b64)
