import re
from qgis.utils import iface
from qgis.core import QgsLayerTreeGroup

def natural_sort_key(node):
    """
    Tokenizzazione della stringa. Isola i blocchi testuali dai numerici.
    Casta le porzioni numeriche a float per la corretta valutazione matematica.
    """
    def convert(text):
        try:
            return float(text)
        except ValueError:
            return text.lower()
            
    # La regex identifica sequenze di numeri, includendo i separatori decimali
    return [convert(c) for c in re.split(r'([0-9]+(?:\.[0-9]+)?)', node.name())]

def sort_target_hierarchy_natural():
    view = iface.layerTreeView()
    selected_nodes = view.selectedNodes()
    
    if not selected_nodes:
        return

    node = selected_nodes[0]
    
    # Risoluzione topologica: target = gruppo o genitore del layer selezionato
    target_parent = node if isinstance(node, QgsLayerTreeGroup) else node.parent()
        
    if target_parent is None:
        return

    children = target_parent.children()
    if len(children) < 2:
        return

    # Ordinamento naturale basato sulla tokenizzazione regex
    sorted_children = sorted(children, key=natural_sort_key)

    if children == sorted_children:
        return

    # Mutazione: Inserimento cloni -> Rimozione originali per Memory Safety
    for clone in [c.clone() for c in sorted_children]:
        target_parent.addChildNode(clone)

    for child in children:
        target_parent.removeChildNode(child)

sort_target_hierarchy_natural()