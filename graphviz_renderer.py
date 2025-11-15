import subprocess, shutil, tempfile, sys
from qgis.core import QgsSettings

def _esc(s: str) -> str:
    if s is None:
        return ""
    return str(s).replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')

def _run_no_console(args):
    # Évite la fenêtre console éphémère sous Windows
    if sys.platform.startswith('win'):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            flags = subprocess.CREATE_NO_WINDOW
        except AttributeError:
            flags = 0
        return subprocess.run(args, capture_output=True, startupinfo=si, creationflags=flags)
    else:
        return subprocess.run(args, capture_output=True)

class GraphvizRenderer:
    def __init__(self):
        self.reload()
        self.last_error = ""

    def reload(self):
        set_path = QgsSettings().value('relations_explorer/dot_path', '').strip()
        self.dot_path = set_path or shutil.which('dot')

    def available(self) -> bool:
        return self.dot_path is not None

    def _build_dot(self, snapshot, highlight_ids=None, focus_ids=None):
        highlight_ids = set(highlight_ids or [])
        focus_ids = set(focus_ids or [])

        all_nodes = snapshot.layers
        all_edges = snapshot.edges

        if focus_ids:
            keep_nodes = set(focus_ids)
            keep_edges = []
            for e in all_edges:
                if e.parent_layer_id in focus_ids or e.child_layer_id in focus_ids:
                    keep_edges.append(e)
                    keep_nodes.add(e.parent_layer_id)
                    keep_nodes.add(e.child_layer_id)
        else:
            keep_nodes = set(all_nodes.keys())
            keep_edges = all_edges

        def node_stmt(n):
            base = f'"{_esc(n.id)}" [label="{_esc(n.name)}", shape=box'
            if getattr(n, 'is_link_table', False):
                base += ', style=filled, fillcolor="#FFE0B2"'
            if n.id in highlight_ids:
                base += ', penwidth=2'
            base += ']'
            return base

        lines = [
            'digraph relations {',
            '  rankdir=LR;',
            '  graph [splines=true, overlap=false];',
            '  node [fontname="Helvetica", fontsize=10];',
            '  edge [fontname="Helvetica", fontsize=9];'
        ]
        for nid, n in snapshot.layers.items():
            if nid in keep_nodes:
                lines.append('  ' + node_stmt(n))
        for e in keep_edges:
            label = '\\n'.join([f'{_esc(p)} → {_esc(c)}' for p, c in e.pairs])
            style = f' [label="{label}"]' if label else ''
            lines.append(f'  "{_esc(e.parent_layer_id)}" -> "{_esc(e.child_layer_id)}"{style};')
        lines.append('}')
        return '\n'.join(lines)

    def render_svg(self, snapshot, highlight_ids=None, focus_ids=None) -> bytes:
        if not self.available():
            return None
        dot = self._build_dot(snapshot, highlight_ids, focus_ids)
        with tempfile.NamedTemporaryFile('w', suffix='.dot', delete=False, encoding='utf-8') as f:
            f.write(dot)
            dot_fn = f.name
        proc = _run_no_console([self.dot_path, '-Tsvg', dot_fn])
        self.last_error = proc.stderr.decode('utf-8', errors='ignore').strip()
        if proc.returncode != 0:
            return None
        return proc.stdout

    def render_plain(self, snapshot, highlight_ids=None, focus_ids=None) -> str:
        if not self.available():
            return ""
        dot = self._build_dot(snapshot, highlight_ids, focus_ids)
        with tempfile.NamedTemporaryFile('w', suffix='.dot', delete=False, encoding='utf-8') as f:
            f.write(dot)
            dot_fn = f.name
        proc = _run_no_console([self.dot_path, '-Tplain', dot_fn])
        self.last_error = proc.stderr.decode('utf-8', errors='ignore').strip()
        if proc.returncode != 0:
            return ""
        return proc.stdout.decode('utf-8', errors='ignore')