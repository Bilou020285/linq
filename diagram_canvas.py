# -*- coding: utf-8 -*-
from qgis.PyQt import QtCore, QtGui, QtWidgets
from qgis.PyQt.QtCore import Qt, QPointF, QRectF, pyqtSignal
from qgis.PyQt.QtGui import QPainter, QPen, QBrush, QPainterPath, QPolygonF, QColor, QFont, QFontMetrics
from qgis.PyQt.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPathItem, QGraphicsObject, QMenu
from qgis.core import QgsProject
from collections import Counter, defaultdict

PX_PER_INCH = 96.0
RADIUS = 10.0
OFFSET = 18.0

PEN_NODE = QPen(QColor("#5f6b7a"), 1.2)
PEN_NODE_SEL = QPen(QColor("#2e7d32"), 2.0)
BRUSH_NODE = QBrush(QColor("#ffffff"))
BRUSH_NODE_LINK = QBrush(QColor("#FFEFD9"))

PEN_EDGE = QPen(QColor("#607d8b"), 1.2)
PEN_EDGE_HL = QPen(QColor("#1565c0"), 1.8)

def _layer_name(layer_id: str) -> str:
    lyr = QgsProject.instance().mapLayer(layer_id)
    return lyr.name() if lyr else layer_id

class NodeItem(QGraphicsObject):
    def __init__(self, node_id: str, label: str, w_px: float, h_px: float, is_link=False, parent=None):
        super().__init__(parent)
        self.node_id = node_id
        self.label = label or node_id
        fm = QFontMetrics(QFont())
        self.w = max(float(w_px), float(fm.horizontalAdvance(self.label) + 16), 80.0)
        self.h = max(float(h_px), float(fm.height() + 12), 36.0)
        self.is_link = is_link
        self.setFlags(self.ItemIsMovable | self.ItemIsSelectable | self.ItemSendsGeometryChanges)
        self.setCacheMode(self.DeviceCoordinateCache)
        self.edges = []

    def addEdge(self, e): self.edges.append(e)
    def boundingRect(self): return QRectF(-self.w/2, -self.h/2, self.w, self.h)
    def shape(self): p=QPainterPath(); p.addRoundedRect(self.boundingRect(),RADIUS,RADIUS); return p
    def paint(self, p:QPainter, option, widget=None):
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(PEN_NODE_SEL if self.isSelected() else PEN_NODE)
        p.setBrush(BRUSH_NODE_LINK if self.is_link else BRUSH_NODE)
        p.drawRoundedRect(self.boundingRect(), RADIUS, RADIUS)
        rect = self.boundingRect().adjusted(8,6,-8,-6); p.setPen(Qt.black)
        p.drawText(rect, Qt.AlignCenter|Qt.TextWordWrap, self.label)
    def itemChange(self, change, value):
        if change == self.ItemPositionHasChanged:
            for e in self.edges: e.updatePath()
        return super().itemChange(change, value)
    def anchorPointTowards(self, other_center: QPointF) -> QPointF:
        c = self.scenePos(); dx = other_center.x()-c.x(); dy = other_center.y()-c.y()
        if dx==0 and dy==0: return c
        import math
        ang = math.atan2(dy, dx); rx=self.w/2.0; ry=self.h/2.0
        cos=math.cos(ang); sin=math.sin(ang)
        tx = rx/abs(cos) if cos else float('inf'); ty = ry/abs(sin) if sin else float('inf')
        t=min(tx,ty)-2.0
        return QPointF(c.x()+cos*t, c.y()+sin*t)

class EdgeItem(QGraphicsPathItem):
    def __init__(self, src:NodeItem, dst:NodeItem, pairs=None, highlight=False, offset=0.0, parent=None):
        super().__init__(parent)
        self.src=src; self.dst=dst
        # pairs peut être : [(pk, fk)], [(parent, child, pk, fk)], etc. → on sera tolérant
        self.pairs = list(pairs or [])
        self.setZValue(-1)
        self.setPen(PEN_EDGE_HL if highlight else PEN_EDGE)
        self.setFlag(self.ItemIsSelectable, False)
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.LeftButton | Qt.RightButton)
        self.offset = offset
        self.updatePath()
        self.src.addEdge(self); self.dst.addEdge(self)
        self._refresh_tooltip()

    def _iter_pk_fk(self):
        """Yield (pk, fk) de manière robuste, quel que soit le format de self.pairs."""
        for entry in self.pairs:
            # tuple/list ?
            if isinstance(entry, (tuple, list)):
                if len(entry) >= 4:
                    # formats étendus possibles : (parentLayer, childLayer, pk, fk) ou (pk, fk, extra...)
                    pk, fk = entry[-2], entry[-1]
                    yield str(pk), str(fk)
                elif len(entry) >= 2:
                    pk, fk = entry[0], entry[1]
                    yield str(pk), str(fk)
                elif len(entry) == 1:
                    # un seul champ ? → afficher tel quel
                    yield str(entry[0]), ""
            else:
                # chaîne brute
                yield str(entry), ""
    def _refresh_tooltip(self):
        src_name = self.src.label; dst_name = self.dst.label
        lines = []
        any_pair = False
        for pk, fk in self._iter_pk_fk():
            any_pair = True
            if fk:
                lines.append(f"{src_name}.{pk} → {dst_name}.{fk}")
            else:
                lines.append(f"{src_name}.{pk}")
        self.setToolTip("\n".join(lines) if any_pair else f"{src_name} → {dst_name}")

    def _arrow(self, path:QPainterPath) -> QPolygonF:
        if path.elementCount()<2: return QPolygonF()
        e2=path.elementAt(path.elementCount()-1); e1=path.elementAt(path.elementCount()-2)
        tip=QPointF(e2.x, e2.y); import math
        ang=math.atan2(e2.y-e1.y, e2.x-e1.x); size=10.0
        left = QPointF(tip.x()-size*math.cos(ang-math.pi/6), tip.y()-size*math.sin(ang-math.pi/6))
        right= QPointF(tip.x()-size*math.cos(ang+math.pi/6), tip.y()-size*math.sin(ang+math.pi/6))
        return QPolygonF([tip,left,right])

    def updatePath(self):
        # self-loop ?
        if self.src is self.dst:
            c = self.src.scenePos(); w=self.src.w; h=self.src.h
            start = QPointF(c.x()+w/2, c.y())      # milieu droit
            cp1   = QPointF(c.x()+w/2+40, c.y()-h/2-40)
            cp2   = QPointF(c.x()-w/2-40, c.y()-h/2-40)
            end   = QPointF(c.x()-w/2, c.y())      # milieu gauche
            path = QPainterPath(start); path.cubicTo(cp1, cp2, end)
            self.setPath(path); self._arrowHead=self._arrow(path); return

        a = self.src.anchorPointTowards(self.dst.scenePos())
        b = self.dst.anchorPointTowards(self.src.scenePos())
        midx=(a.x()+b.x())/2.0; midy=(a.y()+b.y())/2.0

        dx = b.x()-a.x(); dy = b.y()-a.y()
        if abs(dx) >= abs(dy):
            c1 = QPointF(midx, a.y() - self.offset)
            c2 = QPointF(midx, b.y() + self.offset)
        else:
            c1 = QPointF(a.x() + self.offset, midy)
            c2 = QPointF(b.x() - self.offset, midy)

        path = QPainterPath(a); path.cubicTo(c1, c2, b)
        self.setPath(path); self._arrowHead=self._arrow(path)

    def paint(self, p:QPainter, option, widget=None):
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(self.pen()); p.setBrush(Qt.NoBrush); p.drawPath(self.path())
        p.setBrush(self.pen().color()); p.drawPolygon(self._arrowHead)

    def contextMenuEvent(self, ev:QtWidgets.QGraphicsSceneContextMenuEvent):
        m=QMenu()
        m.addSection("Champs référencés")
        added = False
        src_name = self.src.label; dst_name = self.dst.label
        for pk, fk in self._iter_pk_fk():
            added = True
            if fk:
                m.addAction(f"{src_name}.{pk} → {dst_name}.{fk}")
            else:
                m.addAction(f"{src_name}.{pk}")
        if not added:
            m.addAction("Aucun détail de champ disponible")
        m.exec_(ev.screenPos())

class DiagramCanvas(QGraphicsView):
    nodeClicked = pyqtSignal(str)
    nodeDoubleClicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QBrush(QColor("#ffffff")))
        self.setRenderHints(self.renderHints()|QPainter.Antialiasing|QPainter.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setDragMode(QGraphicsView.NoDrag)
        self.nodes={}; self.edges=[]

    def clearAll(self): self.scene().clear(); self.nodes.clear(); self.edges.clear()
    def wheelEvent(self, e): self.scale(1.15,1.15) if e.angleDelta().y()>0 else self.scale(1/1.15,1/1.15)

    def _node_under_pos(self, pos):
        pt=self.mapToScene(pos); item=self.scene().itemAt(pt, self.transform())
        while item and not isinstance(item, NodeItem): item=item.parentItem()
        return item

    def mousePressEvent(self, e):
        node=self._node_under_pos(e.pos())
        self.setDragMode(QGraphicsView.NoDrag if node else QGraphicsView.ScrollHandDrag)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e); self.setDragMode(QGraphicsView.NoDrag)

    def mouseDoubleClickEvent(self, e):
        if e.button()==Qt.LeftButton:
            node=self._node_under_pos(e.pos())
            if node: self.nodeDoubleClicked.emit(node.node_id)
        super().mouseDoubleClickEvent(e)

    def set_graph(self, plain_text:str, selected_ids=None, link_ids=None, edge_pairs_map=None):
        selected_ids = selected_ids or set(); link_ids=link_ids or set(); edge_pairs_map=edge_pairs_map or {}
        self.clearAll()

        nodes_raw, edges_raw = {}, []
        for raw in plain_text.splitlines():
            if not raw.strip(): continue
            parts=raw.strip().split(); kind=parts[0]
            if kind=="node" and len(parts)>=6:
                nid=parts[1]; x,y,w,h=map(float, parts[2:6])
                nodes_raw[nid]=(x*PX_PER_INCH, -y*PX_PER_INCH, w*PX_PER_INCH, h*PX_PER_INCH)
            elif kind=="edge" and len(parts)>=3:
                edges_raw.append((parts[1], parts[2]))

        for nid,(x,y,w,h) in nodes_raw.items():
            node=NodeItem(nid, _layer_name(nid), w, h, is_link=(nid in link_ids))
            node.setPos(x,y)
            if nid in selected_ids: node.setSelected(True)
            self.scene().addItem(node); self.nodes[nid]=node

        edge_set = set(edges_raw)
        bidir = set()
        for tail, head in edges_raw:
            if (head, tail) in edge_set and tail != head:
                bidir.add(frozenset((tail, head)))

        # NEW : gestion multi-arêtes (mêmes tail/head plusieurs fois)
        counts = Counter(edges_raw)
        seen = defaultdict(int)

        for tail, head in edges_raw:
            src = self.nodes.get(tail)
            dst = self.nodes.get(head)
            if not src or not dst:
                continue

            key = (tail, head)
            occ = seen[key]
            seen[key] += 1
            n = counts[key]

            # Base : séparation des bidirectionnelles
            off = 0.0
            if frozenset((tail, head)) in bidir:
                off = +OFFSET if tail < head else -OFFSET

            # NEW : séparation des arêtes parallèles (même direction)
            if n > 1 and tail != head:
                mid = (n - 1) / 2.0
                off += (occ - mid) * OFFSET

            # NEW : edge_pairs_map = liste par occurrence
            pairs = []
            lst = (edge_pairs_map or {}).get(key, [])

            # compat éventuelle si lst est encore "aplati" (ancienne version)
            if lst and isinstance(lst[0], (tuple, list)) and len(lst[0]) == 2 and not (lst and isinstance(lst[0][0], (tuple, list))):
                pairs = lst
            else:
                if occ < len(lst):
                    pairs = lst[occ]
                elif lst:
                    pairs = lst[-1]  # fallback
                else:
                    pairs = []

            e = EdgeItem(
                src, dst,
                pairs=pairs,
                highlight=(tail in selected_ids or head in selected_ids),
                offset=off
            )
            self.scene().addItem(e)
            self.edges.append(e)

        self._fit_scene()

    def _fit_scene(self):
        if not self.nodes: return
        rect=self.scene().itemsBoundingRect().adjusted(-60,-60,60,60)
        self.scene().setSceneRect(rect); self.fitInView(rect, Qt.KeepAspectRatio)