# -*- coding: utf-8 -*-
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set, Optional
from qgis.core import (
    QgsProject, QgsRelation, QgsVectorLayer, QgsFeature, QgsFeatureRequest
)

# ---------------------------------------------------------------------
# Modèle / Snapshot
# ---------------------------------------------------------------------

@dataclass
class RelationEdge:
    id: str
    parent_layer_id: str
    child_layer_id: str
    pairs: List[Tuple[str, str]]  # (parent_field, child_field)

@dataclass
class LayerNode:
    id: str
    name: str
    is_link_table: bool = False
    editable_extra_fields: Set[str] = field(default_factory=set)

@dataclass
class RelationsSnapshot:
    layers: Dict[str, LayerNode]
    edges: List[RelationEdge]

    @staticmethod
    def capture(project: QgsProject) -> 'RelationsSnapshot':
        relmgr = project.relationManager()
        layers: Dict[str, LayerNode] = {}
        edges: List[RelationEdge] = []

        for lyr in project.mapLayers().values():
            layers[lyr.id()] = LayerNode(id=lyr.id(), name=lyr.name())

        for rel in relmgr.relations().values():
            parent = rel.referencedLayer()
            child = rel.referencingLayer()
            if not parent or not child:
                continue
            pairs = _pairs_parent_child(rel)
            edges.append(RelationEdge(rel.id(), parent.id(), child.id(), pairs))

        # Détection tables de liaison (heuristique renforcée)
        detect_link_tables(project, layers, relmgr)
        return RelationsSnapshot(layers=layers, edges=edges)

# ---------------------------------------------------------------------
# Heuristique tables de liaison (Note A)
# ---------------------------------------------------------------------

def detect_link_tables(project: QgsProject, layers: Dict[str, LayerNode], relmgr):
    """
    Heuristique améliorée :
    - Une table est considérée comme "table de liaison" si elle a >= 2 relations ENTRANTES
      (même si elles pointent vers le même parent → cas réflexif via L)
    - ET si l'ensemble des PK de la table est inclus dans l'ensemble des champs FK impliqués.
    """
    child_map: Dict[str, List[QgsRelation]] = {}
    for rel in relmgr.relations().values():
        child = rel.referencingLayer()
        parent = rel.referencedLayer()
        if not child or not parent:
            continue
        child_map.setdefault(child.id(), []).append(rel)

    for child_id, rels in child_map.items():
        if len(rels) < 2:
            continue
        child_layer = project.mapLayer(child_id)
        if not isinstance(child_layer, QgsVectorLayer):
            continue

        pks = set(child_layer.dataProvider().pkAttributeIndexes())
        if not pks:
            continue

        fk_idx: Set[int] = set()
        for r in rels:
            for pk, fk in _pairs_parent_child(r):
                idx = child_layer.fields().indexOf(fk)
                if idx >= 0:
                    fk_idx.add(idx)

        if pks.issubset(fk_idx):
            node = layers.get(child_id)
            if node:
                node.is_link_table = True

# ---------------------------------------------------------------------
# Utilitaires relations (robustes au sens des paires)
# ---------------------------------------------------------------------

def _pairs_parent_child(rel: QgsRelation) -> List[Tuple[str, str]]:
    """
    Retourne une liste de paires (parent_field, child_field), quel que soit
    le sens renvoyé par rel.fieldPairs() selon ta version de QGIS.
    """
    pairs = []
    parent = rel.referencedLayer()
    child = rel.referencingLayer()
    if not parent or not child:
        return pairs

    fp = rel.fieldPairs()  # mapping, mais le sens peut varier selon versions
    for a, b in fp.items():
        # On veut (parent_field, child_field)
        # Si 'b' appartient au child, on garde (a, b), sinon on inverse.
        if child.fields().indexOf(b) != -1:
            pairs.append((a, b))
        elif child.fields().indexOf(a) != -1:
            pairs.append((b, a))
        else:
            # fallback: on tente tel quel
            pairs.append((a, b))
    return pairs

# ---------------------------------------------------------------------
# Fonctions exportées (utilisées par selected_panel.py)
# ---------------------------------------------------------------------

def find_direct_relation(project: QgsProject,
                         parent_layer: QgsVectorLayer,
                         child_layer: QgsVectorLayer) -> Optional[QgsRelation]:
    """Retourne la relation directe parent→enfant si elle existe, sinon None."""
    for r in project.relationManager().relations().values():
        p = r.referencedLayer()
        c = r.referencingLayer()
        if not p or not c:
            continue
        if p.id() == parent_layer.id() and c.id() == child_layer.id():
            return r
    return None

def find_link_table_between(project: QgsProject, layer_a: QgsVectorLayer, layer_b: QgsVectorLayer):
    """Compat: retourne le premier candidat s'il existe."""
    cands = find_link_tables_between(project, layer_a, layer_b)
    return cands[0] if cands else None

def children_for_relation(parent_feat: QgsFeature, rel: QgsRelation) -> List[QgsFeature]:
    """
    Renvoie la liste des entités enfants (layer enfant = rel.referencingLayer())
    dont les FK correspondent aux valeurs PK du parent_feat, d'après les paires.
    """
    child = rel.referencingLayer()
    if not isinstance(child, QgsVectorLayer) or not parent_feat or not parent_feat.isValid():
        return []
    pairs = _pairs_parent_child(rel)
    out: List[QgsFeature] = []
    req = QgsFeatureRequest()
    for f in child.getFeatures(req):
        ok = True
        for pk, fk in pairs:
            pv = parent_feat[pk] if pk in parent_feat.fields().names() else None
            try:
                cv = f[fk]
            except Exception:
                ok = False; break
            if pv != cv:
                ok = False; break
        if ok:
            out.append(f)
    return out

def set_child_fk(child_layer: QgsVectorLayer,
                 rel: QgsRelation,
                 parent_feat: QgsFeature,
                 child_feat: QgsFeature) -> bool:
    """
    Remplit les FK de child_feat (dans child_layer) en se basant sur parent_feat et la relation rel.
    Retourne True si l'update a réussi.
    """
    if not isinstance(child_layer, QgsVectorLayer):
        return False
    pairs = _pairs_parent_child(rel)
    if not child_layer.isEditable():
        child_layer.startEditing()

    f = QgsFeature(child_feat)
    for pk, fk in pairs:
        try:
            f[fk] = parent_feat[pk]
        except Exception:
            return False
    ok = child_layer.updateFeature(f)
    return bool(ok)

def new_prefilled_link_feature(link_layer: QgsVectorLayer,
                               rel_src: QgsRelation,
                               rel_tgt: QgsRelation,
                               src_feat: QgsFeature,
                               target_feat: QgsFeature) -> QgsFeature:
    """
    Crée une entité pour la table de liaison 'link_layer' avec les deux FK auto-remplies :
      - depuis src_feat via rel_src
      - depuis target_feat via rel_tgt
    """
    nf = QgsFeature(link_layer.fields())

    # Paires parent→enfant pour rel_src et rel_tgt, enfant = link_layer ici
    for pk, fk in _pairs_parent_child(rel_src):
        nf[fk] = src_feat[pk]
    for pk, fk in _pairs_parent_child(rel_tgt):
        nf[fk] = target_feat[pk]

    return nf
def find_link_tables_between(project: QgsProject,
                             layer_a: QgsVectorLayer,
                             layer_b: QgsVectorLayer):
    """Retourne une liste de candidats (L, r1, r2) où L est une table d'association
    telle que r1: parent=A, child=L et r2: parent=B, child=L. Cas réflexif accepté (A == B)."""
    rels = list(project.relationManager().relations().values())
    by_child = {}
    for r in rels:
        child = r.referencingLayer()
        parent = r.referencedLayer()
        if not child or not parent:
            continue
        by_child.setdefault(child.id(), []).append(r)

    out = []
    for L_id, lst in by_child.items():
        if len(lst) < 2:
            continue
        L = project.mapLayer(L_id)
        if not isinstance(L, QgsVectorLayer):
            continue
        n = len(lst)
        for i in range(n):
            for j in range(i+1, n):
                r1, r2 = lst[i], lst[j]
                p1, p2 = r1.referencedLayer(), r2.referencedLayer()
                if not p1 or not p2:
                    continue
                if ((p1.id() == layer_a.id() and p2.id() == layer_b.id()) or
                    (p1.id() == layer_b.id() and p2.id() == layer_a.id())):
                    out.append((L, r1, r2))
                if layer_a.id() == layer_b.id() and p1.id() == layer_a.id() and p2.id() == layer_a.id():
                    out.append((L, r1, r2))
    return out
