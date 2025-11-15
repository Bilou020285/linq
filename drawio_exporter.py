# -*- coding: utf-8 -*-
"""
drawio_exporter.py
Export LinQ -> .drawio (diagrams.net) avec boîtes "tables" repliables :
- Swimlane parent (collapsible) = en-tête nom de table
- Corps = grille 2 colonnes construite avec de vraies sous-cellules :
    [PK | FKx]  |  [nom_champ souligné]
- Tables N↔N : en-tête orangé
"""

from xml.sax.saxutils import escape as _esc, quoteattr as _qa

# ---- Thème (proche de ton exemple noir & blanc) ----------------------------
BORDER_OUT    = "#424242"
GRID_COLOR    = "#BDBDBD"
HEADER_NORM_BG= "#FFFFFF"
HEADER_NORM_FG= "#111111"
BODY_BG       = "#FFFFFF"

# Tables de liaison (N↔N) : petit repère visuel
HEADER_LINK_BG= "#FFE0B2"
HEADER_LINK_FG= "#111111"

EDGE_COLOR    = "#616161"
EDGE_STYLE = (
    "edgeStyle=orthogonalEdgeStyle;"
    "endArrow=block;endFill=1;"
    f"strokeColor={EDGE_COLOR};"
    "rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
    "labelBackgroundColor=#FFFFFF;fontSize=11;"
)

# ---------------------------------------------------------------------------

def _mx_header():
    return (
        '<mxfile host="app.diagrams.net">\n'
        '  <diagram id="linq-relations" name="LinQ">\n'
        '    <mxGraphModel dx="1280" dy="720" grid="1" gridSize="10" guides="1" '
        'tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1654" pageHeight="1169">\n'
        '      <root>\n'
        '        <mxCell id="0"/>\n'
        '        <mxCell id="1" parent="0"/>\n'
    )

def _mx_footer():
    return (
        '      </root>\n'
        '    </mxGraphModel>\n'
        '  </diagram>\n'
        '</mxfile>\n'
    )

def _gather_pk_fk(snapshot):
    """ {layer_id: {'pk': set(), 'fk': list()}} """
    pkfk = {lid: {'pk': set(), 'fk': []} for lid in snapshot.layers.keys()}
    for e in snapshot.edges:
        for p, c in e.pairs:
            pkfk[e.parent_layer_id]['pk'].add(p)
            if c not in pkfk[e.child_layer_id]['fk']:
                pkfk[e.child_layer_id]['fk'].append(c)
    return pkfk

def _grid_positions(n, start_x=40, start_y=40, cell_w=300, cell_h=170, cols=4):
    pos = []
    for i in range(n):
        r = i // cols
        c = i % cols
        pos.append((start_x + c * cell_w, start_y + r * cell_h))
    return pos

def build_drawio(snapshot, node_positions=None, style=None):
    """
    snapshot.layers: dict id->LayerNode(id, name, is_link_table)
    snapshot.edges: list RelationEdge(id, parent_layer_id, child_layer_id, pairs=[(pk, fk), ...])
    """
    id2name = {n.id: n.name for n in snapshot.layers.values()}
    pkfk = _gather_pk_fk(snapshot)

    layer_list = list(snapshot.layers.values())
    layer_list.sort(key=lambda n: n.name.lower())

    # positions
    if node_positions:
        pos_map, unknown = {}, []
        for n in layer_list:
            if n.id in node_positions:
                pos_map[n.id] = node_positions[n.id]
            else:
                unknown.append(n)
        if unknown:
            grid = _grid_positions(len(unknown))
            for i, n in enumerate(unknown):
                pos_map[n.id] = grid[i]
    else:
        grid = _grid_positions(len(layer_list))
        pos_map = {layer_list[i].id: grid[i] for i in range(len(layer_list))}

    # métriques
    header_h   = 28
    row_h      = 22
    left_w     = 56
    min_rows   = 1  # au moins la ligne "…"
    base_w     = 280

    def _box_wh(row_count):
        rows = max(min_rows, row_count + 1)    # +1 pour "…"
        h = header_h + rows * row_h
        return base_w, h

    out = []
    out.append(_mx_header())
    node_id_map = {}
    next_id = 2

    # --------- NŒUDS : swimlane + cellules "grille" internes -----------------
    for n in layer_list:
        lid   = n.id
        name  = n.name
        is_ln = bool(getattr(n, 'is_link_table', False))
        pk    = sorted(pkfk[lid]['pk'])
        fk    = list(pkfk[lid]['fk'])

        w, h  = _box_wh(len(pk) + len(fk))
        x, y  = pos_map[lid]

        head_bg = HEADER_LINK_BG if is_ln else HEADER_NORM_BG
        head_fg = HEADER_LINK_FG if is_ln else HEADER_NORM_FG

        swim_style = (
            "shape=swimlane;collapsible=1;fold=0;rounded=1;html=1;"
            f"strokeColor={BORDER_OUT};"
            f"fillColor={head_bg};fontColor={head_fg};"
            f"swimlaneFillColor={BODY_BG};"
            f"startSize={header_h};"
            "fontStyle=1;fontSize=12;"
        )

        swim_id = f"s_{next_id}"; next_id += 1
        node_id_map[lid] = swim_id
        out.append(
            f'        <mxCell id="{swim_id}" value={_qa(_esc(name))} style="{swim_style}" vertex="1" parent="1">\n'
            f'          <mxGeometry x="{int(x)}" y="{int(y)}" width="{w}" height="{h}" as="geometry"/>\n'
            '        </mxCell>\n'
        )

        # Génère les lignes : d'abord PK (peut en avoir plusieurs), puis FK1..n, puis "…"
        rows = []
        for p in pk:
            rows.append(("PK", p))
        for i, f in enumerate(sorted(fk), start=1):
            rows.append((f"FK{i}", f))
        rows.append(("", "…"))

        # Cellules internes : rectangles bordés pour dessiner la grille
        for r_idx, (tag, field) in enumerate(rows):
            # y absolu à l'intérieur du swimlane
            ry = header_h + r_idx * row_h

            # cellule gauche (PK / FKx)
            left_style = (
                "shape=rectangle;html=1;rounded=0;"
                f"strokeColor={GRID_COLOR};fillColor={BODY_BG};"
                "align=center;verticalAlign=middle;fontSize=11;fontStyle=0;"
            )
            left_id = f"l_{next_id}"; next_id += 1
            out.append(
                f'        <mxCell id="{left_id}" value={_qa(_esc(tag))} style="{left_style}" vertex="1" parent="{swim_id}">\n'
                f'          <mxGeometry x="0" y="{ry}" width="{left_w}" height="{row_h}" as="geometry"/>\n'
                '        </mxCell>\n'
            )

            # cellule droite (nom de champ souligné)
            right_style = (
                "shape=rectangle;html=1;rounded=0;"
                f"strokeColor={GRID_COLOR};fillColor={BODY_BG};"
                "align=left;verticalAlign=middle;spacingLeft=8;fontSize=11;"
            )
            field_html = f'<span style="text-decoration:underline">{_esc(field)}</span>' if field != "…" else "…"
            right_id = f"r_{next_id}"; next_id += 1
            out.append(
                f'        <mxCell id="{right_id}" value={_qa(field_html)} style="{right_style}" vertex="1" parent="{swim_id}">\n'
                f'          <mxGeometry x="{left_w}" y="{ry}" width="{w-left_w}" height="{row_h}" as="geometry"/>\n'
                '        </mxCell>\n'
            )

    # ---------------------- ARÊTES ------------------------------------------
    for e in snapshot.edges:
        src = node_id_map.get(e.parent_layer_id)
        tgt = node_id_map.get(e.child_layer_id)
        if not src or not tgt:
            continue
        parent_name = id2name.get(e.parent_layer_id, 'parent')
        child_name  = id2name.get(e.child_layer_id,  'child')
        label = '\n'.join([f'{parent_name}.{p} → {child_name}.{c}' for (p, c) in e.pairs])
        edge_id = f"e_{next_id}"; next_id += 1
        out.append(
            f'        <mxCell id="{edge_id}" value={_qa(label.replace("\n", "&#xa;"))} '
            f'style="{EDGE_STYLE}" edge="1" parent="1" source="{src}" target="{tgt}">\n'
            '          <mxGeometry relative="1" as="geometry"/>\n'
            '        </mxCell>\n'
        )

    out.append(_mx_footer())
    return ''.join(out).encode('utf-8')