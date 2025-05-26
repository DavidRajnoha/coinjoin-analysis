from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Set, Tuple, Iterable
import re
import math

from pyvis.network import Network           # pip install pyvis

from joinmarket.visualisation.tx_output import TxOutputRegistry, TxOutputProvider
from joinmarket.common.coinjoin_model import CoinJoin

_TX = re.compile(r'^[0-9a-f]{64}$')
_ADDR = re.compile(r'^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$')

_ROLE_COLOR = {
    "taker": "#e67e22",  # orange
    "maker": "#2ecc40",  # green
}

# ─────────────────────────────────────────────────────────────────────────────
#  Core data containers
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Edge:
    src:      str
    dst:      str
    value:    float
    role:     str
    out_n:    int
    src_type: str
    dst_type: str                # "CoinJoin" | "address"
    label:    str | None = None
    client:   str | None = None


# ─────────────────────────────────────────────────────────────────────────────
#  Graph builder
# ─────────────────────────────────────────────────────────────────────────────

class CoinJoinGraphBuilder:
    """
    Builder for CoinJoin flow graph visualization.
    Takes a list of CoinJoin objects and builds a graph representation.
    """

    def __init__(self, coinjoins=None, cj_objs=None, show_changes=True, layout_callback=None):
        """
        Initialize the graph builder with a list of CoinJoin objects.
        
        Args:
            coinjoins: List of CoinJoin objects
            cj_objs: Alternative name for coinjoins (for backward compatibility)
            show_changes: Whether to show change outputs in the visualization
            layout_callback: Optional callback for custom layout
        """
        # Handle both parameter names for backward compatibility
        cj_list = coinjoins if coinjoins is not None else cj_objs
        
        if not cj_list:
            print("Warning: Empty list of CoinJoins provided to CoinJoinGraphBuilder")
            cj_list = []
            
        self.coinjoins = cj_list
        self.show_changes = show_changes
        self.layout_callback = layout_callback
        
        # Data structures initialized during build
        self.edges = []
        self.nodes = set()
        self.cj_txids = set([cj.txid for cj in cj_list if hasattr(cj, 'txid')])
        self.client_addr_map = {}
        self.positions = {}
        self.output_to_addr = {}  # Mapping of (txid, vout_n) -> address
        
        # Track whether build has been called
        self._is_built = False
        
    def build(self):
        """
        Build the graph data structures from the CoinJoin objects.
        This method must be called before accessing the graph data.
        """
        if not self.coinjoins:
            print("No CoinJoins to build graph from")
            self._is_built = True
            return
            
        try:
            self._build_nodes_and_edges()
            self._calculate_positions()
            self._is_built = True
        except Exception as e:
            print(f"Error building CoinJoin graph: {e}")
            # Initialize with empty structures in case of error
            self.edges = []
            self.nodes = set()
            self.cj_txids = set()
            self.client_addr_map = {}
            self.positions = {}
            self.output_to_addr = {}
            self._is_built = False
            
    def _build_nodes_and_edges(self):
        self.nodes = set()
        self.cj_txids = set()
        self.client_addr_map = {}
        self.output_to_addr = {}

        for cj in self.coinjoins:
            self.cj_txids.add(cj.txid)
            for participant in cj.participants:
                self._process_inputs(cj, participant)
                # self._process_outputs(cj, participant)
                if not self.show_changes:
                    continue
                self._process_change_outputs(cj, participant)

    def _process_inputs(self, cj, participant):
        # Process inputs for a participant
        if hasattr(participant, 'inputs'):
            for inp in participant.inputs:
                addr = self.get_address(inp)
                self.nodes.add(addr)
                value = getattr(inp, 'value', 0.0)
                role = getattr(participant, 'role', 'unknown')
                client = getattr(participant, 'client', None)
                try:
                    self.edges.append(
                        Edge(
                            src=addr,
                            dst=cj.txid,
                            src_type="address",
                            dst_type="CoinJoin",
                            value=value,
                            role=role,
                            out_n=None,
                            client=client,
                            label=f"{value:.8f}" if value else "",
                        )
                    )
                except Exception as e:
                    print(f"Error creating edge for input in {cj.txid}: {e}")

    def _process_outputs(self, cj, participant):
        # Process CoinJoin outputs for a participant
        if hasattr(participant, 'cj_output') and participant.cj_output:
            out = participant.cj_output
            if hasattr(out, 'n') and hasattr(out, 'address'):
                vout_n = out.n
                addr = self.get_address(out)
                if addr:
                    self.output_to_addr[(cj.txid, vout_n)] = addr
                    self.nodes.add(addr)
                    value = getattr(out, 'value', 0.0)
                    role = getattr(participant, 'role', 'unknown')
                    client = getattr(participant, 'client', None)
                    out_n = getattr(out, 'n', 0)
                    if client:
                        self.client_addr_map[addr] = client
                    try:
                        self.edges.append(
                            Edge(
                                src=cj.txid,
                                dst=addr,
                                src_type="CoinJoin",
                                dst_type="address",
                                value=value,
                                role=role,
                                out_n=out_n,
                                client=client,
                                label=f"{value:.8f}" if value else "",
                            )
                        )
                    except Exception as e:
                        print(f"Error creating edge for CJ output in {cj.txid}: {e}")

    def _process_change_outputs(self, cj, participant):
        # Process change outputs for a participant, if enabled
        if self.show_changes and hasattr(participant, 'change_output') and participant.change_output:
            try:
                out = participant.change_output
                if hasattr(out, 'n') and hasattr(out, 'address'):
                    vout_n = out.n
                    addr = self.get_address(out)
                    if addr:
                        self.output_to_addr[(cj.txid, vout_n)] = addr
                        self.nodes.add(addr)
                        value = getattr(out, 'value', 0.0)
                        role = getattr(participant, 'role', 'unknown')
                        client = getattr(participant, 'client', None)
                        out_n = getattr(out, 'n', 0)
                        if client:
                            self.client_addr_map[addr] = client
                        self.edges.append(
                            Edge(
                                src=cj.txid,
                                dst=addr,
                                src_type="CoinJoin",
                                dst_type="address",
                                value=value,
                                role=role,
                                out_n=out_n,
                                client=client,
                                label=f"{value:.8f}" if value else "",
                            )
                        )
            except Exception as e:
                print(f"Error creating edge for change output in {cj.txid}: {e}")
    
    def _calculate_positions(self):
        """Calculate positions for the nodes in the visualization."""
        if not self.nodes:
            print("Warning: No nodes to position")
            self.positions = {}
            return
            
        # Get block heights for CoinJoin transactions
        block_heights = {}
        for tx in self.coinjoins:
            block_heights[tx.txid] = tx.block_height
        
        # Get the set of CoinJoin nodes
        cj_nodes = set(self.cj_txids)
        
        # Get output roles
        output_roles = {}
        output_spent = {}
        
        # Track which outputs are spent in other CoinJoins
        for tx in self.coinjoins:
            # Get inputs from all participants
            for participant in tx.participants:
                if hasattr(participant, 'inputs'):
                    for inp in participant.inputs:
                        output_spent.setdefault((inp.txid, inp.vout), (tx.txid, None))
            
            # Get outputs from all participants
            for participant in tx.participants:
                # Add CoinJoin output
                if hasattr(participant, 'cj_output'):
                    output = participant.cj_output
                    output_roles[(tx.txid, output.n)] = {
                        'is_change': False,
                        'type': 'coinjoin',
                        'role': getattr(participant, 'role', 'unknown')
                    }
                
                # Add change output if present
                if hasattr(participant, 'change_output') and participant.change_output:
                    output = participant.change_output
                    output_roles[(tx.txid, output.n)] = {
                        'is_change': True,
                        'type': 'change',
                        'role': getattr(participant, 'role', 'unknown')
                    }
        
        # First, position the CoinJoin transactions based on block height
        if not cj_nodes:
            print("Warning: No CoinJoin nodes to position")
            self.positions = {}
            return
            
        # Sort CoinJoins by block height
        get_block_height = lambda txid: block_heights.get(txid, 0)
        
        cj_sorted = sorted(cj_nodes, key=lambda x: (get_block_height(block_heights[x]), x))
        x_map = {txid: i*200 for i, txid in enumerate(cj_sorted)}
        
        positions = {}
        Y = 120
        for idx, txid in enumerate(cj_sorted):
            y = [0, -Y, Y][idx % 3]
            positions[txid] = {'x': x_map[txid], 'y': y}
            
        max_cj_y = max(abs(positions[txid]['y']) for txid in cj_sorted) if cj_sorted else 0
        
        # Position for change outputs - below all CoinJoin nodes
        change_y_base = max_cj_y + 300
        
        # Position for other address nodes - below change outputs
        addr_y_base = change_y_base + 200
        
        # Tracking offsets to prevent overlaps
        change_offsets = {}
        addr_offsets = {}
        
        # First handle change outputs
        for (txid, vout_n), info in output_roles.items():
            spender = output_spent.get((txid, vout_n))
            # Skip if this output is spent in another CoinJoin
            if spender and spender[0] in block_heights:
                continue
                
            # If this is a change output
            if info.get('is_change', False) or info.get('type', '') == 'change':
                if txid not in cj_nodes:
                    continue
                    
                addr = self.output_to_addr.get((txid, vout_n))
                if not addr:
                    continue
                    
                # Position the change below its CoinJoin
                cj_pos = positions.get(txid, {'x': 0, 'y': 0})
                
                # Get horizontal position based on parent CoinJoin
                x_base = cj_pos['x']
                
                # Add some random jitter to x position (+/- 50 pixels)
                import random
                x_jitter = x_base + random.uniform(-50, 50)
                
                # Calculate vertical position with offset to prevent overlaps
                txid_offset = change_offsets.setdefault(txid, 0)
                change_offsets[txid] += 1
                
                # Space change nodes vertically
                y_jitter = change_y_base + (txid_offset * 50)
                
                positions[addr] = {'x': x_jitter, 'y': y_jitter}
        
        # Then handle all other address nodes (that are not change and not spent in other CJs)
        for (txid, vout_n), info in output_roles.items():
            spender = output_spent.get((txid, vout_n))
            # Skip if this output is spent in another CoinJoin
            if spender and spender[0] in block_heights:
                continue
                
            # Skip if this is a change output (already handled)
            if info.get('is_change', False) or info.get('type', '') == 'change':
                continue
                
            if txid not in cj_nodes:
                continue
                
            addr = self.output_to_addr.get((txid, vout_n))
            if not addr:
                continue
                
            # Position the address below its CoinJoin
            cj_pos = positions.get(txid, {'x': 0, 'y': 0})
            
            # Get horizontal position based on parent CoinJoin
            x_base = cj_pos['x']
            
            # Add some random jitter to x position (+/- 80 pixels)
            import random
            x_jitter = x_base + random.uniform(-80, 80)
            
            # Calculate vertical position with offset to prevent overlaps
            txid_offset = addr_offsets.setdefault(txid, 0)
            addr_offsets[txid] += 1
            
            # Space address nodes vertically
            y_jitter = addr_y_base + (txid_offset * 40)
            
            positions[addr] = {'x': x_jitter, 'y': y_jitter}
        
        self.positions = positions
    
    def generate_vis_network(self, height="750px", width="100%"):
        """
        Generate a pyvis Network object for visualization.
        
        Args:
            height: Height of the visualization
            width: Width of the visualization
            
        Returns:
            A pyvis Network object
        """
        # Ensure the graph is built
        if not self._is_built:
            self.build()
            
        # If we have custom nodes and edges for visualization
        if hasattr(self, 'nodes_for_vis') and hasattr(self, 'edges_for_vis'):
            net = Network(height=height, width=width, directed=True)
            
            # Add custom nodes
            for node_data in getattr(self, 'nodes_for_vis', []):
                try:
                    net.add_node(**node_data)
                except Exception as e:
                    print(f"Error adding custom node: {e}")
                    
            # Add custom edges
            for edge_data in getattr(self, 'edges_for_vis', []):
                try:
                    net.add_edge(**edge_data)
                except Exception as e:
                    print(f"Error adding custom edge: {e}")
                    
            # Apply layout options
            if self.layout_callback:
                try:
                    self.layout_callback(net)
                except Exception as e:
                    print(f"Error applying layout callback: {e}")
                    # Fall back to default options
                    self._apply_default_options(net)
            else:
                self._apply_default_options(net)
                
            return net
        
        # Otherwise, build the visualization from scratch
        if not self.edges:
            if not self._is_built:
                self.build()
            
            # If still no edges after build, return empty network
            if not self.edges:
                print("Warning: No edges in graph, returning empty visualization")
                net = Network(height=height, width=width, directed=True)
                self._apply_default_options(net)
                return net
        
        net = Network(height=height, width=width, directed=True)
        
        # Track the nodes we've added to ensure we don't add duplicates
        added_nodes = set()
        
        # First pass: Add all nodes from self.nodes
        for nid in self.nodes:
            try:
                pos = self.positions.get(nid, {})
                
                # Create readable label
                if not isinstance(nid, str):
                    label = str(nid)
                else:
                    label = nid if len(nid) <= 16 else f"{nid[:8]}..{nid[-6:]}"
                    
                # Determine node color based on type
                if isinstance(nid, str) and _TX.fullmatch(nid):
                    color = "#87ceeb"  # txids – sky-blue
                elif isinstance(nid, str) and _ADDR.fullmatch(nid):
                    color = "#f9e79f"  # addresses – pale-yellow
                else:
                    color = "#bbbbbb"  # default – grey
                
                # Add node with position if available
                node_args = {
                    "label": label,
                    "color": color,
                    "shape": "ellipse",
                    "font": {"size": 12, "bold": True},
                    "title": f"txid: {nid}" if nid in self.cj_txids else nid
                }
                
                # Add position data if available
                if pos and "x" in pos and "y" in pos:
                    node_args["x"] = pos["x"]
                    node_args["y"] = pos["y"]
                    node_args["fixed"] = True
                
                net.add_node(nid, **node_args)
                added_nodes.add(nid)
            except Exception as e:
                print(f"Error adding node {nid}: {e}")
        
        # Second pass: Collect all missing nodes referenced in edges
        missing_nodes = set()
        for e in self.edges:
            if e.src not in added_nodes:
                missing_nodes.add(e.src)
            if e.dst not in added_nodes:
                missing_nodes.add(e.dst)
        
        # Add the missing nodes
        for nid in missing_nodes:
            try:
                # Create a default position if none exists
                pos = self.positions.get(nid, {})
                if not pos or "x" not in pos or "y" not in pos:
                    # Place at a default position
                    pos = {"x": 0, "y": 0}
                
                # Create readable label
                if not isinstance(nid, str):
                    label = str(nid)
                else:
                    label = nid if len(nid) <= 16 else f"{nid[:8]}..{nid[-6:]}"
                
                # Determine node color based on type
                if isinstance(nid, str) and _TX.fullmatch(nid):
                    color = "#87ceeb"  # txids – sky-blue
                elif isinstance(nid, str) and _ADDR.fullmatch(nid):
                    color = "#f9e79f"  # addresses – pale-yellow
                else:
                    color = "#bbbbbb"  # default – grey
                
                # Add the node with the correct parameter format
                net.add_node(
                    nid,  # This is the required positional parameter n_id
                    label=label,
                    color=color,
                    shape="ellipse",
                    font={"size": 12, "bold": True},
                    x=pos["x"],
                    y=pos["y"],
                    fixed=True,
                    title=nid
                )
                added_nodes.add(nid)
            except Exception as e:
                print(f"Error adding missing node {nid}: {e}")
        
        # Now add all edges
        for e in self.edges:
            try:
                # Skip edges with non-existent nodes
                if e.src not in added_nodes or e.dst not in added_nodes:
                    continue
                
                # Safely access role attribute
                role = getattr(e, 'role', None)
                color = _ROLE_COLOR.get(role, "#999")  # default grey
                
                # Safely access label attribute
                label = getattr(e, 'label', "")
                
                net.add_edge(
                    e.src,
                    e.dst,
                    label=label,
                    title=label,
                    arrows="to",
                    color=color,
                    smooth={"type": "continuous", "forceDirection": "none"},
                    width=1 + min(5, getattr(e, 'value', 0) * 100)
                )
            except Exception as e:
                print(f"Error adding edge: {e}")
        
        # Apply layout options
        if self.layout_callback:
            try:
                self.layout_callback(net)
            except Exception as e:
                print(f"Error applying layout callback: {e}")
                self._apply_default_options(net)
        else:
            self._apply_default_options(net)
            
        return net
    
    def _apply_default_options(self, net):
        """Apply default visualization options to the network."""
        try:
            net.set_options("""
            {
              "layout": {
                "improvedLayout": true,
                "hierarchical": {
                  "enabled": false
                }
              },
              "physics": {
                "enabled": true,
                "barnesHut": {
                  "gravitationalConstant": -2000,
                  "centralGravity": 0.1,
                  "springLength": 200,
                  "springConstant": 0.04
                },
                "stabilization": {
                  "enabled": true,
                  "iterations": 1000,
                  "updateInterval": 100,
                  "onlyDynamicEdges": false,
                  "fit": true
                }
              },
              "interaction": {
                "navigationButtons": true,
                "keyboard": true,
                "tooltipDelay": 200
              },
              "edges": {
                "smooth": {
                  "type": "continuous",
                  "forceDirection": "none"
                },
                "color": {
                  "inherit": false
                },
                "font": {
                  "size": 10
                }
              },
              "nodes": {
                "shape": "ellipse",
                "font": {
                  "size": 12,
                  "bold": true
                },
                "fixed": {
                  "x": true,
                  "y": true
                },
                "physics": false
              }
            }""")
        except Exception as e:
            print(f"Error applying default options: {e}")

    def save_graph(self, filepath):
        """
        Save the graph visualization to an HTML file.
        
        Args:
            filepath: Path to save the HTML file
        """
        net = self.generate_vis_network()
        
        # Create directory if it doesn't exist
        import os
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Save the network
        net.save_graph(filepath)
        print(f"Saved visualization to {filepath}")

    # For backward compatibility
    def to_pyvis(self, height="750px", width="100%", physics=False):
        """Backward compatibility method that calls generate_vis_network"""
        return self.generate_vis_network(height=height, width=width)

    def get_address(self, obj):
        """
        Extract address from input or output objects.
        
        Args:
            obj: Input or output object
            
        Returns:
            str: Address string
        """
        # If the object has an address attribute, use it
        if hasattr(obj, 'address') and obj.address:
            return obj.address
            
        # If it's an input, try to get txid:vout format
        if hasattr(obj, 'txid') and hasattr(obj, 'vout'):
            return f"{obj.txid}"
            
        # If it's an output with a transaction reference and n index
        if hasattr(obj, 'txid') and hasattr(obj, 'n'):
            return f"{obj.txid}"
            
        return None

    def get_node_attrs(self, cj):
        """Get node attributes for a CoinJoin transaction."""
        attrs = {
            'label': cj.txid[:8],
            'title': f"CoinJoin: {cj.txid}",
            'color': '#3388DD',
            'size': 20,
            'shape': 'box',
            'borderWidth': 2
        }
        return attrs
        
    def get_addr_attrs(self, addr, cj=None):
        """Get node attributes for an address."""
        # Check if this is a client address
        client = self.client_addr_map.get(addr)
        
        if client:
            # This is a client address
            role = "unknown"
            if client in self.client_roles:
                role = self.client_roles[client]
                
            color = "#00AA00"  # Default green for makers
            if role == "taker":
                color = "#FF0000"  # Red for takers
                
            attrs = {
                'label': f"{addr[:8]}...\n({client})",
                'title': f"Address: {addr}\nClient: {client}\nRole: {role}",
                'color': color,
                'size': 15,
                'borderWidth': 1
            }
        else:
            # External address
            attrs = {
                'label': addr[:8] + "...",
                'title': f"Address: {addr}",
                'color': '#AAAAAA',
                'size': 10,
                'borderWidth': 1
            }
            
        return attrs


# ─────────────────────────────────────────────────────────────────────────────
#  Private helpers
# ─────────────────────────────────────────────────────────────────────────────

def _edges_from_registry(reg: TxOutputRegistry, show_change: bool = True) -> Tuple[List[Edge], Set[str]]:
    edges: List[Edge] = []
    extra: Set[str]   = set()

    for out in reg.all().values():
        # Skip change outputs if show_change is False
        if not show_change and "change" in out.tags:
            continue
            
        if out.spender:                # goes into another CJ
            dst, dst_t = out.spender[0], "CoinJoin"
        else:
            dst, dst_t = (out.address or f"{out.txid}:{out.n}", "address")

        extra.add(dst)
        edges.append(
            Edge(src=out.txid, dst=dst, src_type="address", dst_type=dst_t, value=out.value,
                 role=out.role, out_n=out.n)
        )
    return edges, extra


def _label_edges(
    edges: List[Edge],
    reg:   TxOutputRegistry,
    tx_map: Dict[str, dict],
) -> None:
    """Fill Edge.label; always include the client id when it exists."""
    have_attr = any(o.role in {"maker", "taker"} for o in reg.all().values())

    for e in edges:
        out       = reg[(e.src, e.out_n)]
        client_s  = f"\n{out.client}" if out.client else ""
        is_change = (out.role != "cj_out") or "change" in out.tags

        if e.dst_type == "CoinJoin":
            if is_change or not have_attr:
                e.label = f"{out.value:.8f}\n{out.role}{client_s}"
            else:
                base    = _label_by_input(e.src, e.out_n, e.dst, reg, tx_map)
                e.label = f"{base}{client_s}"
        else:
            base = f"{out.value:.8f}\n{out.role}" if is_change else "unattributable"
            e.label = f"{base}{client_s}"



def _label_by_input(
    src_txid: str, n: int, dst_txid: str,
    reg: TxOutputRegistry, tx_map: Dict[str,dict],
) -> str:
    # Look into JoinMarket attribution (if available) to recover role/value.
    # Fall back to generic string if missing.
    out = reg[(src_txid, n)]
    vin_idx = None
    for idx, vin in enumerate(tx_map[dst_txid].get("vin", [])):
        if vin.get("txid") == src_txid and vin.get("vout") == n:
            vin_idx = idx; break
    if vin_idx is None:
        return "unattributable"

    role  = out.role or "?"
    value = out.value
    return f"in#{vin_idx} | {value:.8f} | {role}"
