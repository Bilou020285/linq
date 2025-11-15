
def classFactory(iface):
    from .plugin import RelationsExplorerPlugin
    return RelationsExplorerPlugin(iface)
