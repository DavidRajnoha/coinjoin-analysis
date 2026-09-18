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

    def _is_coinjoin_txid(self, txid):
        return txid in self.cj_txids
            
    def _build_nodes_and_edges(self):
        self.nodes = set()
        self.cj_txids = set()
        self.client_addr_map = {}
        self.output_to_addr = {}

        for cj in self.coinjoins:
            self.cj_txids.add(cj.txid)
            for participant in cj.participants:
                self._process_inputs(cj, participant)
                if not self.show_changes:
                    continue
                self._process_change_outputs(cj, participant)

    def _process_inputs(self, cj, participant):
        # Process inputs for a participant
        if hasattr(participant, 'inputs'):
            for inp in participant.inputs:
                if not self._is_coinjoin_txid(inp.txid):
                    continue

                self.nodes.add(inp.txid)  # Add txid as a node (input)
                value = getattr(inp, 'value', 0.0)
                role = getattr(participant, 'role', 'unknown')
                client = getattr(participant, 'client', None)
                try:
                    self.edges.append(
                        Edge(
                            src=inp.txid,
                            dst=cj.txid,
                            src_type="CoinJoin",
                            dst_type="CoinJoin",
                            value=value,
                            role=role,
                            out_n=inp.vout,
                            client=client,
                            label=f"{value:.8f}" if value else "",
                        )
                    )
                except Exception as e:
                    print(f"Error creating edge for input in {cj.txid}: {e}")


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
        """Efficient and deterministic layout of CoinJoin graph nodes."""
        if not self.nodes:
            self.positions = {}
            return

        # Build necessary metadata in a single pass
        output_info = {}  # (txid, vout) -> dict with addr, role, type, spent_in
        cj_block_heights = {}
        for cj in self.coinjoins:
            cj_block_heights[cj.txid] = cj.block_height
            for p in cj.participants:
                role = getattr(p, 'role', 'unknown')
                client = getattr(p, 'client', None)

                for inp in getattr(p, 'inputs', []):
                    output_info.setdefault((inp.txid, inp.vout), {})["spent_in"] = cj.txid

                for label, out_type in [("cj_output", "coinjoin"), ("change_output", "change")]:
                    out = getattr(p, label, None)
                    if out:
                        key = (cj.txid, out.n)
                        output_info[key] = {
                            "addr": self.get_address(out),
                            "role": role,
                            "type": out_type,
                            "client": client,
                            "spent_in": output_info.get(key, {}).get("spent_in")
                        }
                        self.output_to_addr[key] = output_info[key]["addr"]

        # Sort CoinJoin txs by block height (unconfirmed => float('inf'))
        cj_sorted = sorted(
            self.cj_txids,
            key=lambda txid: (
            cj_block_heights.get(txid) if cj_block_heights.get(txid) is not None else float('inf'), txid)
        )
        x_map = {txid: 200 * i for i, txid in enumerate(cj_sorted)}
        Y = 120
        positions = {}

        for i, txid in enumerate(cj_sorted):
            y = [0, -Y, Y][i % 3]
            positions[txid] = {"x": x_map[txid], "y": y}

        max_cj_y = max(abs(pos["y"]) for pos in positions.values()) if positions else 0
        change_y_base = max_cj_y + 300
        addr_y_base = change_y_base + 200

        change_offsets = defaultdict(int)
        addr_offsets = defaultdict(int)

        # Deterministic x-offset jitter
        def _jitter(base: float, span: float, seed: str) -> float:
            h = hash(seed) & 0xFFFFFFFF
            return base + span * ((h % 1000) / 500.0 - 1.0)

        for (txid, vout), meta in output_info.items():
            addr = meta.get("addr")
            if not addr or addr in positions:
                continue  # skip already placed or unknown

            spent_in = meta.get("spent_in")
            if spent_in in self.cj_txids:
                continue  # this output was used in another CJ ⇒ no visual node

            parent_x = positions.get(txid, {"x": 0})["x"]
            y_base = change_y_base if meta["type"] == "change" else addr_y_base
            offset_dict = change_offsets if meta["type"] == "change" else addr_offsets

            offset = offset_dict[txid]
            offset_dict[txid] += 1

            positions[addr] = {
                "x": _jitter(parent_x, 50 if meta["type"] == "change" else 80, addr),
                "y": y_base + offset * (50 if meta["type"] == "change" else 40)
            }

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
                "enabled": false,
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
        


# ─────────────────────────────────────────────────────────────────────────────
#  Private helpers
# ─────────────────────────────────────────────────────────────────────────────


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
