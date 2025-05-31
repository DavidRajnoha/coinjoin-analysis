#!/usr/bin/env python3
"""
Test script to verify our tree-based CoinJoin chain detection implementation
works correctly with report generation.
"""

import os
from joinmarket.common.coinjoin_model import CoinJoin, CoinJoinParticipant, TxInput, TxOutput
from joinmarket.common.coinjoin_chain import identify_coinjoin_chains, CoinJoinTree
from joinmarket.unified_report.create_report import generate_unified_report

def create_test_data():
    """Create a simple test dataset with branching chains"""
    
    # Create a series of CoinJoin transactions forming a tree structure
    
    # First transaction (root)
    p1_cj1 = CoinJoinParticipant(
        role="taker",
        client="clientA",
        inputs=[TxInput(txid="prev_tx1", vout=0, value=1.0, client="clientA")],
        cj_output=TxOutput(n=0, value=0.9, address="addr_cj1_out1", client="clientA"),
        change_output=TxOutput(n=1, value=0.09, address="addr_cj1_out2", client="clientA")
    )
    
    p2_cj1 = CoinJoinParticipant(
        role="maker",
        client="clientB",
        inputs=[TxInput(txid="prev_tx2", vout=0, value=1.0, client="clientB")],
        cj_output=TxOutput(n=2, value=0.9, address="addr_cj1_out3", client="clientB"),
        change_output=TxOutput(n=3, value=0.09, address="addr_cj1_out4", client="clientB")
    )
    
    cj1 = CoinJoin(
        txid="tx1",
        block_height=100,
        tx={"vin": [], "vout": []},  # Simplified tx data
        participants=[p1_cj1, p2_cj1]
    )
    
    # Second transaction (first branch)
    p1_cj2 = CoinJoinParticipant(
        role="taker",
        client="clientA",
        inputs=[TxInput(txid="tx1", vout=0, value=0.9, client="clientA")],
        cj_output=TxOutput(n=0, value=0.8, address="addr_cj2_out1", client="clientA"),
        change_output=TxOutput(n=1, value=0.09, address="addr_cj2_out2", client="clientA")
    )
    
    p2_cj2 = CoinJoinParticipant(
        role="maker",
        client="clientC",
        inputs=[TxInput(txid="prev_tx3", vout=0, value=1.0, client="clientC")],
        cj_output=TxOutput(n=2, value=0.8, address="addr_cj2_out3", client="clientC"),
        change_output=TxOutput(n=3, value=0.19, address="addr_cj2_out4", client="clientC")
    )
    
    cj2 = CoinJoin(
        txid="tx2",
        block_height=101,
        tx={"vin": [], "vout": []},  # Simplified tx data
        participants=[p1_cj2, p2_cj2]
    )
    
    # Third transaction (second branch)
    p1_cj3 = CoinJoinParticipant(
        role="taker", 
        client="clientA",
        inputs=[TxInput(txid="tx1", vout=1, value=0.09, client="clientA")],
        cj_output=TxOutput(n=0, value=0.07, address="addr_cj3_out1", client="clientA"),
        change_output=TxOutput(n=1, value=0.01, address="addr_cj3_out2", client="clientA")
    )
    
    p2_cj3 = CoinJoinParticipant(
        role="maker",
        client="clientD",
        inputs=[TxInput(txid="prev_tx4", vout=0, value=1.0, client="clientD")],
        cj_output=TxOutput(n=2, value=0.07, address="addr_cj3_out3", client="clientD"),
        change_output=TxOutput(n=3, value=0.92, address="addr_cj3_out4", client="clientD")
    )
    
    cj3 = CoinJoin(
        txid="tx3",
        block_height=102,
        tx={"vin": [], "vout": []},  # Simplified tx data
        participants=[p1_cj3, p2_cj3]
    )
    
    # Fourth transaction (from the first branch)
    p1_cj4 = CoinJoinParticipant(
        role="taker",
        client="clientA",
        inputs=[TxInput(txid="tx2", vout=0, value=0.8, client="clientA")],
        cj_output=TxOutput(n=0, value=0.7, address="addr_cj4_out1", client="clientA"),
        change_output=TxOutput(n=1, value=0.09, address="addr_cj4_out2", client="clientA")
    )
    
    p2_cj4 = CoinJoinParticipant(
        role="maker",
        client="clientE",
        inputs=[TxInput(txid="prev_tx5", vout=0, value=1.0, client="clientE")],
        cj_output=TxOutput(n=2, value=0.7, address="addr_cj4_out3", client="clientE"),
        change_output=TxOutput(n=3, value=0.29, address="addr_cj4_out4", client="clientE")
    )
    
    cj4 = CoinJoin(
        txid="tx4",
        block_height=103,
        tx={"vin": [], "vout": []},  # Simplified tx data
        participants=[p1_cj4, p2_cj4]
    )
    
    # Fifth transaction (orphaned, not connected to any chain)
    p1_cj5 = CoinJoinParticipant(
        role="taker",
        client="clientF",
        inputs=[TxInput(txid="prev_tx6", vout=0, value=1.0, client="clientF")],
        cj_output=TxOutput(n=0, value=0.9, address="addr_cj5_out1", client="clientF"),
        change_output=TxOutput(n=1, value=0.09, address="addr_cj5_out2", client="clientF")
    )
    
    p2_cj5 = CoinJoinParticipant(
        role="maker",
        client="clientG",
        inputs=[TxInput(txid="prev_tx7", vout=0, value=1.0, client="clientG")],
        cj_output=TxOutput(n=2, value=0.9, address="addr_cj5_out3", client="clientG"),
        change_output=TxOutput(n=3, value=0.09, address="addr_cj5_out4", client="clientG")
    )
    
    cj5 = CoinJoin(
        txid="tx5",
        block_height=104,
        tx={"vin": [], "vout": []},  # Simplified tx data
        participants=[p1_cj5, p2_cj5]
    )
    
    return [cj1, cj2, cj3, cj4, cj5]

def main():
    """Main function to test chain detection and report generation"""
    
    # Create test data
    coinjoins = create_test_data()
    
    print(f"Created {len(coinjoins)} CoinJoin transactions")
    
    # Identify chains in blackbox mode
    blackbox_chains = identify_coinjoin_chains(coinjoins, 'blackbox')
    print(f"Identified {len(blackbox_chains)} chains in blackbox mode")
    
    # Display chain information using the new __str__ method
    for i, chain in enumerate(blackbox_chains):
        print(f"\nChain {i+1} details:")
        print(chain)
    
    # Identify chains in whitebox mode
    whitebox_chains = identify_coinjoin_chains(coinjoins, 'whitebox')
    print(f"\nIdentified {len(whitebox_chains)} chains in whitebox mode")
    
    # Display chain information using the new __str__ method
    for i, chain in enumerate(whitebox_chains):
        print(f"\nChain {i+1} details:")
        print(chain)
    
    # Generate a report for both analysis types
    output_dir = "../../report_output"
    os.makedirs(output_dir, exist_ok=True)
    
    # Create simplified report showing just the chain structure
    with open(os.path.join(output_dir, "chains_only_report.html"), "w") as f:
        # Use the to_dict() method for serialization
        bb_chains_serialized = [chain.to_dict() for chain in blackbox_chains]
        wb_chains_serialized = [chain.to_dict() for chain in whitebox_chains]
        
        f.write("<html><head><title>CoinJoin Chain Report</title>")
        f.write("<style>body{font-family:Arial,sans-serif;max-width:1200px;margin:0 auto;padding:20px}")
        f.write("table{border-collapse:collapse;width:100%}")
        f.write("th,td{border:1px solid #ddd;padding:8px;}")
        f.write("th{background-color:#f2f2f2}")
        f.write("pre{background-color:#f5f5f5;padding:10px;border-radius:4px;overflow:auto;}</style></head><body>")
        
        f.write("<h1>CoinJoin Chain Analysis</h1>")
        
        # Display blackbox chains
        f.write("<h2>Blackbox Analysis Chains</h2>")
        f.write("<table><tr><th>Chain ID</th><th>Length</th><th>TXIDs</th><th>Connections</th></tr>")
        for chain in bb_chains_serialized:
            f.write(f"<tr><td>{chain['id']}</td><td>{chain['length']}</td>")
            f.write(f"<td>{', '.join(chain['coinjoin_txids'])}</td>")
            f.write(f"<td><pre>{chain['connections']}</pre></td></tr>")
        f.write("</table>")
        
        # Display whitebox chains
        f.write("<h2>Whitebox Analysis Chains</h2>")
        f.write("<table><tr><th>Chain ID</th><th>Length</th><th>TXIDs</th><th>Connections</th><th>Taker Clients</th></tr>")
        for chain in wb_chains_serialized:
            f.write(f"<tr><td>{chain['id']}</td><td>{chain['length']}</td>")
            f.write(f"<td>{', '.join(chain['coinjoin_txids'])}</td>")
            f.write(f"<td><pre>{chain['connections']}</pre></td>")
            f.write(f"<td>{', '.join(chain['taker_clients'])}</td></tr>")
        f.write("</table>")
        
        # Add visualized tree structure
        f.write("<h2>Tree Visualization</h2>")
        
        # Visualize each chain's tree structure
        f.write("<h3>Blackbox Chains</h3>")
        for i, chain in enumerate(blackbox_chains):
            f.write(f"<h4>Chain {i+1}: {chain.id}</h4>")
            f.write(f"<pre>{str(chain)}</pre>")
        
        f.write("<h3>Whitebox Chains</h3>")
        for i, chain in enumerate(whitebox_chains):
            f.write(f"<h4>Chain {i+1}: {chain.id}</h4>")
            f.write(f"<pre>{str(chain)}</pre>")
        
        f.write("</body></html>")
    
    print(f"\nGenerated chain report in: {output_dir}/chains_only_report.html")
    print("The report includes visual tree representations of the chain structure.")

if __name__ == "__main__":
    main()
