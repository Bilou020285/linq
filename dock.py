# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QSplitter, QLineEdit, QFormLayout, QMessageBox
)
from qgis.core import QgsProject, QgsSettings

from .relation_utils import RelationsSnapshot
from .graphviz_renderer import GraphvizRenderer
from .diagram_canvas import DiagramCanvas
from .selected_panel import SelectionBoard


class RelationsExplorerDock(QDockWidget):
    def __init__(self, iface):
        super().__init__('LinQ')
        self.iface = iface
        self.setObjectName('RelationsExplorerDock')
        self.setMinimumWidth(950)

        # --- Layout racine
        main = QWidget(self)
        self.setWidget(main)
        root = QVBoxLayout(main)

        # === Header sur 2 lignes ============================================
        header_area = QVBoxLayout()             # conteneur des 2 lignes
        header_top = QHBoxLayout()
        header_bottom = QHBoxLayout()

        self.btn_refresh = QPushButton('Analyser les relations')
        self.btn_export = QPushButton('Exporter diagramme (SVG)…')
        self.btn_export_drawio = QPushButton('Exporter Draw.io…')
        self.btn_export_drawio.clicked.connect(self.export_drawio)

        self.search = QLineEdit()
        self.search.setPlaceholderText('Rechercher une table…')

        # Ligne 1 : [Analyser] ..... [Recherche] [Exporter SVG]
        header_top.addWidget(self.btn_refresh)
        header_top.addStretch(1)
        header_top.addWidget(self.search)
        header_top.addWidget(self.btn_export)

        # Ligne 2 : ..... [Exporter Draw.io…] (aligné à droite)
        header_bottom.addStretch(1)
        header_bottom.addWidget(self.btn_export_drawio)
        header_bottom.setContentsMargins(0, 0, 0, 6)  # petit espace

        header_area.addLayout(header_top)
        header_area.addLayout(header_bottom)
        root.addLayout(header_area)
        # ====================================================================

        # --- Splitter haut (diagramme) / bas (colonnes entités)
        self.splitter = QSplitter(Qt.Vertical)
        root.addWidget(self.splitter, 1)

        # Zone diagramme
        self.diagram_container = QWidget()
        self.diagram_layout = QVBoxLayout(self.diagram_container)
        self.diagram_layout.setContentsMargins(0, 0, 0, 0)

        self.diagram_widget = QLabel("Diagramme non généré. Clique « Analyser les relations ».")
        self.diagram_widget.setAlignment(Qt.AlignCenter)

        self.dot_hint = QWidget()
        form = QFormLayout(self.dot_hint)
        self.dot_path_edit = QLineEdit(QgsSettings().value('relations_explorer/dot_path', ''))
        self.btn_save_dot = QPushButton('Chemin dot : Enregistrer')
        form.addRow('Chemin vers dot (optionnel) :', self.dot_path_edit)
        form.addRow('', self.btn_save_dot)

        self.diagram_layout.addWidget(self.diagram_widget)
        self.diagram_layout.addWidget(self.dot_hint)
        self.splitter.addWidget(self.diagram_container)

        # Zone colonnes entités
        self.board = SelectionBoard(self.iface)
        self.splitter.addWidget(self.board)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)

        # --- État
        self.snapshot = None
        self.gv = GraphvizRenderer()
        self.canvas = None

        # --- Signaux
        self.btn_refresh.clicked.connect(self.refresh_all)
        self.btn_export.clicked.connect(self.export_diagram)
        self.btn_save_dot.clicked.connect(self.save_dot_path)
        self.board.selectionChanged.connect(self.refresh_diagram_only)
        self.search.textChanged.connect(self.refresh_diagram_only)

    # ------------------------------------------------------------------ utils
    def _clear_diag_layout_and_put(self, widget):
        # supprime tout et met 'widget' + hint dot
        for i in reversed(range(self.diagram_layout.count())):
            w = self.diagram_layout.itemAt(i).widget()
            if w:
                w.setParent(None)
        if widget is not None:
            self.diagram_layout.addWidget(widget)
        self.diagram_layout.addWidget(self.dot_hint)

    def save_dot_path(self):
        QgsSettings().setValue('relations_explorer/dot_path', self.dot_path_edit.text().strip())
        try:
            self.gv.reload()  # re-détecter dot
        except Exception:
            pass
        self.refresh_diagram_only()

    # ---------------------------------------------------------------- capture
    def refresh_all(self):
        self.snapshot = RelationsSnapshot.capture(QgsProject.instance())
        self.board.set_snapshot(self.snapshot)
        self.refresh_diagram_only()

    # Mapping (parent_id, child_id) -> [ (PK_parent, FK_enfant), ... ]
    def _edge_pairs_map(self):
        mp = {}
        if not self.snapshot:
            return mp
        for e in self.snapshot.edges:
            key = (e.parent_layer_id, e.child_layer_id)
            mp.setdefault(key, []).extend(e.pairs)
        return mp

    def _snapshot_to_plain(self, focus_ids=None):
        if not self.snapshot:
            return ""
        highlight = self.board.selected_layer_ids()
        focus = set(focus_ids or highlight)
        return self.gv.render_plain(
            self.snapshot,
            highlight_ids=highlight,
            focus_ids=focus if focus else None
        )

    # ---------------------------------------------------------- diagram refresh
    def refresh_diagram_only(self, *args):
        if not self.snapshot:
            return

        # focus via champ de recherche (par nom de couche)
        query = self.search.text().strip().lower()
        focus_ids = set()
        if query:
            for nid, node in self.snapshot.layers.items():
                if query in node.name.lower():
                    focus_ids.add(nid)

        plain = self._snapshot_to_plain(focus_ids)
        if not plain:
            txt = "Impossible de générer le diagramme. Vérifie Graphviz (binaire 'dot').\n"
            if getattr(self.gv, 'last_error', ''):
                txt += "\nDétails Graphviz :\n" + self.gv.last_error
            self.diagram_widget.setText(txt)
            self._clear_diag_layout_and_put(self.diagram_widget)
            return

        # Recréation du canvas
        if self.canvas:
            self.canvas.setParent(None)
            self.canvas = None
        self.canvas = DiagramCanvas()
        # Double-clic = ajouter colonne (pas de simple clic)
        self.canvas.nodeDoubleClicked.connect(self._on_node_double_clicked)

        selected_ids = set(self.board.selected_layer_ids())
        link_ids = {nid for nid, n in self.snapshot.layers.items() if getattr(n, 'is_link_table', False)}
        edge_pairs = self._edge_pairs_map()

        self.canvas.set_graph(
            plain,
            selected_ids=selected_ids,
            link_ids=link_ids,
            edge_pairs_map=edge_pairs
        )

        self._clear_diag_layout_and_put(self.canvas)

    # -------------------------------------- action depuis double-clic diagramme
    def _on_node_double_clicked(self, layer_id: str):
        try:
            self.board.add_layer_by_id(layer_id)
            lyr = QgsProject.instance().mapLayer(layer_id)
            name = lyr.name() if lyr else layer_id
            self.iface.messageBar().pushSuccess("LinQ", f"Table ajoutée : {name}")
        except Exception as e:
            self.iface.messageBar().pushWarning("LinQ", f"Impossible d'ajouter la table : {e}")

    # --------------------------------------------------------------- export SVG
    def export_diagram(self):
        if not self.snapshot:
            return
        fn, _ = QFileDialog.getSaveFileName(self, 'Exporter le diagramme', 'relations.svg', 'SVG (*.svg)')
        if not fn:
            return
        highlight = self.board.selected_layer_ids()
        svg = self.gv.render_svg(self.snapshot, highlight_ids=highlight, focus_ids=highlight)
        if not svg:
            return
        with open(fn, 'wb') as f:
            f.write(svg)

    # ------------------------------------------------------------- export draw
    def export_drawio(self):
        if not self.snapshot:
            QMessageBox.information(self, 'Export', 'Aucun diagramme à exporter. Lance d’abord l’analyse.')
            return
        fn, _ = QFileDialog.getSaveFileName(self, 'Exporter au format draw.io', 'linq_model.drawio', 'Draw.io (*.drawio)')
        if not fn:
            return

        # Essaye de récupérer les positions depuis la scène (facultatif)
        node_pos = None
        try:
            if hasattr(self, 'canvas') and hasattr(self.canvas, 'node_positions'):
                node_pos = self.canvas.node_positions()  # dict {layer_id: (x,y)} si dispo
        except Exception:
            node_pos = None

        try:
            from .drawio_exporter import build_drawio
        except Exception as ex:
            QMessageBox.warning(self, 'Export', f'Export draw.io indisponible : {ex}')
            return

        try:
            xml = build_drawio(self.snapshot, node_positions=node_pos)
            with open(fn, 'wb') as f:
                f.write(xml)
            QMessageBox.information(self, 'Export', 'Fichier .drawio exporté avec succès.')
        except Exception as ex:
            QMessageBox.warning(self, 'Export', f'Échec export draw.io : {ex}')