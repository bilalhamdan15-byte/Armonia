"""
Visualiseur schematique de slabs TaleSpire (pas de vrai rendu 3D - on n'a pas
les meshes/textures proprietaires du jeu). But : transformer les coordonnees
decodees (guid, x, y, z, rot) en un plan 2D (vue du dessus, par niveau) + une
elevation (vue de cote), coloree/legendee par type d'asset, pour AUTO-VERIFIER
la structure (trous, chevauchements, alignement) AVANT de demander a Bilal de
construire/valider en jeu. Ne remplace pas la validation in-game pour les
aspects visuels/texture (ex: le faux "toit rouge" plein), mais attrape la
quasi-totalite des bugs geometriques qu'on a rencontres jusqu'ici.
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.transforms as mtransforms
import numpy as np

# guid -> (nom_court, couleur, w, d, categorie)
# w,d = empreinte approx en unites de coordonnees (1 unite = 1 tuile), dans le
# repere local AVANT rotation. Rotation = index*15deg, appliquee autour de
# l'ancre (x,z) elle-meme (convention empirique confirmee sur les slabs de Bilal).
ASSET_INFO = {
    'cf6063bb-5c6e-4107-b3e9-9c0c5ac75768': ('Sol',        '#8a8a8a', 1, 1, 'floor'),
    'e62c6746-cecf-46bf-8b20-f81738f1d220': ('Deck',       '#a0a0a0', 1, 1, 'floor'),
    '55421077-5672-492d-9609-89befbf9eb9d': ('Mur',        '#7a4a2a', 2, 0.3, 'wall'),
    '82b03fd9-1afb-463f-a3f8-2f30204d6561': ('Mur petit',  '#8a5a3a', 2, 0.3, 'wall'),
    '7c5edd5b-38fa-4c1a-aa39-99b5720a9171': ('Fenetre',    '#6ab0d8', 2, 0.3, 'window'),
    'ce1e617e-f031-4011-b64e-ba262082b20f': ('Coin',       '#4a2a10', 2, 2, 'corner'),
    'fd31ea7e-0b05-4caa-a3df-439c2e3b6a31': ('Escalier',   '#9040c0', 1, 1, 'stair'),
    '2e4e30de-485d-4f4c-a110-92ce364a2a6f': ('Toit plat',  '#c04030', 1, 1, 'roof'),
    '10727582-c251-4dc6-acbb-ec058d2bd80b': ('About pignon', '#e08030', 2, 2, 'ridge'),
    'bd1e0ed2-3315-48bc-bdcb-37cf15cf934e': ('Planche faitage', '#f0a050', 1, 2, 'ridge'),
    '1928adc8-1413-4026-ab36-d3db13415ed4': ('Mur pignon', '#c8a060', 1, 0.3, 'gablewall'),
    'baaf3839-0c43-42a2-9154-95f764b319a1': ('About niv.2', '#d06040', 2, 2, 'ridge2'),
    'baaf3839-0c43-42a2-9154-95f764b319a1': ('Toit redan',  '#d06040', 2, 2, 'roof'),
    'fb04f74e-fd7a-4243-92ba-30cdaba18574': ('Coin int.',  '#3a2a20', 1, 1, 'corner'),
}
DEFAULT_INFO = ('?', '#cccccc', 1, 1, 'autre')

CAT_ORDER = ['floor', 'corner', 'wall', 'window', 'stair', 'roof', 'ridge', 'autre']


def _draw_piece(ax, x, z, rot, w, d, color, alpha=0.85):
    angle = rot * 15.0
    rect = patches.Rectangle((x, z), w, d, linewidth=0.6, edgecolor='black',
                              facecolor=color, alpha=alpha, zorder=2)
    t = mtransforms.Affine2D().rotate_deg_around(x, z, angle) + ax.transData
    rect.set_transform(t)
    ax.add_patch(rect)
    # petite fleche pour indiquer l'orientation (face avant = +x local avant rotation)
    dx = 0.6 * np.cos(np.radians(angle))
    dz = 0.6 * np.sin(np.radians(angle))
    ax.annotate('', xy=(x + dx, z + dz), xytext=(x, z),
                arrowprops=dict(arrowstyle='->', color='black', lw=0.8), zorder=3)


def plot_floor_plan(data, y_level, title, asset_info=ASSET_INFO, tol=0.3):
    fig, ax = plt.subplots(figsize=(7, 7))
    used_labels = set()
    for guid, placements in data.items():
        name, color, w, d, cat = asset_info.get(guid, DEFAULT_INFO)
        for (x, y, z, rot) in placements:
            if abs(y - y_level) > tol:
                continue
            _draw_piece(ax, x, z, rot, w, d, color)
            if name not in used_labels:
                ax.plot([], [], 's', color=color, label=name)
                used_labels.add(name)
    ax.set_aspect('equal')
    ax.set_title(title)
    ax.set_xlabel('x')
    ax.set_ylabel('z')
    ax.invert_yaxis()
    ax.grid(True, linewidth=0.3, alpha=0.4)
    if used_labels:
        ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1.0), fontsize=8)
    fig.tight_layout()
    return fig


def plot_elevation(data, title, asset_info=ASSET_INFO):
    """Vue de cote (x vs y), toutes les tuiles projetees - utile pour verifier
    les hauteurs d'etage, du toit, de la faitiere."""
    fig, ax = plt.subplots(figsize=(8, 5))
    used_labels = set()
    for guid, placements in data.items():
        name, color, w, d, cat = asset_info.get(guid, DEFAULT_INFO)
        xs = [p[0] for p in placements]
        ys = [p[1] for p in placements]
        ax.scatter(xs, ys, c=color, s=30, label=name if name not in used_labels else None,
                   edgecolors='black', linewidths=0.4)
        used_labels.add(name)
    ax.set_xlabel('x')
    ax.set_ylabel('y (hauteur)')
    ax.set_title(title)
    ax.grid(True, linewidth=0.3, alpha=0.4)
    ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1.0), fontsize=8)
    fig.tight_layout()
    return fig


def all_y_levels(data, tol=0.05):
    ys = []
    for placements in data.values():
        for (x, y, z, rot) in placements:
            if not any(abs(y - yy) < tol for yy in ys):
                ys.append(y)
    return sorted(ys)


def render_all(data, prefix, out_dir='.'):
    """Genere un PNG par niveau Y (vue du dessus) + une elevation globale."""
    paths = []
    for y in all_y_levels(data):
        fig = plot_floor_plan(data, y, f'{prefix} — plan a y={y:.2f}')
        path = f'{out_dir}/{prefix}_plan_y{y:.2f}.png'.replace(' ', '_')
        fig.savefig(path, dpi=130)
        plt.close(fig)
        paths.append(path)
    fig = plot_elevation(data, f'{prefix} — elevation')
    path = f'{out_dir}/{prefix}_elevation.png'.replace(' ', '_')
    fig.savefig(path, dpi=130)
    plt.close(fig)
    paths.append(path)
    return paths
