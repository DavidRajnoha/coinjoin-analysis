def write_html_report(coinjoin_results, out_path, cj_flow_graph_data=None):
    html = ['<html><head><meta charset="utf-8"><title>CoinJoin Sudoku Report</title>',
            '<style>body{font-family:sans-serif;}table{border-collapse:collapse;}td,th{border:1px solid #ccc;padding:4px;}th{background:#eee;}tr.taker{background:#ffe;}tr.maker{background:#efe;}tr.unknown{background:#fdd;}</style>',
            '</head><body>']
    html.append('<h1>CoinJoin Sudoku Report</h1>')
    if cj_flow_graph_data:
        import json
        html.append('<h2>CoinJoin-to-CoinJoin Flow Graph</h2>')
        html.append('<div id="cjflowgraph" style="width:95vw; height:600px; border:1px solid #aaa;"></div>')
        html.append('<script type="text/javascript" src="https://unpkg.com/vis-network@9.1.2/dist/vis-network.min.js"></script>')
        html.append('<script type="text/javascript">')
        html.append(f'const cjFlowData = {json.dumps(cj_flow_graph_data)};')
        html.append('const nodes = new vis.DataSet(cjFlowData.nodes.map(n => ({id: n, label: n.length > 16 ? n.slice(0,8)+".."+n.slice(-6) : n, color: n.match(/^([0-9a-f]{64})$/) ? "#87ceeb" : (n.match(/^([13][a-km-zA-HJ-NP-Z1-9]{25,34})$/) ? "#f9e79f" : "#bbb"), x: cjFlowData.positions[n]?.x, y: cjFlowData.positions[n]?.y})));')
        html.append('const edges = new vis.DataSet(cjFlowData.edges.map(e => ({from: e.from, to: e.to, label: e.label, color: e.role==="taker" ? "#e67e22" : e.role==="maker" ? "#2ecc40" : "#999", arrows: "to", font:{align:"top"}})));')
        html.append('const container = document.getElementById("cjflowgraph");')
        html.append('const data = {nodes: nodes, edges: edges};')
        html.append('const options = {layout: {improvedLayout:false}, physics: false, edges: {smooth: {type: "dynamic"}, font: {size: 10}}, nodes: {shape: "ellipse", font: {size: 12, bold: true}}};')
        html.append('new vis.Network(container, data, options);')
        html.append('</script>')
    for cj in coinjoin_results:
        txid = cj['txid']
        html.append(f'<h2>CoinJoin txid: <code>{txid}</code></h2>')
        if not cj['solutions']:
            html.append('<p style="color:red;">No valid JoinMarket-style decomposition found.</p>')
            continue
        for sol_num, sol in enumerate(cj['solutions'], 1):
            html.append(f'<h3>Solution {sol_num}</h3>')
            html.append('<table>')
            html.append('<tr><th>Role</th><th>Inputs</th><th>Input Value Sum</th><th>Change Output</th><th>CoinJoin Output</th><th>Delta</th></tr>')
            for p in sol:
                role = p['role']
                in_str = '<br>'.join([f"{vin['vin']['txid']}:{vin['vin']['vout']} ({vin['value']:.8f})" for vin in p['inputs']])
                in_sum = sum(vin['value'] for vin in p['inputs'])
                ch_out = p['change']
                ch_str = f"n={ch_out['n']}, value={ch_out['value']:.8f}" if ch_out else '-'
                cj_out = p['cj']
                cj_str = f"n={cj_out['n']}, value={cj_out['value']:.8f}" if cj_out else '-'
                delta = f"{p['delta']:.8f}"
                html.append(f'<tr class="{role}"><td>{role}</td><td>{in_str}</td><td>{in_sum:.8f}</td><td>{ch_str}</td><td>{cj_str}</td><td>{delta}</td></tr>')
            html.append('</table>')
    html.append('</body></html>')
    with open(out_path, 'w') as f:
        f.write('\n'.join(html))