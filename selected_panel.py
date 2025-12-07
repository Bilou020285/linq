# -*- coding: utf-8 -*-
__all__ = ["SelectionBoard"]

import json
from qgis.PyQt.QtCore import (
    Qt, QAbstractItemModel, QModelIndex, QSortFilterProxyModel,
    pyqtSignal, QMimeData, QPoint, QItemSelectionModel, QTimer
)
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit,
    QScrollArea, QTreeView, QMenu, QMessageBox, QStyle, QApplication, QCheckBox,
    QInputDialog, QSpinBox, QDialog, QDialogButtonBox, QTextEdit
)
from qgis.core import QgsProject, QgsVectorLayer, QgsFeature, QgsApplication
from .relation_utils import (
    find_direct_relation, children_for_relation, set_child_fk,
    new_prefilled_link_feature
)

MIME = 'application/x-linq-feature'

def _push_bar(iface, level, msg):
    try:
        if level == 'ok':
            iface.messageBar().pushSuccess('LinQ', msg)
        elif level == 'warn':
            iface.messageBar().pushWarning('LinQ', msg)
        else:
            iface.messageBar().pushCritical('LinQ', msg)
    except Exception:
        pass

NT_TOP_FEAT = 1
NT_REL_GROUP = 2
NT_CHILD_FEAT = 3

class Node:
    def __init__(self, label, node_type, layer=None, feature: QgsFeature=None, relation=None, parent=None):
        self.label = label
        self.node_type = node_type
        self.layer = layer
        self.feature = feature
        self.relation = relation
        self.parent = parent
        self.children = []
        self._loaded = False
    def append(self, child):
        child.parent = self; self.children.append(child)

class TreeModel(QAbstractItemModel):
    def __init__(self, column_widget, parent=None):
        super().__init__(parent)
        self.col = column_widget
        self.root = Node('root', 0)

    def rebuild(self):
        self.beginResetModel()
        self.root = Node('root', 0)
        lyr = self.col.layer
        selected_ids = self.col.provider_selected_ids()
        child_filter = self.col.provider_filter_children()

        # Limiteur top-level
        max_top = self.col.max_count()
        shown = 0

        for f in lyr.getFeatures():
            # stop si limite atteinte (>0 = limite active)
            if max_top > 0 and shown >= max_top:
                break

            label = self.col.format_label_for_layer(lyr, f)
            top = Node(label or str(f.id()), NT_TOP_FEAT, layer=lyr, feature=f, parent=self.root)

            # Groupes "→ couche_enfant"
            for rel in QgsProject.instance().relationManager().relations().values():
                if rel.referencedLayer() and rel.referencedLayer().id() == lyr.id():
                    child_layer = rel.referencingLayer()
                    if child_filter and child_layer and child_layer.id() not in selected_ids:
                        continue
                    grp = Node("→ " + child_layer.name(), NT_REL_GROUP, layer=child_layer, relation=rel, parent=top)
                    top.append(grp)

            self.root.append(top)
            shown += 1

        self.endResetModel()
        # MAJ du titre avec compteur
        try:
            self.col.update_title(shown)
        except Exception:
            pass

    def ensure_loaded(self, node: 'Node'):
        if node.node_type != NT_REL_GROUP or node._loaded:
            return
        parent_feat = node.parent.feature; rel = node.relation
        childs = children_for_relation(parent_feat, rel)
        for ch in childs:
            lbl = self.col.format_label_for_layer(node.layer, ch) or str(ch.id())
            node.append(Node(lbl, NT_CHILD_FEAT, layer=node.layer, feature=ch, relation=rel, parent=node))
        node._loaded = True

    def index(self, row, col, parent):
        parent_node = self.nodeFromIndex(parent)
        if 0 <= row < len(parent_node.children):
            return self.createIndex(row, col, parent_node.children[row])
        return QModelIndex()

    def parent(self, index):
        node = self.nodeFromIndex(index)
        if not node or not node.parent or node.parent == self.root:
            return QModelIndex()
        grand = node.parent.parent
        return self.createIndex(grand.children.index(node.parent), 0, node.parent)

    def rowCount(self, parent):
        node = self.nodeFromIndex(parent)
        if node.node_type == NT_REL_GROUP:
            self.ensure_loaded(node)
        return len(node.children)

    def columnCount(self, parent): return 1

    def data(self, index, role):
        node = self.nodeFromIndex(index)
        if role in (Qt.DisplayRole, Qt.EditRole):
            return node.label
        return None

    def flags(self, index):
        node = self.nodeFromIndex(index)
        fl = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if node.node_type in (NT_TOP_FEAT, NT_CHILD_FEAT):
            fl |= Qt.ItemIsDragEnabled
        return fl

    def nodeFromIndex(self, index):
        if index.isValid():
            return index.internalPointer()
        return self.root

    def featureAtIndex(self, index):
        node = self.nodeFromIndex(index)
        if node.node_type in (NT_TOP_FEAT, NT_CHILD_FEAT):
            return node.layer, node.feature
        return None, None

class FilterProxy(QSortFilterProxyModel):
    def __init__(self, col_widget):
        super().__init__(col_widget)
        self.col = col_widget
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
    def filterAcceptsRow(self, source_row, source_parent):
        idx = self.sourceModel().index(source_row, 0, source_parent)
        node = self.sourceModel().nodeFromIndex(idx)
        if node.node_type == NT_TOP_FEAT:
            return self.filterRegExp().isEmpty() or self.filterRegExp().indexIn(node.label) >= 0
        parent = node.parent
        while parent and parent.node_type != NT_TOP_FEAT and parent.parent:
            parent = parent.parent
        if not parent:
            return True
        return self.filterRegExp().isEmpty() or self.filterRegExp().indexIn(parent.label) >= 0

class FeatureTreeView(QTreeView):
    def __init__(self, model, proxy, host, iface, parent=None):
        super().__init__(parent)
        self.setModel(proxy)
        self.host = host; self.iface = iface
        self.setSelectionMode(self.ExtendedSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_menu)
        self.setHeaderHidden(True); self.setAlternatingRowColors(True); self.setAnimated(True)
        self.setCursor(Qt.OpenHandCursor)
        self._press_pos = None
        self.setDragDropMode(QTreeView.DragDrop)
        self.setAcceptDrops(True); self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.CopyAction)

    def _open_menu(self, pos: QPoint):
        idx = self.indexAt(pos)
        if not idx.isValid():
            return
        src_idx = self.model().mapToSource(idx)
        node = self.model().sourceModel().nodeFromIndex(src_idx)

        if node.node_type == NT_REL_GROUP:
            m = QMenu(self)
            sub = m.addMenu("Afficher le champ")

            # NEW : expression QGIS pour cette couche enfant
            a_expr = sub.addAction("[Expression QGIS…]")
            a_expr.triggered.connect(
                lambda: self.host.open_child_expression_builder(node.layer)
            )
            sub.addSeparator()

            a_id = sub.addAction("[ID]")
            a_id.triggered.connect(
                lambda: self.host.set_child_display_field(node.layer, "__ID__")
            )
            for fld in node.layer.fields():
                a = sub.addAction(fld.name())
                a.triggered.connect(
                    lambda _, name=fld.name(): self.host.set_child_display_field(node.layer, name)
                )
            m.exec_(self.mapToGlobal(pos))
            return

        m = QMenu(self)
        act_form = m.addAction("Ouvrir formulaire…")
        act_zoom = m.addAction("Zoomer vers l'entité")
        act_copy = m.addAction("Copier l'ID")
        if node.node_type == NT_CHILD_FEAT:
            m.addSeparator()
            act_detach = m.addAction("Détacher (mettre la FK à NULL)…")
        action = m.exec_(self.mapToGlobal(pos))
        if not action:
            return
        layer, feat = (node.layer, node.feature) if node.node_type in (NT_TOP_FEAT, NT_CHILD_FEAT) else (None, None)
        if action.text().startswith("Ouvrir formulaire") and layer and feat:
            self.iface.openFeatureForm(layer, feat, True)
        elif action == act_zoom and layer and feat:
            try:
                self.iface.mapCanvas().setExtent(feat.geometry().boundingBox()); self.iface.mapCanvas().refresh()
            except Exception:
                pass
        elif action == act_copy and layer and feat:
            QApplication.clipboard().setText(str(feat.id()))
        elif node.node_type == NT_CHILD_FEAT and action == act_detach:
            self.host.detach_child_node(node)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_pos = e.pos()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (e.buttons() & Qt.LeftButton) and self._press_pos:
            if (e.pos() - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
                idx = self.indexAt(self._press_pos)
                if idx.isValid():
                    if not self.selectionModel().isSelected(idx):
                        self.selectionModel().select(idx, QItemSelectionModel.ClearAndSelect)
                    self._perform_drag(); return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press_pos = None
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(e)

    def _perform_drag(self):
        sel = self.selectedIndexes()
        if not sel:
            _push_bar(self.iface, 'warn', 'Drag : aucune entité sélectionnée.'); return
        src = self.model().sourceModel()
        pairs = []
        for i in sel:
            lyr, f = src.featureAtIndex(self.model().mapToSource(i))
            if lyr and f:
                pairs.append((lyr, f))
        if not pairs:
            _push_bar(self.iface, 'warn', 'Drag : sélection non valable.'); return
        base_layer = pairs[0][0]
        fids = [f.id() for lyr, f in pairs if lyr.id() == base_layer.id()]
        payload = {'layer': base_layer.id(), 'fids': fids}
        mime = QMimeData(); mime.setData(MIME, json.dumps(payload).encode('utf-8'))
        from qgis.PyQt.QtGui import QDrag
        drag = QDrag(self); drag.setMimeData(mime)
        _push_bar(self.iface, 'ok', f'Drag depuis “{base_layer.name()}” ({len(fids)} sélectionnée[s]).')
        drag.exec_(Qt.CopyAction)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction(); _push_bar(self.iface, 'ok', 'DragEnter : format LinQ OK (vise une ligne).')
        else:
            _push_bar(self.iface, 'warn', 'DragEnter : format inconnu.')

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    def dropEvent(self, e):
        if not e.mimeData().hasFormat(MIME):
            _push_bar(self.iface, 'warn', 'Drop : pas de format LinQ.'); return
        data = json.loads(bytes(e.mimeData().data(MIME)).decode('utf-8'))
        idx = self.indexAt(e.pos())
        target_index = idx if idx.isValid() else None
        self.host.handle_drop(data, target_index)
        e.acceptProposedAction()

class ConfirmFKDialog(QDialog):
    def __init__(self, title, lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        lab = QLabel("Modifications proposées :")
        txt = QTextEdit(); txt.setReadOnly(True)
        # Affiche toutes les lignes, une par modification
        txt.setPlainText("\n".join(lines) if lines else "(aucune)")
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(lab); lay.addWidget(txt, 1); lay.addWidget(btns)

    @staticmethod
    def ask(parent, title, lines):
        d = ConfirmFKDialog(title, lines, parent)
        return d.exec_() == QDialog.Accepted

class ColumnWidget(QWidget):
    request_refresh_diagram = pyqtSignal()
    request_remove = pyqtSignal(object)

    def __init__(self, layer, iface, selected_ids_provider, child_filter_provider, max_provider, parent=None, instance_index=1, board=None):
        super().__init__(parent)  # parent = widget intérieur du QScrollArea
        self.board = board
        self.layer = layer; self.iface = iface
        self.instance_index = instance_index
        self._selected_ids_provider = selected_ids_provider
        self._child_filter_provider = child_filter_provider
        self._max_provider = max_provider
        self.display_field = None; self.display_expr = None
        self.child_display_field = {}
        self.child_display_expr = {}   # <- NEW : expressions pour les couches enfants
        self._expanded = set()

        root = QVBoxLayout(self)

        # Barre d’actions
        bar = QHBoxLayout()
        self.title = QLabel(f"<b>{layer.name()} #{instance_index}</b>")
        self.filter = QLineEdit(); self.filter.setPlaceholderText('Filtrer…')

        self.btnToggle = QPushButton(); self.btnToggle.setToolTip('Activer/Désactiver édition (cette couche)')
        self.btnSave = QPushButton(); self.btnSave.setToolTip('Enregistrer les modifications (cette couche)')
        self.btnCancel = QPushButton(); self.btnCancel.setToolTip('Annuler les modifications (cette couche)')
        self.btnClose = QPushButton(); self.btnClose.setToolTip('Retirer cette colonne')
        self.btnCollapse = QPushButton(); self.btnCollapse.setToolTip('Tout replier')
        self.btnExpand = QPushButton(); self.btnExpand.setToolTip('Tout déplier')

        try:
            self.btnCollapse.setIcon(QgsApplication.getThemeIcon("/mActionCollapseTree.svg"))
            self.btnExpand.setIcon(QgsApplication.getThemeIcon("/mActionExpandTree.svg"))
            self.btnToggle.setIcon(self.iface.actionToggleEditing().icon())
            self.btnSave.setIcon(self.iface.actionSaveActiveLayerEdits().icon())
            self.btnCancel.setIcon(self.iface.actionRollbackEdits().icon())
            self.btnClose.setIcon(self.style().standardIcon(QStyle.SP_DockWidgetCloseButton))
        except Exception:
            self.btnClose.setText('✕')

        bar.addWidget(self.title); bar.addStretch(1); bar.addWidget(self.filter)
        bar.addWidget(self.btnCollapse); bar.addWidget(self.btnExpand)
        bar.addWidget(self.btnToggle); bar.addWidget(self.btnSave); bar.addWidget(self.btnCancel); bar.addWidget(self.btnClose)
        root.addLayout(bar)

        # Affichage (champ / expression)
        row2 = QHBoxLayout()
        self.fieldCombo = QComboBox()
        self.fieldCombo.addItem('[Expression QGIS…]')
        self.fieldCombo.addItem('[ID]')
        for f in self.layer.fields():
            self.fieldCombo.addItem(f.name())
        self.exprEdit = QLineEdit(); self.exprEdit.setPlaceholderText("Ex: coalesce(nom, code) || ' - ' || id")
        self.btnExpr = QPushButton(); self.btnExpr.setToolTip("Ouvrir le générateur d’expression (QGIS)")
        try:
            self.btnExpr.setIcon(QgsApplication.getThemeIcon("/mIconExpression.svg"))
        except Exception:
            self.btnExpr.setText("fx")
        row2.addWidget(QLabel('Afficher :'))
        row2.addWidget(self.fieldCombo, 1)
        row2.addWidget(self.btnExpr)
        row2.addWidget(self.exprEdit, 2)
        root.addLayout(row2)

        # Vue arborescente
        self.model = TreeModel(self)
        self.proxy = FilterProxy(self); self.proxy.setSourceModel(self.model)
        self.view = FeatureTreeView(self.model, self.proxy, self, self.iface, self)
        root.addWidget(self.view, 1)

        # Liaisons
        self.filter.textChanged.connect(self.proxy.setFilterFixedString)
        self.fieldCombo.currentIndexChanged.connect(self._onDisplayChoice)
        self.exprEdit.textEdited.connect(self._onExprChanged)
        self.btnExpr.clicked.connect(self.open_expression_builder)
        self.btnToggle.clicked.connect(self._toggle_edit)
        self.btnSave.clicked.connect(self._save_edits)
        self.btnCancel.clicked.connect(self._cancel_edits)
        self.btnClose.clicked.connect(lambda: self.request_remove.emit(self))
        self.btnCollapse.clicked.connect(self._collapse_all)
        self.btnExpand.clicked.connect(self._expand_all)

        try:
            # État d'édition
            layer.editingStarted.connect(self._update_edit_style)
            layer.editingStopped.connect(self._update_edit_style)
            layer.editCommandEnded.connect(self._update_edit_style)
            # Commits
            layer.committedAttributesChanged.connect(lambda *a: self._update_edit_style())
            layer.committedFeaturesAdded.connect(lambda *a: self._update_edit_style())
            # PATCH: signaux "dirty" pendant édition + commits remove
            layer.attributeValueChanged.connect(self._on_layer_dirty)
            layer.featureAdded.connect(self._on_layer_dirty)
            layer.featuresDeleted.connect(self._on_layer_dirty)
            layer.committedAttributeValuesChanges.connect(self._on_layer_committed)
            layer.committedFeaturesRemoved.connect(self._on_layer_committed)
        except Exception:
            pass

        # Replié par défaut, puis on laisse l’utilisateur gérer l’état
        self.model.rebuild()
        self.view.collapseAll()
        self._update_edit_style()

        # Mémorisation de l’état expand/collapse
        self.view.expanded.connect(lambda idx: self._expanded.add(self._key_for_index(self.proxy.mapToSource(idx))))
        self.view.collapsed.connect(lambda idx: self._expanded.discard(self._key_for_index(self.proxy.mapToSource(idx))))

    # providers (depuis le board)
    def provider_selected_ids(self):
        return self._selected_ids_provider()
    def provider_filter_children(self):
        return self._child_filter_provider()
    def max_count(self) -> int:
        try:
            v = int(self._max_provider())
            return v if v >= 0 else 0
        except Exception:
            return 0

    # ----- état expand/collapse -----
    def _key_for_node(self, node):
        if node.node_type == NT_TOP_FEAT:
            return ('T', self.layer.id(), int(node.feature.id()))
        if node.node_type == NT_REL_GROUP:
            return ('G', node.relation.id(), int(node.parent.feature.id()))
        if node.node_type == NT_CHILD_FEAT:
            return ('C', node.layer.id(), int(node.feature.id()), node.relation.id(), int(node.parent.parent.feature.id()))
        return None

    def _key_for_index(self, src_idx):
        node = self.model.nodeFromIndex(src_idx)
        return self._key_for_node(node)

    def _save_expand_state(self):
        self._expanded.clear()
        def rec(parent_idx):
            for r in range(self.model.rowCount(parent_idx)):
                idx = self.model.index(r, 0, parent_idx)
                px = self.proxy.mapFromSource(idx)
                if self.view.isExpanded(px):
                    k = self._key_for_index(idx)
                    if k:
                        self._expanded.add(k)
                rec(idx)
        rec(QModelIndex())

    def _restore_expand_state(self):
        def rec(parent_idx):
            for r in range(self.model.rowCount(parent_idx)):
                idx = self.model.index(r, 0, parent_idx)
                k = self._key_for_index(idx)
                px = self.proxy.mapFromSource(idx)
                if k in self._expanded:
                    self.view.setExpanded(px, True)
                rec(idx)
        rec(QModelIndex())

    def rebuild(self):
        # On ne force plus d'expansion : on restaure seulement l'état utilisateur
        self._save_expand_state()
        self.model.rebuild()
        self.view.collapseAll()            # sécurité visuelle si l’état est vide
        self._restore_expand_state()

    def update_title(self, shown=None):
        try:
            total = int(self.layer.featureCount())
        except Exception:
            total = 0
        if shown is None:
            txt = f"<b>{self.layer.name()} #{self.instance_index}</b>"
        else:
            txt = f"<b>{self.layer.name()} #{self.instance_index}</b> (affiche {shown} / {total})"
        self.title.setText(txt)

    # ----- style édition -----
    def _update_edit_style(self, *args):
        lyr = self.layer
        editable = bool(lyr.isEditable())
        dirty = False
        if editable:
            try:
                dirty = bool(lyr.isModified())
            except Exception:
                buf = lyr.editBuffer()
                dirty = bool(buf and (buf.changedAttributeValues() or buf.addedFeatures() or buf.deletedFeatureIds()))
        self.btnToggle.setChecked(editable)
        # Rouge si édition en cours + changements non enregistrés
        if editable and dirty:
            self.btnToggle.setStyleSheet("QPushButton { color: white; background:#d11; }")
            self.btnToggle.setToolTip("Éditions en attente d’enregistrement")
        else:
            self.btnToggle.setStyleSheet("")
            self.btnToggle.setToolTip("Basculer le mode édition")

    # PATCH: callbacks dirty/commit
    def _on_layer_dirty(self, *args):
        self._update_edit_style()
        if self.board:
            self.board.refresh_edit_state_for(self.layer)

    def _on_layer_committed(self, *args):
        self._update_edit_style()
        if self.board:
            self.board.refresh_edit_state_for(self.layer)

    # ----- formatages -----
    def format_label(self, layer, feat):
        if self.display_expr:
            try:
                from qgis.core import QgsExpression, QgsExpressionContext, QgsExpressionContextUtils
                expr = QgsExpression(self.display_expr)
                ctx = QgsExpressionContext()
                ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
                ctx.setFeature(feat)
                val = expr.evaluate(ctx)
                return "" if val is None else str(val)
            except Exception:
                pass
        if self.display_field and self.display_field in feat.fields().names():
            v = feat[self.display_field]; return "" if v is None else str(v)
        for fld in layer.fields():
            v = feat[fld.name()]
            if v is not None:
                return str(v)
        return str(feat.id())

    def format_label_for_layer(self, layer, feat):
        # 1) Expression spécifique pour cette couche enfant ?
        expr = self.child_display_expr.get(layer.id())
        if expr:
            try:
                from qgis.core import (
                    QgsExpression, QgsExpressionContext, QgsExpressionContextUtils
                )
                e = QgsExpression(expr)
                if not e.hasParserError():
                    ctx = QgsExpressionContext()
                    ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
                    ctx.setFeature(feat)
                    val = e.evaluate(ctx)
                    if not e.hasEvalError():
                        return "" if val is None else str(val)
            except Exception:
                pass  # en cas de souci, on retombe sur le comportement standard

        # 2) Sinon, champ choisi pour cette couche enfant
        chosen = self.child_display_field.get(layer.id())
        if chosen == "__ID__":
            return str(feat.id())
        if chosen:
            try:
                v = feat[chosen]; return "" if v is None else str(v)
            except Exception:
                pass

        # 3) Sinon, formatage général de la colonne
        return self.format_label(layer, feat)

    def set_child_display_field(self, child_layer, field_name_or_id):
        if field_name_or_id not in ("__ID__",) and field_name_or_id not in child_layer.fields().names():
            return
        # Choix d'un champ → on oublie l'éventuelle expression pour cette couche
        self.child_display_expr.pop(child_layer.id(), None)
        self.child_display_field[child_layer.id()] = field_name_or_id
        self.rebuild()

    def set_child_display_expression(self, child_layer, expr: str):
        """Définit une expression QGIS pour les entités enfants de cette couche."""
        lid = child_layer.id()
        expr = (expr or "").strip()
        if not expr:
            # Expression vide → on l'enlève
            self.child_display_expr.pop(lid, None)
        else:
            self.child_display_expr[lid] = expr
        # Une expression a priorité sur le champ → on oublie le champ sélectionné
        self.child_display_field.pop(lid, None)
        self.rebuild()

    # ----- Export HTML (section pour cette colonne) -----
    def to_html_section(self) -> str:
        """
        Construit un fragment HTML représentant cette colonne :
        - titre de la couche
        - arbre filtré (selon le proxy) dans des <ul><li>
        - le label de chaque noeud est self.model / self.proxy (donc respect
          le champ / expression / filtre définis par l'utilisateur·ice).
        """

        def esc(s):
            if s is None:
                return ""
            return (
                str(s)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )

        proxy = self.proxy
        model = self.model

        # Si rien n'est affiché dans la colonne, on retourne une petite note
        if proxy.rowCount() == 0:
            title_txt = esc(self.layer.name())
            return f"<h2>{title_txt}</h2><p class='meta'><i>Aucune entité affichée dans cette colonne.</i></p>"

        def recurse(proxy_index):
            # proxy_index : index dans le proxy -> on récupère le Node source
            src_index = proxy.mapToSource(proxy_index)
            node = model.nodeFromIndex(src_index)
            label = esc(node.label)

            # Enfants visibles (après filtrage du proxy)
            child_count = proxy.rowCount(proxy_index)
            if child_count == 0:
                return f"<li>{label}</li>"

            html = [f"<li>{label}<ul>"]
            for row in range(child_count):
                child_proxy_index = proxy.index(row, 0, proxy_index)
                html.append(recurse(child_proxy_index))
            html.append("</ul></li>")
            return "".join(html)

        # Titre : on nettoie un peu le titre HTML (<b>...</b>) pour le rapport
        raw_title = self.title.text() or self.layer.name()
        # On enlève grossièrement les balises <b> éventuelles
        clean_title = raw_title.replace("<b>", "").replace("</b>", "")
        h = [f"<h2>{esc(clean_title)}</h2>"]

        # Arbre : racine = index invalide, on parcourt les lignes de premier niveau
        h.append("<details open><summary>Entités et relations</summary><ul>")
        for r in range(proxy.rowCount()):
            idx = proxy.index(r, 0)
            h.append(recurse(idx))
        h.append("</ul></details>")

        return "\n".join(h)

    # ----- Expression Builder -----
    def _open_qgis_expression_dialog(self, layer, initial_expr, window_title):
        ExprDlg = None
        try:
            from qgis.gui import QgsExpressionDialog as ExprDlg  # type: ignore
        except Exception:
            try:
                from qgis.gui import QgsExpressionBuilderDialog as ExprDlg  # type: ignore
            except Exception:
                ExprDlg = None
        if ExprDlg is None:
            QMessageBox.warning(
                self,
                "Indisponible",
                "Le générateur d’expression n’est pas disponible dans cet environnement."
            )
            return None

        try:
            dlg = ExprDlg(layer, initial_expr or "", self)
            if hasattr(dlg, 'setWindowTitle'):
                dlg.setWindowTitle(window_title)
        except TypeError:
            dlg = ExprDlg(self)
            if hasattr(dlg, 'setLayer'):
                dlg.setLayer(layer)
            if hasattr(dlg, 'setExpressionText'):
                dlg.setExpressionText(initial_expr or "")
            if hasattr(dlg, 'setWindowTitle'):
                dlg.setWindowTitle(window_title)

        if dlg.exec_():
            if hasattr(dlg, 'expressionText'):
                return dlg.expressionText()
            elif hasattr(dlg, 'expression'):
                return dlg.expression()
        return None

    def open_expression_builder(self):
        new_expr = self._open_qgis_expression_dialog(
            self.layer,
            self.display_expr,
            "Expression d’affichage (QGIS)"
        )
        if new_expr is not None:
            self.fieldCombo.setCurrentIndex(0)  # [Expression QGIS…]
            self.exprEdit.setText(new_expr)
            self.display_field = None
            self.display_expr = new_expr
            self.rebuild()

    def open_child_expression_builder(self, child_layer):
        """Ouvre le générateur d'expression pour une couche enfant (relation)."""
        current = self.child_display_expr.get(child_layer.id())
        new_expr = self._open_qgis_expression_dialog(
            child_layer,
            current,
            f"Expression d’affichage (enfants de « {child_layer.name()} »)"
        )
        if new_expr is not None:
            self.set_child_display_expression(child_layer, new_expr)

    # ----- édition -----
    def _ensure_edit_with_prompt(self, layer: QgsVectorLayer) -> bool:
        if layer.isEditable():
            return True
        ans = QMessageBox.question(self, "Activer le mode édition ?",
                                   f"Activer le mode édition pour « {layer.name()} » ?",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if ans == QMessageBox.Yes:
            ok = layer.startEditing()
            if not ok:
                QMessageBox.warning(self, "Échec", f"Impossible d’activer l’édition sur « {layer.name()} ».")
            else:
                # PATCH: maj immédiate des crayons concernés
                if self.board:
                    self.board.refresh_edit_state_for(layer)
                else:
                    self._update_edit_style()
            return ok
        return False

    def _ask_commit(self, layer: QgsVectorLayer):
        if not layer.isEditable():
            return
        ans = QMessageBox.question(self, "Enregistrer les modifications ?",
                                   f"Enregistrer maintenant les modifications sur « {layer.name()} » ?",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans == QMessageBox.Yes:
            ok = layer.commitChanges()
            if not ok:
                QMessageBox.warning(self, "Échec", f"Échec de l’enregistrement sur « {layer.name()} ».")
            else:
                _push_bar(self.iface, 'ok', f"Modifications enregistrées sur « {layer.name()} ».")
        self._update_edit_style()

    def _toggle_edit(self):
        self.iface.setActiveLayer(self.layer)
        self.iface.actionToggleEditing().trigger()
        self._update_edit_style()

    def _save_edits(self):
        self.iface.setActiveLayer(self.layer)
        self.iface.actionSaveActiveLayerEdits().trigger()
        self._update_edit_style()

    def _cancel_edits(self):
        self.iface.setActiveLayer(self.layer)
        self.iface.actionRollbackEdits().trigger()
        self._update_edit_style()

    def _onDisplayChoice(self):
        txt = self.fieldCombo.currentText()
        if txt == '[Expression QGIS…]':
            self.display_field = None; self.display_expr = self.exprEdit.text().strip() or None
        elif txt == '[ID]':
            self.display_field = None; self.display_expr = None
        else:
            self.display_field = txt; self.display_expr = None
        self.rebuild()
        self.request_refresh_diagram.emit()

    def _onExprChanged(self, _):
        if self.fieldCombo.currentText() == '[Expression QGIS…]':
            self.display_expr = self.exprEdit.text().strip() or None
            self.rebuild()

    def _collapse_all(self):
        self.view.collapseAll()
        self._expanded.clear()

    def _expand_all(self):
        self.view.expandAll()
        self._save_expand_state()

    def _mb(self, text, level=0):
        _push_bar(self.iface, 'ok' if level == 0 else ('warn' if level == 1 else 'err'), text)

    def reload(self):
        """Reload entities displayed in this column."""
        try:
            self.rebuild()
        except Exception:
            pass

    def detach_child_node(self, node):
        rel = node.relation; link_or_child_layer = node.layer; link_or_child_feat = node.feature
        parent_layer = self.layer
        if not rel or not link_or_child_layer or not link_or_child_feat:
            return

        # Table d’association ?
        relmgr = QgsProject.instance().relationManager()
        rels_with_same_child = [r for r in relmgr.relations().values()
                                if r.referencingLayer() and r.referencingLayer().id() == link_or_child_layer.id()]
        is_link_table = len(rels_with_same_child) >= 2

        if is_link_table:
            if not self._ensure_edit_with_prompt(link_or_child_layer):
                return
            ans = QMessageBox.question(
                self, "Supprimer l'association ?",
                f"La ligne sélectionnée appartient à la table d’association « {link_or_child_layer.name()} ».\n"
                f"Supprimer cette association ?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if ans == QMessageBox.Yes:
                ok = link_or_child_layer.deleteFeature(link_or_child_feat.id())
                link_or_child_layer.triggerRepaint()
                self._mb("Association supprimée." if ok else "Échec de la suppression.", 0 if ok else 2)
                if ok:
                    self._ask_commit(link_or_child_layer)
                self.rebuild()
            return

        # 1→N : mettre toutes les FK à NULL
        child_layer = link_or_child_layer
        child_feat = link_or_child_feat
        if not self._ensure_edit_with_prompt(child_layer):
            return
        changed = 0
        for fk, pk in rel.fieldPairs().items():
            idx = child_layer.fields().indexOf(fk)
            if idx >= 0 and child_layer.changeAttributeValue(child_feat.id(), idx, None):
                changed += 1
        child_layer.triggerRepaint()
        self._mb(f"FK remise à NULL ({changed} champ[s]).")
        self._ask_commit(child_layer)
        self.rebuild()

    def handle_drop(self, payload, target_index=None):
        try:
            src_id = payload['layer']; ids = payload['fids']
        except Exception:
            self._mb('Payload drop invalide.', 2); return

        src_layer = QgsProject.instance().mapLayer(src_id)
        if not src_layer or not isinstance(src_layer, QgsVectorLayer):
            self._mb('Couche source introuvable ou non vectorielle.', 2); return

        def resolve_target_feat():
            if target_index is not None and target_index.isValid():
                src_idx = self.proxy.mapToSource(target_index)
                layer, feat = self.model.featureAtIndex(src_idx)
                if layer and feat and layer.id() == self.layer.id():
                    return feat
            sels = self.view.selectionModel().selectedIndexes()
            for i in sels:
                lyr, f = self.model.featureAtIndex(self.proxy.mapToSource(i))
                if lyr and f and lyr.id() == self.layer.id():
                    return f
            return None

        tgt_layer = self.layer

        # ---------- Parent -> Child (1→N) : on pose la FK sur la couche source ----------
        rel_pc = find_direct_relation(QgsProject.instance(), parent_layer=tgt_layer, child_layer=src_layer)
        if rel_pc:
            parent_feat = resolve_target_feat()
            if not parent_feat:
                self._mb('Choisis (ou vise) une entité dans la colonne cible (parent).', 1); return
            if not self._ensure_edit_with_prompt(src_layer):
                return

            # Prévisualisation claire des changements
            pairs = list(rel_pc.fieldPairs().items())  # [(pk_parent, fk_child), ...]
            lines = []
            for fid in ids:
                ch = src_layer.getFeature(fid)
                if not ch.isValid():
                    continue
                # PATCH: libellé de la colonne source (exactement comme affiché)
                label = self.board.label_for(src_layer, ch) if self.board else self.format_label_for_layer(src_layer, ch)
                for pk, fk in pairs:
                    old = ch[fk] if fk in ch.fields().names() else None
                    new = parent_feat[pk] if pk in parent_feat.fields().names() else None
                    old_s = "NULL" if old in (None, "") else str(old)
                    new_s = "NULL" if new in (None, "") else str(new)
                    lines.append(f'{label} : {fk}  {old_s} → {new_s}')

            if not ConfirmFKDialog.ask(self, "Confirmer les mises à jour (1→N)", lines):
                return

            # Application des changements (sans commit auto)
            changed = 0
            for fid in ids:
                ch = src_layer.getFeature(fid)
                if ch.isValid() and set_child_fk(src_layer, rel_pc, parent_feat, ch):
                    changed += 1

            src_layer.triggerRepaint()
            self._mb(f'Relation posée (1→N) sur {changed} entité(s). Enregistre quand tu veux.')
            # PATCH: maj des crayons de toutes les colonnes affichant cette couche
            if self.board:
                self.board.refresh_edit_state_for(src_layer)
            else:
                self._update_edit_style()
            self.rebuild()
            return

        # ---------- Child -> Parent (1→N) : on pose la FK sur la couche cible ----------
        rel_cp = find_direct_relation(QgsProject.instance(), parent_layer=src_layer, child_layer=tgt_layer)
        if rel_cp:
            child_feat = resolve_target_feat()
            if not child_feat:
                self._mb('Choisis (ou vise) une entité dans la colonne cible (enfant).', 1); return
            if not self._ensure_edit_with_prompt(tgt_layer):
                return

            parent_feat = src_layer.getFeature(ids[0])
            if not parent_feat.isValid():
                self._mb('Entité parent invalide.', 2); return

            # Prévisualisation claire des changements (un enfant visé)
            pairs = list(rel_cp.fieldPairs().items())  # [(pk_parent, fk_child), ...]
            label = self.format_label_for_layer(tgt_layer, child_feat)
            lines = []
            for pk, fk in pairs:
                old = child_feat[fk] if fk in child_feat.fields().names() else None
                new = parent_feat[pk] if pk in parent_feat.fields().names() else None
                old_s = "NULL" if old in (None, "") else str(old)
                new_s = "NULL" if new in (None, "") else str(new)
                lines.append(f'{label} : {fk}  {old_s} → {new_s}')

            if not ConfirmFKDialog.ask(self, "Confirmer les mises à jour (1→N)", lines):
                return

            ok = set_child_fk(tgt_layer, rel_cp, parent_feat, child_feat)
            tgt_layer.triggerRepaint()
            self._mb('Relation posée (1→N). Enregistre quand tu veux.' if ok else 'Échec de la mise à jour (1→N).',
                     0 if ok else 2)
            if self.board:
                self.board.refresh_edit_state_for(tgt_layer)
            else:
                self._update_edit_style()
            self.rebuild()
            return

        # ---------- N↔N via table d’association (auto-FK) ----------
        from .relation_utils import find_link_tables_between
        cands = find_link_tables_between(QgsProject.instance(), src_layer, tgt_layer)
        if cands:
            L = None
            rel_src = None
            rel_tgt = None

            # 1) Choix / détection de la table d'association
            if len(cands) == 1:
                L, r1, r2 = cands[0]
                if r1.referencedLayer().id() == src_layer.id():
                    rel_src, rel_tgt = r1, r2
                else:
                    rel_src, rel_tgt = r2, r1
            else:
                options = []
                mapping = []
                for (Lk, r1, r2) in cands:
                    p1 = r1.referencedLayer().name() if r1.referencedLayer() else "?"
                    p2 = r2.referencedLayer().name() if r2.referencedLayer() else "?"
                    fp1 = ", ".join([f"{pk}->{fk}" for pk, fk in r1.fieldPairs().items()])
                    fp2 = ", ".join([f"{pk}->{fk}" for pk, fk in r2.fieldPairs().items()])
                    label = f"{Lk.name()}  ⟦ {p1}[{fp1}] + {p2}[{fp2}] ⟧"
                    options.append(label)
                    mapping.append((Lk, r1, r2))

                choice, ok = QInputDialog.getItem(
                    self,
                    "Choisir la table d’association",
                    "Plusieurs tables d’association relient ces deux couches :",
                    options,
                    0,
                    False
                )
                if not ok:
                    return
                sel_idx = options.index(choice)
                L, r1, r2 = mapping[sel_idx]
                if r1.referencedLayer().id() == src_layer.id():
                    rel_src, rel_tgt = r1, r2
                else:
                    rel_src, rel_tgt = r2, r1

            # 2) Entité cible (celle sur laquelle on a lâché le drag)
            target_feat = resolve_target_feat()
            if not target_feat:
                self._mb('Choisis (ou vise) une entité dans la colonne cible.', 1)
                return

            if not self._ensure_edit_with_prompt(L):
                return

            created_links = []

            # 3) Pour CHAQUE entité glissée, on crée une ligne dans la table d’assoc
            for fid in ids:
                src_feat = src_layer.getFeature(fid)
                if not src_feat.isValid():
                    continue

                try:
                    link_feat = new_prefilled_link_feature(L, rel_src, rel_tgt, src_feat, target_feat)
                except KeyError as ex:
                    self._mb(f"FK introuvable dans la table d’association : {ex}", 2)
                    continue

                if not L.addFeature(link_feat):
                    continue

                # On essaie de récupérer la version "vue par la couche"
                try:
                    persisted = L.getFeature(link_feat.id())
                except Exception:
                    persisted = link_feat

                if persisted and persisted.isValid():
                    created_links.append(persisted)
                else:
                    created_links.append(link_feat)

            if not created_links:
                self._mb("Impossible d’ajouter dans la table d’association.", 2)
                return

            # 4) Mise à jour visuelle / crayons
            L.triggerRepaint()
            if self.board:
                self.board.refresh_edit_state_for(L)
            else:
                self._update_edit_style()

            # 5) Ouvrir les formulaires un par un pour chaque liaison créée
            try:
                for feat in created_links:
                    if feat and feat.isValid():
                        # Formulaire projet, en édition, modal
                        self.iface.openFeatureForm(L, feat, True)
            except Exception:
                pass

            self._mb(
                f"{len(created_links)} ligne(s) d’association créée(s) (FK auto-remplies). "
                "Enregistre quand tu veux."
            )
            return

        self._mb('Aucune relation 1↔N ou N↔N détectée entre ces tables.', 2)

class SelectionBoard(QWidget):
    selectionChanged = pyqtSignal(set)

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.columns = []
        self.instances = {}
        self.snapshot = None

        root = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.combo = QComboBox(); self.combo.setEditable(False)
        self.btn_add = QPushButton('Ajouter colonne')

        # Nouveau : bouton Actualiser + limiteur Max
        self.btn_reload = QPushButton('Actualiser')
        self.btn_reload.setToolTip("Recharger les colonnes affichées")
        self.btn_clear = QPushButton('Vider')
        self.chkFilterChildren = QCheckBox("Filtrer l'affichage des entités enfants selon les tables chargées")

        self.spinMax = QSpinBox()
        self.spinMax.setRange(0, 1000000)
        self.spinMax.setValue(0)  # 0 = illimité
        self.spinMax.setToolTip("Nombre maximum d’entités à afficher (0 = illimité)")

        bar.addWidget(QLabel('Table :')); bar.addWidget(self.combo, 1); bar.addWidget(self.btn_add)
        bar.addStretch(1)
        bar.addWidget(QLabel("Max:")); bar.addWidget(self.spinMax)
        bar.addWidget(self.chkFilterChildren)
        bar.addWidget(self.btn_reload); bar.addWidget(self.btn_clear)
        root.addLayout(bar)

        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        from qgis.PyQt.QtWidgets import QWidget as _W
        self.inner = _W(); self.hbox = QHBoxLayout(self.inner)
        self.hbox.setContentsMargins(4,4,4,4)
        self.hbox.setSpacing(6)
        self.hbox.addStretch(1)
        self.scroll.setWidget(self.inner)
        root.addWidget(self.scroll, 1)

        self.btn_add.clicked.connect(self.add_selected_layer)
        self.btn_clear.clicked.connect(self.clear_columns)
        self.btn_reload.clicked.connect(self.reload_columns)
        self.chkFilterChildren.toggled.connect(self._on_filter_children_toggled)
        self.spinMax.valueChanged.connect(self._on_max_changed)

    def _on_max_changed(self, _):
        # Rebuild doux de toutes les colonnes
        for c in self.columns:
            c.rebuild()

    def _on_filter_children_toggled(self, checked):
        for c in self.columns:
            c.rebuild()
        self._emit_selection()

    def set_snapshot(self, snapshot):
        self.snapshot = snapshot
        self.combo.clear()
        if not snapshot:
            return
        for n in snapshot.layers.values():
            lyr = QgsProject.instance().mapLayer(n.id)
            if isinstance(lyr, QgsVectorLayer):
                self.combo.addItem(n.name, n.id)

    def add_selected_layer(self):
        lid = self.combo.currentData()
        lyr = QgsProject.instance().mapLayer(lid)
        if not lyr:
            return
        self._add_layer(lyr)

    def add_layer_by_id(self, layer_id: str):
        lyr = QgsProject.instance().mapLayer(layer_id)
        if not lyr:
            return
        self._add_layer(lyr)

    def _add_layer(self, lyr):
        count = self.instances.get(lyr.id(), 0) + 1
        self.instances[lyr.id()] = count

        col = ColumnWidget(
            lyr, self.iface,
            self.selected_layer_ids,
            self.chkFilterChildren.isChecked,
            self.spinMax.value,                     # <— fournisseur de la limite
            parent=self.inner, instance_index=count,
            board=self
        )
        col.request_refresh_diagram.connect(self._emit_selection)
        col.request_remove.connect(self._remove_column)

        self.columns.append(col)
        self.hbox.insertWidget(self.hbox.count()-1, col)

        QTimer.singleShot(0, self._emit_selection)

    def _remove_column(self, col_widget):
        try:
            col_widget.request_refresh_diagram.disconnect(self._emit_selection)
            col_widget.request_remove.disconnect(self._remove_column)
        except Exception:
            pass
        try:
            self.columns.remove(col_widget)
        except ValueError:
            pass
        self.hbox.removeWidget(col_widget)
        col_widget.setParent(None)
        col_widget.deleteLater()
        QTimer.singleShot(0, self._emit_selection)

    def clear_columns(self):
        for i in range(self.hbox.count()-1):
            item = self.hbox.itemAt(0)
            w = item.widget()
            if w:
                try:
                    w.request_refresh_diagram.disconnect(self._emit_selection)
                    w.request_remove.disconnect(self._remove_column)
                except Exception:
                    pass
                self.hbox.removeWidget(w)
                w.setParent(None)
                w.deleteLater()
        self.columns.clear()
        self.instances.clear()
        QTimer.singleShot(0, self._emit_selection)

    def selected_layer_ids(self):
        return {c.layer.id() for c in self.columns}

    def _emit_selection(self):
        self.selectionChanged.emit(self.selected_layer_ids())

    # --- Reload all visible columns
    def reload_columns(self):
        for col in list(self.columns):
            if hasattr(col, 'reload'):
                try:
                    col.reload()
                except Exception:
                    pass

    def label_for(self, layer, feat) -> str:
        # Cherche s’il y a déjà une colonne pour cette couche → on réutilise son formatage
        for c in self.columns:
            if c.layer.id() == layer.id():
                return c.format_label_for_layer(layer, feat) or str(feat.id())
        # Fallback si la couche n’est pas en colonne : premier champ non NULL ou ID
        try:
            for f in layer.fields():
                v = feat[f.name()]
                if v is not None:
                    return str(v)
        except Exception:
            pass
        return str(feat.id())

    def refresh_edit_state_for(self, layer):
        """Force le rafraîchissement du style 'crayon' pour toutes
        les colonnes affichant cette couche."""
        lid = layer.id()
        for c in getattr(self, "columns", []):
            try:
                if c.layer.id() == lid:
                    c._update_edit_style()
            except Exception:
                pass

    # ----- Construction du rapport HTML pour toutes les colonnes -----
    def build_html_report(self) -> str:
        """
        Construit le corps HTML du rapport à partir de TOUTES les colonnes
        actuellement affichées dans LinQ (ordre gauche → droite).
        """
        parts = []
        for col in self.columns:
            try:
                section = col.to_html_section()
            except Exception as ex:
                # On évite que tout casse à cause d'une colonne
                name = getattr(col.layer, 'name', lambda: '<?>')()
                section = (
                    f"<h2>{name}</h2>"
                    f"<p class='meta' style='color:red'>Erreur dans cette colonne : {ex}</p>"
                )
            parts.append(section)
        return "\n".join(parts)