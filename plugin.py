
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from .dock import RelationsExplorerDock

class RelationsExplorerPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None

    def tr(self, message):
        return QCoreApplication.translate('RelationsExplorer', message)

    def initGui(self):
        icon = QIcon(self.plugin_dir("resources/icon.png"))
        self.action = QAction(icon, self.tr('Relations Explorer (LinQ)'), self.iface.mainWindow())
        self.action.triggered.connect(self.open_dock)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToDatabaseMenu(self.tr('LinQ'), self.action)

    def plugin_dir(self, rel):
        import os
        return os.path.join(os.path.dirname(__file__), rel)

    def unload(self):
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginDatabaseMenu(self.tr('LinQ'), self.action)
        if self.dock:
            self.iface.removeDockWidget(self.dock)

    def open_dock(self):
        if not self.dock:
            self.dock = RelationsExplorerDock(self.iface)
            self.iface.addDockWidget(0x1, self.dock)  # Left
        self.dock.refresh_all()
        self.dock.show()
        self.dock.raise_()
