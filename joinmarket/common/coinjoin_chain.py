from __future__ import annotations
from typing import Dict, List, Set, Optional, Any, Tuple, Iterator
from collections import defaultdict, deque
import uuid
import json
from abc import ABC, abstractmethod


class CoinJoinNode(ABC):
    """Abstract base class for CoinJoin nodes in the composite pattern."""
    
    def __init__(self, txid: str):
        """Initialize a CoinJoin node.
        
        Args:
            txid: The transaction ID of this node
        """
        self.txid = txid
        self.children: List[CoinJoinNode] = []
        
    def add_child(self, child: CoinJoinNode) -> None:
        """Add a child node to this node.
        
        Args:
            child: The child node to add
        """
        if child not in self.children:
            self.children.append(child)
    
    @abstractmethod
    def get_coinjoin(self):
        """Get the CoinJoin object associated with this node."""
        pass
    
    @property
    def is_leaf(self) -> bool:
        """Return True if this node is a leaf node (no children)."""
        return len(self.children) == 0
        
    def traverse(self) -> Iterator[CoinJoinNode]:
        """Depth-first traversal of the tree starting from this node."""
        yield self
        for child in self.children:
            yield from child.traverse()

    def __str__(self) -> str:
        """Return a string representation of this node."""
        return f"{self.txid}"


class CoinJoinLeafNode(CoinJoinNode):
    """Leaf node in the CoinJoin tree representing a single transaction."""
    
    def __init__(self, coinjoin):
        """Initialize a CoinJoin leaf node.
        
        Args:
            coinjoin: The CoinJoin object this node represents
        """
        super().__init__(coinjoin.txid)
        self._coinjoin = coinjoin
    
    def get_coinjoin(self):
        """Get the CoinJoin object associated with this node."""
        return self._coinjoin


class CoinJoinTree:
    """
    Represents a tree of CoinJoin transactions where transactions are linked
    through input-output relationships. Implements the composite pattern.
    
    Note: In reality, this might be a directed acyclic graph (DAG) rather than a strict tree
    due to the way tumbler scripts consolidate multiple outputs into one CoinJoin. However,
    we maintain a tree-like representation for visualization purposes.
    """
    
    def __init__(self, id: Optional[str] = None, root_nodes: Optional[List[CoinJoinNode]] = None, analysis_type: Optional[str] = None):
        """Initialize a CoinJoin tree.
        
        Args:
            id: Optional identifier for the tree
            root_nodes: Optional list of root nodes (will be populated later if None)
            analysis_type: 'whitebox' or 'blackbox'
        """
        self.id = id if id is not None else f"{analysis_type}_chain_{uuid.uuid4().hex[:8]}"
        self.root_nodes = root_nodes if root_nodes is not None else []
        self.analysis_type = analysis_type
        self._nodes_cache = None
        self._coinjoins_cache = None
        self._connections = {}  # Map of txid -> list of child txids
        self._nodes_by_txid = {}  # Map of txid -> node
        
        # Initialize nodes cache if root_nodes provided
        if root_nodes:
            for node in root_nodes:
                self._nodes_by_txid[node.txid] = node
                
    def add_coinjoin(self, node: CoinJoinNode):
        """Add a CoinJoin node to the tree.
        
        Args:
            node: CoinJoinNode to add
        """
        if node.txid not in self._nodes_by_txid:
            self._nodes_by_txid[node.txid] = node
            self.root_nodes.append(node)
            # Invalidate caches
            self._nodes_cache = None
            self._coinjoins_cache = None
            
    def add_connection(self, parent_txid: str, child_txid: str):
        """Add a connection between two CoinJoin transactions.
        
        Args:
            parent_txid: TXID of the parent CoinJoin
            child_txid: TXID of the child CoinJoin
        """
        # Add connection to connections dictionary
        if parent_txid not in self._connections:
            self._connections[parent_txid] = []
        if child_txid not in self._connections[parent_txid]:
            self._connections[parent_txid].append(child_txid)
            
        # If both nodes exist in the tree, establish parent-child relationship
        if parent_txid in self._nodes_by_txid and child_txid in self._nodes_by_txid:
            parent_node = self._nodes_by_txid[parent_txid]
            child_node = self._nodes_by_txid[child_txid]
            
            parent_node.add_child(child_node)
            
            # If the child was a root node, remove it (it's now connected to a parent)
            if child_node in self.root_nodes:
                self.root_nodes.remove(child_node)
                
            # Invalidate nodes cache
            self._nodes_cache = None
    
    @property
    def nodes(self) -> List[CoinJoinNode]:
        """Get all nodes in this tree."""
        if self._nodes_cache is None:
            # Use a dictionary to track nodes by txid to avoid duplicates
            nodes_dict = {}
            for root in self.root_nodes:
                for node in root.traverse():
                    if node.txid not in nodes_dict:
                        nodes_dict[node.txid] = node
            self._nodes_cache = list(nodes_dict.values())
        return self._nodes_cache

    def bfs_traverse(self) -> Iterator[CoinJoinNode]:
        """Breadth-first traversal over the tree's nodes.

        Starts from all root_nodes and visits children level by level.
        Ensures each txid is yielded at most once in case of shared subtrees.
        """
        seen: Set[str] = set()
        queue: deque[CoinJoinNode] = deque(self.root_nodes)
        while queue:
            node = queue.popleft()
            txid = getattr(node, 'txid', None)
            if txid is None or txid in seen:
                # Skip if missing txid or already visited
                continue
            seen.add(txid)
            yield node
            for child in getattr(node, 'children', []) or []:
                queue.append(child)
    
    @property
    def coinjoins(self) -> List:
        """Get all CoinJoin objects in this tree."""
        if self._coinjoins_cache is None:
            self._coinjoins_cache = [node.get_coinjoin() for node in self.nodes]
        return self._coinjoins_cache
    
    def __str__(self) -> str:
        """Return a string representation of this tree."""
        lines = [f"CoinJoinTree(id={self.id}, analysis_type={self.analysis_type})"]
        
        # Track nodes that have been printed already
        printed_nodes = set()
        
        def _format_node(node, depth=0):
            indent = "  " * depth
            
            # Check if this node has already been printed elsewhere in the tree
            if node.txid in printed_nodes:
                node_str = f"{indent}└─ {node} [REPEATED - not expanded]"
                lines.append(node_str)
                return
                
            # Mark this node as printed
            printed_nodes.add(node.txid)
            
            # Format the current node
            node_str = f"{indent}└─ {node}"
            lines.append(node_str)
            
            # Expand all children (we'll handle repeated nodes when we encounter them)
            for child in node.children:
                _format_node(child, depth + 1)
        
        # Start from root nodes
        for root in self.root_nodes:
            _format_node(root)
            
        return "\n".join(lines)
        
    def start_block(self) -> int:
        """Get the block height of the earliest CoinJoin in this tree."""
        if not self.coinjoins:
            return 0
        return min(cj.block_height for cj in self.coinjoins)
    
    def end_block(self) -> int:
        """Get the block height of the latest CoinJoin in this tree."""
        if not self.coinjoins:
            return 0
        return max(cj.block_height for cj in self.coinjoins)
    
    def duration_blocks(self) -> int:
        """Get the duration of this tree in blocks."""
        if not self.coinjoins:
            return 0
        return self.end_block() - self.start_block()
    
    def length(self) -> int:
        """Get the number of CoinJoins in this tree."""
        return len(self.nodes)
    
    def total_cj_amount(self) -> float:
        """Get the total CoinJoin amount in this tree."""
        return sum(cj.cj_amount for cj in self.coinjoins)
    
    def avg_cj_amount(self) -> float:
        """Get the average CoinJoin amount in this tree."""
        if not self.coinjoins:
            return 0.0
        return self.total_cj_amount() / len(self.coinjoins)
    
    @property
    def tumbler_clients(self) -> Set[str]:
        """Get the set of tumbler clients in this tree: takers, plus zero-fee makers that also take."""
        participants = [p for cj in self.coinjoins for p in cj.participants if p.client]
        takers = {p.client for p in participants if p.role == 'taker'}
        zero_fee = {p.client for p in participants if p.is_tumbler_link and p.client in takers}
        return takers | zero_fee
    
    @property
    def connections(self) -> Dict[str, List[str]]:
        """Get a dictionary mapping CoinJoin txids to lists of child txids."""
        return self._connections.copy()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert this tree to a dictionary for serialization."""
        tree_repr = str(self)
        return {
            "id": self.id,
            "analysis_type": self.analysis_type,
            "length": self.length(),
            "coinjoin_txids": [node.txid for node in self.nodes],
            "connections": self.connections,
            "start_block": self.start_block(),
            "end_block": self.end_block(),
            "duration_blocks": self.duration_blocks(),
            "total_cj_amount": self.total_cj_amount(),
            "avg_cj_amount": self.avg_cj_amount(),
            "tumbler_clients": list(self.tumbler_clients),
            "tree_representation": tree_repr
        }
    
    def to_json(self) -> str:
        """Convert this tree to a JSON string."""
        return json.dumps(self.to_dict(), indent=2)


def identify_coinjoin_chains(coinjoins, analysis_type):
    """
    Identify chains of CoinJoin transactions based on the specified analysis type.
    
    In whitebox mode, chains are identified based on client participation.
    In blackbox mode, chains are identified based on transaction linking.
    
    Args:
        coinjoins: List of CoinJoin objects
        analysis_type: 'whitebox' or 'blackbox'
        
    Returns:
        List of CoinJoinTree objects representing the identified chains
    """
    if not coinjoins:
        return []
    
    # Sort coinjoins by block height
    sorted_cjs = sorted(coinjoins, key=lambda cj: cj.block_height)
    
    # For whitebox mode - group by client
    if analysis_type == 'whitebox':
        return _identify_whitebox_chains(sorted_cjs, analysis_type)
    # For blackbox mode - find chains based on input-output relationships
    else:  # analysis_type == 'blackbox'
        return _identify_blackbox_chains(sorted_cjs, analysis_type)


def _identify_whitebox_chains(sorted_cjs, analysis_type):
    """Identify CoinJoin chains in whitebox mode using recursive approach.
    
    Args:
        sorted_cjs: List of CoinJoin objects sorted by block height
        analysis_type: 'whitebox'
        
    Returns:
        List of CoinJoinTree objects
    """
    # Map client IDs to their CoinJoin transactions
    client_cjs = {}
    client_connections = {}
    
    # A zero-fee maker participation is a tumbler leg only when that client also takes somewhere;
    # otherwise it is an ordinary maker that happens to charge nothing.
    taker_client_ids = {p.client for cj in sorted_cjs for p in cj.participants
                        if p.role == 'taker' and p.client}

    def is_tumbler_leg(p):
        return p.client and (p.role == 'taker' or (p.is_tumbler_link and p.client in taker_client_ids))

    for cj in sorted_cjs:
        tumbler_clients = set()
        for p in cj.participants:
            if is_tumbler_leg(p):
                tumbler_clients.add(p.client)
        
        for client in tumbler_clients:
            if client not in client_cjs:
                client_cjs[client] = []
                client_connections[client] = {}
            client_cjs[client].append(cj)
    
    # Build connections for each client recursively
    for client, client_txs in client_cjs.items():
        # Sort client's transactions by block height
        client_txs.sort(key=lambda cj: cj.block_height)
        _build_client_connections(client, client_txs, client_connections, is_tumbler_leg)
    
    # Create chains based on client groupings
    chains = []
    processed_clients = set()
    processed_txids = set()  # Track which transactions are already in chains
    
    # Process each client to create chains
    for client in client_cjs:
        if client in processed_clients:
            continue
        
        # Create and populate chain for this client and related clients
        chain, chain_clients = _create_client_chain(
            client, client_cjs, client_connections, processed_clients, processed_txids, analysis_type
        )
        
        # Mark all clients in this chain as processed
        processed_clients.update(chain_clients)
        chains.append(chain)
    
    # Transactions outside every client chain (no attributable tumbler) become singleton
    # chains, so each CoinJoin is placed exactly once, as in blackbox mode.
    _add_remaining_singleton_chains(chains, sorted_cjs, processed_txids, analysis_type)

    return chains


def _build_client_connections(client, client_txs, client_connections, is_tumbler_leg):
    """Build connections between transactions for a client recursively.
    
    Args:
        client: Client identifier
        client_txs: List of CoinJoin objects for this client
        client_connections: Dictionary mapping clients to their connection dictionaries
    """
    # Initialize connections dictionary for this client
    for cj in client_txs:
        client_connections[client][cj.txid] = []
    
    # Recursively find connections starting from each transaction
    for i, cj in enumerate(client_txs):
        if i < len(client_txs) - 1:  # Skip the last transaction
            _find_next_connections(client, cj, client_txs[i+1:], client_connections, is_tumbler_leg)


def _find_next_connections(client, current_cj, next_cjs, client_connections, is_tumbler_leg):
    """Recursively find connections from current transaction to next transactions.
    
    Args:
        client: Client identifier
        current_cj: Current CoinJoin object
        next_cjs: List of potential next CoinJoin objects
        client_connections: Dictionary mapping clients to their connection dictionaries
    """
    # Extract outputs from current transaction for this client
    tumbler_outputs = []
    for p in current_cj.participants:
        if is_tumbler_leg(p) and p.client == client:
            if p.cj_output:
                tumbler_outputs.append(p.cj_output)
            if p.change_output:
                tumbler_outputs.append(p.change_output)
    
    # Look for connections to each potential next transaction
    for next_cj in next_cjs:
        # Skip if already connected
        if next_cj.txid in client_connections[client][current_cj.txid]:
            continue
        
        # Check for connections
        for p_next in next_cj.participants:
            if is_tumbler_leg(p_next) and p_next.client == client:
                # Check if any input of next_cj references an output of current_cj
                for inp in p_next.inputs:
                    if inp.txid == current_cj.txid:
                        # Found a connection
                        client_connections[client][current_cj.txid].append(next_cj.txid)
                        break
                
                # If connection found, no need to check other participants
                if next_cj.txid in client_connections[client][current_cj.txid]:
                    break


def _create_client_chain(client, client_cjs, client_connections, processed_clients, processed_txids, analysis_type):
    """Create a chain for a client and related clients recursively.
    
    Args:
        client: Client identifier
        client_cjs: Dictionary mapping clients to their CoinJoin objects
        client_connections: Dictionary mapping clients to their connection dictionaries
        processed_clients: Set of clients already processed
        processed_txids: Set of transaction IDs already in chains
        analysis_type: 'whitebox' or 'blackbox'
        
    Returns:
        Tuple of (CoinJoinTree, set of clients in the chain)
    """
    # Create new chain
    tree = CoinJoinTree(analysis_type=analysis_type)
    chain_clients = {client}
    
    # Add all transactions for this client
    client_txids = set()
    for cj in client_cjs[client]:
        if cj.txid not in processed_txids:
            # Create a node for this transaction
            node = CoinJoinLeafNode(cj)
            tree.add_coinjoin(node)
            processed_txids.add(cj.txid)
            client_txids.add(cj.txid)
    
    # Add connections between transactions
    for txid, connections in client_connections.get(client, {}).items():
        for next_txid in connections:
            if txid in client_txids and next_txid in client_txids:
                tree.add_connection(txid, next_txid)
    
    # Find related clients recursively
    for connected_client in set(client_connections.keys()):
        # Skip if already processed
        if connected_client in processed_clients:
            continue
            
        # Check if connected to this client
        is_connected = False
        for txid, connections in client_connections.get(client, {}).items():
            for next_txid in connections:
                # Check if any client_cjs for connected_client has next_txid
                if any(cj.txid == next_txid for cj in client_cjs.get(connected_client, [])):
                    is_connected = True
                    break
            if is_connected:
                break
                
        if is_connected:
            # Add the related client recursively
            _find_related_clients(connected_client, client_cjs, client_connections,
                                processed_clients, processed_txids, tree,
                                chain_clients, client_txids)
    
    return tree, chain_clients


def _find_related_clients(base_client, client_cjs, client_connections, 
                           processed_clients, processed_txids, tree, 
                           chain_clients, txids_in_chain):
    """Find clients related to the base client and add them to the chain.
    
    Args:
        base_client: Base client identifier
        client_cjs: Dictionary mapping clients to their CoinJoin objects
        client_connections: Dictionary mapping clients to their connection dictionaries
        processed_clients: Set of clients already processed
        processed_txids: Set of transaction IDs already in chains
        tree: CoinJoinTree to add related transactions to
        chain_clients: Set of clients in the chain
        txids_in_chain: Set of transaction IDs already in the chain
    """
    # Add the base client to the chain
    chain_clients.add(base_client)
    processed_clients.add(base_client)
    
    # Add all transactions for this client
    client_txids = set()
    for cj in client_cjs.get(base_client, []):
        if cj.txid not in processed_txids:
            # Create a node for this transaction
            node = CoinJoinLeafNode(cj)
            tree.add_coinjoin(node)
            processed_txids.add(cj.txid)
            txids_in_chain.add(cj.txid)
            client_txids.add(cj.txid)
    
    # Add connections between transactions
    for txid, connections in client_connections.get(base_client, {}).items():
        for next_txid in connections:
            if txid in txids_in_chain and next_txid in txids_in_chain:
                tree.add_connection(txid, next_txid)
    
    # Find related clients recursively
    for connected_client in set(client_connections.keys()):
        # Skip if already processed
        if connected_client in processed_clients:
            continue
            
        # Check if connected to this client
        is_connected = False
        for txid, connections in client_connections.get(base_client, {}).items():
            for next_txid in connections:
                # Check if any client_cjs for connected_client has next_txid
                if any(cj.txid == next_txid for cj in client_cjs.get(connected_client, [])):
                    is_connected = True
                    break
            if is_connected:
                break
                
        if is_connected:
            # Add the related client recursively
            _find_related_clients(connected_client, client_cjs, client_connections,
                                processed_clients, processed_txids, tree,
                                chain_clients, txids_in_chain)


def _identify_blackbox_chains(sorted_cjs, analysis_type):
    """Identify CoinJoin chains in blackbox mode using recursive approach.
    
    Args:
        sorted_cjs: List of CoinJoin objects sorted by block height
        analysis_type: 'blackbox'
        
    Returns:
        List of CoinJoinTree objects
    """
    chains = []
    cjs_in_a_chain = set()
    
    # Build mapping from transaction IDs to CoinJoin objects
    tx_map = {cj.txid: cj for cj in sorted_cjs}
    
    # Set to track which CoinJoins have at least one tumbler participant (taker or zero-fee maker)
    cjs_with_tumbler = set()
    
    # Map to track tumbler inputs for each CoinJoin
    tumbler_inputs = defaultdict(set)
    
    # First pass: collect tumbler inputs
    for cj in sorted_cjs:
        has_tumbler = False
        for participant in cj.participants:
            if participant.is_tumbler_link:
                has_tumbler = True
                for input_tx in participant.inputs:
                    tumbler_inputs[cj.txid].add(input_tx.txid)
        
        if has_tumbler:
            cjs_with_tumbler.add(cj.txid)
    
    # Find potential root transactions (those with tumblers not spending from other CoinJoins)
    root_txids = []
    for cj in sorted_cjs:
        # Skip transactions without tumbler participants
        if cj.txid not in cjs_with_tumbler:
            continue
        
        # A transaction is a root if none of its TUMBLER inputs are from other CoinJoins
        is_root = True
        for input_txid in tumbler_inputs[cj.txid]:
            if input_txid in tx_map:
                is_root = False
                break
        
        if is_root:
            root_txids.append(cj.txid)
    
    def grow_chain(root_txid):
        """Seed a chain at root_txid and extend it breadth-first along tumbler spends."""
        tree = CoinJoinTree(
            id=f"{analysis_type}_chain_{uuid.uuid4().hex[:8]}",
            analysis_type=analysis_type
        )
        tree.add_coinjoin(CoinJoinLeafNode(tx_map[root_txid]))
        cjs_in_a_chain.add(root_txid)

        queue = [root_txid]
        
        while queue:
            current_txid = queue.pop(0)
            current_cj = tx_map[current_txid]
            
            # Find transactions that have a tumbler participant and spend from this one
            for next_cj in sorted_cjs:
                if next_cj.txid in cjs_in_a_chain or next_cj.txid == current_txid:
                    continue
                
                # Skip if it doesn't have a tumbler participant
                if next_cj.txid not in cjs_with_tumbler:
                    continue
                
                # Check if any tumbler inputs of next_cj come from current_cj
                has_tumbler_spending_from_current = False
                
                for participant in next_cj.participants:
                    # Only consider tumbler participants (taker / zero-fee maker) for building chains
                    if not participant.is_tumbler_link:
                        continue
                        
                    for input_tx in participant.inputs:
                        # Check if this input comes from current transaction
                        if input_tx.txid == current_txid:
                            has_tumbler_spending_from_current = True
                            break
                    
                    if has_tumbler_spending_from_current:
                        break
                
                # Only follow tumbler connections
                if has_tumbler_spending_from_current:
                    # Add this transaction to the chain
                    next_node = CoinJoinLeafNode(next_cj)
                    tree.add_coinjoin(next_node)
                    tree.add_connection(current_txid, next_cj.txid)
                    cjs_in_a_chain.add(next_cj.txid)
                    
                    # Add to queue for further processing
                    queue.append(next_cj.txid)

        chains.append(tree)

    for root_txid in root_txids:
        if root_txid not in cjs_in_a_chain:
            grow_chain(root_txid)

    # Transactions whose tumbler inputs come from a CoinJoin that never made it into a chain
    # (e.g. its Sudoku failed) are not roots, yet they head the rest of that chain: grow from
    # them in block order instead of leaving each as a singleton.
    for cj in sorted_cjs:
        if cj.txid not in cjs_in_a_chain and cj.txid in cjs_with_tumbler:
            grow_chain(cj.txid)
    
    # Transactions without any tumbler participant (unsolved or maker-only) still get a
    # singleton chain so every CoinJoin is placed exactly once.
    _add_remaining_singleton_chains(chains, sorted_cjs, cjs_in_a_chain, analysis_type)

    return chains


def _build_blackbox_chain(tree, current_cj, all_cjs, cjs_in_a_chain, has_taker=False):
    """Build CoinJoin chain recursively in blackbox mode.
    
    Args:
        tree: CoinJoinTree to add nodes to
        current_cj: Current CoinJoin object
        all_cjs: List of all CoinJoin objects
        cjs_in_a_chain: Set of CoinJoin transaction IDs already in chains
        has_taker: Whether the chain has a taker participant
    """
    # For each CoinJoin, check if it spends from the current one
    for next_cj in all_cjs:
        if next_cj.txid in cjs_in_a_chain:
            continue
            
        # Check if next_cj spends from current_cj
        spends_from_current, role = _check_spends_from(next_cj, current_cj)
        if not spends_from_current:
            continue
            
        # Don't link taker-based chains with non-taker ones
        # If current chain has a taker, and next tx doesn't, skip
        if has_taker and role != 'taker':
            continue
            
        # If we get here, add this CoinJoin to the chain
        next_node = CoinJoinLeafNode(next_cj)
        tree.add_coinjoin(next_node)
        tree.add_connection(current_cj.txid, next_cj.txid)
        
        # Mark this CJ as processed
        cjs_in_a_chain.add(next_cj.txid)
        
        # Continue building the chain recursively
        _build_blackbox_chain(tree, next_cj, all_cjs, cjs_in_a_chain, has_taker or role == 'taker')


def _is_spending_from_other_cj(cj, all_cjs):
    """Check if a CoinJoin is spending from any other CoinJoin in the set.
    
    Args:
        cj: CoinJoin object to check
        all_cjs: List of all CoinJoin objects
        
    Returns:
        True if spending from another CoinJoin, False otherwise
    """
    for p in cj.participants:
        for inp in p.inputs:
            if any(other_cj.txid == inp.txid for other_cj in all_cjs):
                return True
    return False


def _check_spends_from(next_cj, current_cj):
    """Check if next_cj spends from current_cj and get the role of the participant.
    
    Args:
        next_cj: Next CoinJoin object
        current_cj: Current CoinJoin object
        
    Returns:
        Tuple of (spends_from_current, role)
    """
    # Default role
    role = 'maker'  # Default to maker if we can't determine
    
    # Check if any input of next_cj spends from an output of current_cj
    for input_tx in next_cj.inputs:
        if input_tx.txid == current_cj.txid:
            # If input has client info, check if it's a taker
            if input_tx.client:
                for p in next_cj.participants:
                    if p.client == input_tx.client and p.role == 'taker':
                        role = 'taker'
                        break
            return True, role
    
    return False, role


def _add_remaining_singleton_chains(chains, sorted_cjs, cjs_in_a_chain, analysis_type):
    """Add any remaining transactions as single-tx chains.

    Args:
        chains: List of chains to add to
        sorted_cjs: List of all CoinJoin objects
        cjs_in_a_chain: Set of transaction IDs already in chains
        analysis_type: 'whitebox' or 'blackbox'
    """
    for cj in sorted_cjs:
        if cj.txid not in cjs_in_a_chain:
            tree = CoinJoinTree(analysis_type=analysis_type)
            node = CoinJoinLeafNode(cj)
            tree.add_coinjoin(node)
            chains.append(tree)


def rebuild_chains_with_new_connections(coinjoins, old_chains, new_connections, analysis_type):
    """
    Rebuild chains incorporating newly discovered connections.

    Strategy:
    1. Re-run chain identification from scratch
    2. Add the new connections to appropriate chains
    3. Merge chains if needed when new connections bridge them

    Args:
        coinjoins: List of all CoinJoin objects
        old_chains: Previous chains (for reference, not directly used)
        new_connections: List of (parent_txid, child_txid) tuples
        analysis_type: 'whitebox' or 'blackbox'

    Returns:
        List of CoinJoinTree objects with new connections incorporated
    """
    # Re-run chain identification
    chains = identify_coinjoin_chains(coinjoins, analysis_type)

    # Build mapping of txid to chain
    txid_to_chain = {}
    for chain in chains:
        for node in chain.nodes:
            txid_to_chain[node.txid] = chain

    # Process each new connection
    for parent_txid, child_txid in new_connections:
        # Find chains containing parent and child
        parent_chain = txid_to_chain.get(parent_txid)
        child_chain = txid_to_chain.get(child_txid)

        if not parent_chain or not child_chain:
            # One or both transactions not in any chain
            # This shouldn't happen if chain identification is working correctly
            print(f"Warning: Cannot add connection {parent_txid[:8]} -> {child_txid[:8]} "
                  f"(one or both not in chains)")
            continue

        if parent_chain == child_chain:
            # Both in same chain, just add the connection
            parent_chain.add_connection(parent_txid, child_txid)
        else:
            # In different chains - need to merge
            # Add all nodes from child_chain to parent_chain
            for node in child_chain.nodes:
                if node.txid not in txid_to_chain or txid_to_chain[node.txid] != parent_chain:
                    parent_chain.add_coinjoin(node)
                    txid_to_chain[node.txid] = parent_chain

            # Add all connections from child_chain to parent_chain
            for conn_parent_txid, conn_child_txids in child_chain.connections.items():
                for conn_child_txid in conn_child_txids:
                    parent_chain.add_connection(conn_parent_txid, conn_child_txid)

            # Add the new connection
            parent_chain.add_connection(parent_txid, child_txid)

            # Remove child_chain from chains list
            if child_chain in chains:
                chains.remove(child_chain)

    return chains
