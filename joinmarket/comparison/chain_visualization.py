"""
Enhanced visualization utilities for CoinJoin chain comparison.

Provides functions to create colored tree representations that highlight
differences and similarities between chains.
"""

from typing import List, Dict, Any, Set, Tuple
from collections import defaultdict
import html

from joinmarket.common.coinjoin_chain import CoinJoinTree


def generate_colored_chain_comparison(
    blackbox_chain: CoinJoinTree,
    whitebox_chain: CoinJoinTree
) -> str:
    """
    Generate a unified color-differentiated HTML string tree representation.
    
    Nodes are colored as follows:
    - Green: Nodes that correspond exactly (same position in both trees)
    - Yellow: Nodes common to both trees but in different positions
    - Light Red: Nodes present only in blackbox tree
    - Dark Red: Nodes present only in whitebox tree
    
    Args:
        blackbox_chain: A CoinJoinTree from blackbox analysis
        whitebox_chain: A CoinJoinTree from whitebox analysis
        
    Returns:
        HTML string with colored tree representation
    """
    # Get all node TXIDs from both trees
    bb_txids = {node.txid for node in blackbox_chain.nodes}
    wb_txids = {node.txid for node in whitebox_chain.nodes}
    
    common_txids = bb_txids.intersection(wb_txids)
    bb_only_txids = bb_txids - common_txids
    wb_only_txids = wb_txids - common_txids
    
    # Create mappings of parent-child relationships
    bb_connections = defaultdict(list)
    wb_connections = defaultdict(list)
    
    # Get parent-child relationships from traversing the tree structure
    for node in blackbox_chain.nodes:
        for child in node.children:
            bb_connections[node.txid].append(child.txid)
    
    for node in whitebox_chain.nodes:
        for child in node.children:
            wb_connections[node.txid].append(child.txid)
    
    # Find the root nodes of each tree (nodes without parents)
    bb_root_txids = set(node.txid for node in blackbox_chain.root_nodes)
    wb_root_txids = set(node.txid for node in whitebox_chain.root_nodes)
    
    # Create node position maps for exact position matching
    bb_positions = {}
    bb_all_nodes = []
    _map_node_positions(bb_root_txids, bb_connections, bb_positions, [], bb_all_nodes)
    
    wb_positions = {}
    wb_all_nodes = []
    _map_node_positions(wb_root_txids, wb_connections, wb_positions, [], wb_all_nodes)
    
    # Check for exact position matches
    exact_position_matches = set()
    for txid, bb_pos in bb_positions.items():
        if txid in wb_positions and bb_pos == wb_positions[txid]:
            exact_position_matches.add(txid)
    
    # Remaining common nodes that don't match exactly by position
    positionally_different = common_txids - exact_position_matches
    
    # Generate a unified tree visualization
    html_output = "<div class='tree-comparison'><pre style='white-space: pre-wrap; max-width: 100%; overflow-x: auto;'>"
    
    # Show common nodes first
    if exact_position_matches:
        html_output += "<span style='color: #00AA00; font-weight: bold;'>Exact Position Matches:</span>\n"
        for txid in sorted(exact_position_matches):
            short_txid = txid[:8] + "..." + txid[-8:]
            html_output += f"<span style='color: #00AA00;'>{html.escape(short_txid)}</span>\n"
    
    if positionally_different:
        html_output += "\n<span style='color: #AAAA00; font-weight: bold;'>Common Nodes (Different Positions):</span>\n"
        for txid in sorted(positionally_different):
            short_txid = txid[:8] + "..." + txid[-8:]
            html_output += f"<span style='color: #AAAA00;'>{html.escape(short_txid)}</span>\n"
    
    if bb_only_txids:
        html_output += "\n<span style='color: #CC5555; font-weight: bold;'>Only in Blackbox Chain:</span>\n"
        for txid in sorted(bb_only_txids):
            short_txid = txid[:8] + "..." + txid[-8:]
            html_output += f"<span style='color: #CC5555;'>{html.escape(short_txid)}</span>\n"
    
    if wb_only_txids:
        html_output += "\n<span style='color: #AA0000; font-weight: bold;'>Only in Whitebox Chain:</span>\n"
        for txid in sorted(wb_only_txids):
            short_txid = txid[:8] + "..." + txid[-8:]
            html_output += f"<span style='color: #AA0000;'>{html.escape(short_txid)}</span>\n"
    
    html_output += "</pre></div>"
    
    # Now create hierarchical tree visualizations
    html_output += "<div class='tree-hierarchy'><pre style='white-space: pre-wrap; max-width: 100%; overflow-x: auto;'>"
    html_output += "<span style='font-weight: bold;'>Blackbox Chain Structure:</span>\n"
    html_output += _render_tree_structure(
        bb_root_txids, bb_connections, 
        exact_position_matches, positionally_different, bb_only_txids, wb_only_txids, 
        "blackbox", 0
    )
    
    html_output += "\n<span style='font-weight: bold;'>Whitebox Chain Structure:</span>\n"
    html_output += _render_tree_structure(
        wb_root_txids, wb_connections, 
        exact_position_matches, positionally_different, bb_only_txids, wb_only_txids, 
        "whitebox", 0
    )
    html_output += "</pre></div>"
    
    return html_output


def _map_node_positions(
    root_txids: Set[str],
    connections: Dict[str, List[str]],
    positions: Dict[str, List[int]],
    current_path: List[int],
    all_nodes: List[str]
) -> None:
    """
    Map each node's position in the tree to enable exact position matching.
    
    Args:
        root_txids: Set of root transaction IDs
        connections: Dictionary mapping parent txids to child txids
        positions: Dictionary to populate with positions
        current_path: Current path in the tree
        all_nodes: List to populate with all nodes in traversal order
    """
    for i, root_txid in enumerate(sorted(root_txids)):
        path = current_path + [i]
        positions[root_txid] = path
        all_nodes.append(root_txid)
        
        if root_txid in connections:
            children = connections[root_txid]
            _map_node_positions(set(children), connections, positions, path, all_nodes)


def _render_tree_structure(
    root_txids: Set[str],
    connections: Dict[str, List[str]],
    exact_matches: Set[str],
    similar_nodes: Set[str],
    bb_only: Set[str],
    wb_only: Set[str],
    tree_type: str,
    indent: int
) -> str:
    """
    Render a tree structure with color-coded nodes based on comparison status.
    
    Args:
        root_txids: Set of root transaction IDs to start from
        connections: Dictionary mapping parent txids to child txids
        exact_matches: Set of txids that match exactly in position
        similar_nodes: Set of txids that exist in both trees but at different positions
        bb_only: Set of txids only in blackbox tree
        wb_only: Set of txids only in whitebox tree
        tree_type: Either "blackbox" or "whitebox"
        indent: Current indentation level
        
    Returns:
        HTML string with color-coded tree structure
    """
    output = ""
    indent_str = "  " * indent
    
    for root_txid in sorted(root_txids):
        short_txid = root_txid[:8] + "..." + root_txid[-8:]
        
        # Determine color based on node status
        if root_txid in exact_matches:
            color = "#00AA00"  # Green for exact matches
        elif root_txid in similar_nodes:
            color = "#AAAA00"  # Yellow for common but different position
        elif tree_type == "blackbox" and root_txid in bb_only:
            color = "#CC5555"  # Light red for blackbox only
        elif tree_type == "whitebox" and root_txid in wb_only:
            color = "#AA0000"  # Dark red for whitebox only
        else:
            color = "#888888"  # Grey for unclassified (shouldn't happen)
            
        output += f"{indent_str}<span style='color: {color};'>{html.escape(short_txid)}</span>\n"
        
        # Render children
        if root_txid in connections and connections[root_txid]:
            children = set(connections[root_txid])
            output += _render_tree_structure(
                children, connections, 
                exact_matches, similar_nodes, bb_only, wb_only, 
                tree_type, indent + 1
            )
    
    return output
