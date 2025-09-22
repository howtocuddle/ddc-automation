#!/usr/bin/env python3
"""Generate an interactive HTML network graph of the brute-force+range hierarchy.

Data source: Sch*.bfrange.json (produced by fix_hierarchy_bruteforce_ranges.py)
Large graph strategy:
 - Start with only top-level (no dot) codes ("main classes") and NO children; on-demand expansion.
 - Color: root=lightgreen, range=orange, other=lightblue.
Enhancements:
 - Double-click expands.
 - Toggle shows prefLabel + first scope snippet.
 - Cross-reference edges (dashed) from seeAlso scope notes (codes pattern).
"""
from __future__ import annotations
import json, re
from pathlib import Path

INPUT_FILES = sorted(Path('processed').glob('Sch*.deduped.json'))
OUTPUT_FILE = Path('hierarchy_graph.html')

entries = []
for f in INPUT_FILES:
    try:
        data = json.loads(f.read_text(encoding='utf-8'))
        if isinstance(data, list):
            entries.extend(data)
    except Exception:
        pass

code_to_entry = {}
children_map = {}
for e in entries:
    code = e.get('bfCode') or e.get('fullNotation') or e.get('notation') or e.get('id')
    if code not in code_to_entry:
        code_to_entry[code] = e
    hier = e.get('hierarchy') or {}
    kids = hier.get('narrower') or []
    if code not in children_map:
        children_map[code] = set()
    for k in kids:
        children_map[code].add(k)

three_digit_pattern = re.compile(r'^\d{3}$')
initial_nodes = {code for code in code_to_entry if three_digit_pattern.match(code)}

nodes_js = []
edges_js = []  # currently not adding child edges initially
for code in initial_nodes:
    e = code_to_entry.get(code)
    lab = (e.get('prefLabel') or {}).get('en') if e else ''
    title = f"<b>{code}</b>" + (f"<br>{lab}" if lab else '')
    color = 'lightgreen'
    nodes_js.append({'id': code,'label': code,'title': title,'color': {'background': color,'border':'gray'},'shape':'box'})

children_map_serializable = {k: sorted(v) for k,v in children_map.items()}

meta = {}
code_pattern = re.compile(r"\b\d{3}(?:\.\d+)?\b")
for code, e in code_to_entry.items():
    scope = e.get('scope') or {}
    pref = (e.get('prefLabel') or {}).get('en') or ''
    snippet = ''
    for key in ('notes','classHere','including'):
        arr = scope.get(key) or []
        if arr:
            snippet = arr[0][:80]
            break
    refs = set()
    for line in scope.get('seeAlso') or []:
        for m in code_pattern.findall(line):
            if m != code:
                refs.add(m)
        meta[code] = {'pref': pref,'snippet': snippet,'seeRefs': sorted(refs)}

# Build HTML directly without templates
html_parts = []
html_parts.append('<!DOCTYPE html>')
html_parts.append('<html lang="en">')
html_parts.append('<head>')
html_parts.append('<meta charset="utf-8" />')
html_parts.append('<title>Hierarchy Graph</title>')
html_parts.append('<script src="https://unpkg.com/vis-network@9.1.6/dist/vis-network.min.js"></script>')
html_parts.append('<link rel="stylesheet" href="https://unpkg.com/vis-network@9.1.6/dist/vis-network.min.css" />')
html_parts.append('<style>')
html_parts.append('  body { font-family: Arial, sans-serif; margin:0; padding:0; }')
html_parts.append('  #toolbar { padding:8px; background:#eee; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }')
html_parts.append('  #network { width:100vw; height:calc(100vh - 60px); border-top:1px solid #ccc; }')
html_parts.append('  input[type=text] { padding:4px; }')
html_parts.append('  button { padding:6px 10px; cursor:pointer; }')
html_parts.append('</style>')
html_parts.append('</head>')
html_parts.append('<body>')
html_parts.append('<div id="toolbar">')
html_parts.append('  <button id="togglePhysics">Toggle Physics</button>')
html_parts.append('  <button id="toggleHeadings">Show Headings</button>')
html_parts.append('  <button id="expandSelection">Expand Selection</button>')
html_parts.append('  <button id="expandAllChildren">Expand All Children (Visible Roots)</button>')
html_parts.append('  <input id="searchBox" type="text" placeholder="Search code..." />')
html_parts.append('  <button id="searchBtn">Search</button>')
html_parts.append('  <span id="status"></span>')
html_parts.append('</div>')
html_parts.append('<div id="network"></div>')
html_parts.append('<script>')
html_parts.append('console.log("Starting hierarchy graph...");')
html_parts.append('const initialNodes = ' + json.dumps(nodes_js) + ';')
html_parts.append('const initialEdges = ' + json.dumps(edges_js) + ';')
html_parts.append('const allChildren = ' + json.dumps(children_map_serializable) + ';')
html_parts.append('const meta = ' + json.dumps(meta) + ';')
html_parts.append('console.log("Loaded", initialNodes.length, "initial nodes");')
html_parts.append('let showHeadings = false;')
html_parts.append('const nodeCache = {};')
html_parts.append('const added = new Set(initialNodes.map(n=>n.id));')
html_parts.append('function computeNode(code) {')
html_parts.append('  let color="lightblue";')
html_parts.append('  if(code.indexOf("-")!==-1) color="orange";')
html_parts.append('  else if(code.indexOf(".")===-1) color="lightgreen";')
html_parts.append('  const m = meta[code]||{};')
html_parts.append('  let label = code;')
html_parts.append('  if (showHeadings) { if(m.pref) label += "\\n"+m.pref.substring(0,50); if(m.snippet) label += "\\n"+m.snippet.substring(0,60); }')
html_parts.append('  let title = `<b>${code}</b>`;')
html_parts.append('  if(m.pref) title += `<br>${m.pref}`;')
html_parts.append('  if(m.snippet) title += `<br><i>${m.snippet}</i>`;')
html_parts.append('  return { id: code, label: label, title: title, color: {background: color, border: "gray"}, shape:"box" };')
html_parts.append('}')
html_parts.append('for (const n of initialNodes) { nodeCache[n.id]=n; }')
html_parts.append('const nodes = new vis.DataSet(initialNodes);')
html_parts.append('const edges = new vis.DataSet(initialEdges);')
html_parts.append('let physicsEnabled=true;')
html_parts.append('const network = new vis.Network(document.getElementById("network"), {nodes,edges}, { physics: {enabled:physicsEnabled, stabilization:false, solver:"forceAtlas2Based", timestep:0.35}, interaction: {hover:true}, layout: {improvedLayout:true} });')
html_parts.append('network.fit();')
html_parts.append('console.log("Network initialized and fitted");')
html_parts.append('function expandNode(code) {')
html_parts.append('  const kids = allChildren[code]||[]; let addedCount=0;')
html_parts.append('  for (const k of kids) {')
html_parts.append('    if(!added.has(k)) { nodes.add(computeNode(k)); edges.add({from:code,to:k}); added.add(k); addedCount++; }')
html_parts.append('    else if(!edges.get({filter:e=>e.from===code && e.to===k}).length) edges.add({from:code,to:k});')
html_parts.append('  }')
html_parts.append('  const m = meta[code];')
html_parts.append('  if(m&&m.seeRefs) { for(const ref of m.seeRefs) { if(ref===code) continue; if(!added.has(ref) && /^\\d{3}$/.test(ref)) { nodes.add(computeNode(ref)); added.add(ref); } if(added.has(ref) && !edges.get({filter:e=>(e.from===code&&e.to===ref)||(e.from===ref&&e.to===code)}).length) edges.add({from:code,to:ref,dashes:true,color:{color:"#aa5500"},width:2}); } }')
html_parts.append('  return addedCount;')
html_parts.append('}')
html_parts.append('document.getElementById("togglePhysics").onclick=()=>{ physicsEnabled=!physicsEnabled; network.setOptions({physics:{enabled:physicsEnabled}}); };')
html_parts.append('document.getElementById("expandSelection").onclick=()=>{ const sel=network.getSelectedNodes(); let total=0; sel.forEach(c=>total+=expandNode(c)); document.getElementById("status").textContent=`Added ${total} nodes.`; };')
html_parts.append('document.getElementById("expandAllChildren").onclick=()=>{ let total=0; nodes.get().forEach(n=>total+=expandNode(n.id)); document.getElementById("status").textContent=`Added ${total} nodes.`; };')
html_parts.append('document.getElementById("toggleHeadings").onclick=()=>{ showHeadings=!showHeadings; document.getElementById("toggleHeadings").textContent= showHeadings? "Hide Headings":"Show Headings"; nodes.get().forEach(n=>{ const nn=computeNode(n.id); nodes.update({id:n.id,label:nn.label,title:nn.title}); }); };')
html_parts.append('network.on("doubleClick",p=>{ if(p.nodes&&p.nodes.length){ const c=p.nodes[0]; const g=expandNode(c); document.getElementById("status").textContent=`Expanded ${c} (+${g})`; } });')
html_parts.append('function search(term){ term=term.toLowerCase(); const candidates=Object.keys(allChildren).filter(c=>c.toLowerCase().includes(term)); if(!candidates.length) return document.getElementById("status").textContent="No match"; const first=candidates[0]; if(!added.has(first)) expandNode(first); network.selectNodes([first]); network.focus(first, {scale:1.1, animation: {duration:500,easing:"easeInOutQuad"}}); document.getElementById("status").textContent=`Focused ${first} (${candidates.length} match(es))`; }')
html_parts.append('document.getElementById("searchBtn").onclick=()=>{ const v=document.getElementById("searchBox").value.trim(); if(v) search(v); };')
html_parts.append('document.getElementById("searchBox").addEventListener("keydown",e=>{ if(e.key==="Enter"){ const v=e.target.value.trim(); if(v) search(v); } });')
html_parts.append('</script>')
html_parts.append('</body>')
html_parts.append('</html>')

html = '\n'.join(html_parts)

# Use unique tokens to avoid str.format brace collisions
html_template = """<!DOCTYPE html>
<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\" />\n<title>Hierarchy Graph</title>\n<script src=\"https://unpkg.com/vis-network@9.1.6/dist/vis-network.min.js\"></script>\n<link rel=\"stylesheet\" href=\"https://unpkg.com/vis-network@9.1.6/dist/vis-network.min.css\" />\n<style>\n  body {{ font-family: Arial, sans-serif; margin:0; padding:0; }}\n  #toolbar {{ padding:8px; background:#eee; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}\n  #network {{ width:100vw; height:calc(100vh - 60px); border-top:1px solid #ccc; }}\n  input[type=text] {{ padding:4px; }}\n  button {{ padding:6px 10px; cursor:pointer; }}\n</style>\n</head>\n<body>\n<div id=\"toolbar\">\n  <button id=\"togglePhysics\">Toggle Physics</button>\n  <button id=\"toggleHeadings\">Show Headings</button>\n  <button id=\"expandSelection\">Expand Selection</button>\n  <button id=\"expandAllChildren\">Expand All Children (Visible Roots)</button>\n  <input id=\"searchBox\" type=\"text\" placeholder=\"Search code...\" />\n  <button id=\"searchBtn\">Search</button>\n  <span id=\"status\"></span>\n</div>\n<div id=\"network\"></div>\n<script>\nconst initialNodes = __NODES__;\nconst initialEdges = __EDGES__;\nconst allChildren = __CHILDREN__;\nconst meta = __META__;\nlet showHeadings = false;\nconst nodeCache = {{}};\nconst added = new Set(initialNodes.map(n=>n.id));\nfunction computeNode(code) {{\n  let color='lightblue';\n  if(code.indexOf('-')!==-1) color='orange';\n  else if(code.indexOf('.')===-1) color='lightgreen';\n  const m = meta[code]||{{}};\n  let label = code;\n  if (showHeadings) {{ if(m.pref) label += "\\n"+m.pref.substring(0,50); if(m.snippet) label += "\\n"+m.snippet.substring(0,60); }}\n  let title = `<b>\\${{code}}</b>`;\n  if(m.pref) title += `<br>\\${{m.pref}}`;\n  if(m.snippet) title += `<br><i>\\${{m.snippet}}</i>`;\n  return {{ id: code, label: label, title: title, color: {{background: color, border: 'gray'}}, shape:'box' }};\n}}\nfor (const n of initialNodes) {{ nodeCache[n.id]=n; }}\nconst nodes = new vis.DataSet(initialNodes);\nconst edges = new vis.DataSet(initialEdges);\nlet physicsEnabled=true;\nconst network = new vis.Network(document.getElementById('network'), {{nodes,edges}}, {{ physics: {{enabled:physicsEnabled, stabilization:false, solver:'forceAtlas2Based', timestep:0.35}}, interaction: {{hover:true}}, layout: {{improvedLayout:true}} }});\nfunction expandNode(code) {{\n  const kids = allChildren[code]||[]; let addedCount=0;\n  for (const k of kids) {{\n    if(!added.has(k)) {{ nodes.add(computeNode(k)); edges.add({{from:code,to:k}}); added.add(k); addedCount++; }}\n    else if(!edges.get({{filter:e=>e.from===code && e.to===k}}).length) edges.add({{from:code,to:k}});\n  }}\n  const m = meta[code];\n  if(m&&m.seeRefs) {{ for(const ref of m.seeRefs) {{ if(ref===code) continue; if(!added.has(ref) && /^\d{3}$/.test(ref)) {{ nodes.add(computeNode(ref)); added.add(ref); }} if(added.has(ref) && !edges.get({{filter:e=>(e.from===code&&e.to===ref)||(e.from===ref&&e.to===code)}}).length) edges.add({{from:code,to:ref,dashes:true,color:{{color:'#aa5500'}},width:2}}); }} }}\n  return addedCount;\n}}\ndocument.getElementById('togglePhysics').onclick=()=>{{ physicsEnabled=!physicsEnabled; network.setOptions({{physics:{{enabled:physicsEnabled}}}}); }};\ndocument.getElementById('expandSelection').onclick=()=>{{ const sel=network.getSelectedNodes(); let total=0; sel.forEach(c=>total+=expandNode(c)); document.getElementById('status').textContent=`Added \\${{total}} nodes.`; }};\ndocument.getElementById('expandAllChildren').onclick=()=>{{ let total=0; nodes.get().forEach(n=>total+=expandNode(n.id)); document.getElementById('status').textContent=`Added \\${{total}} nodes.`; }};\ndocument.getElementById('toggleHeadings').onclick=()=>{{ showHeadings=!showHeadings; document.getElementById('toggleHeadings').textContent= showHeadings? 'Hide Headings':'Show Headings'; nodes.get().forEach(n=>{{ const nn=computeNode(n.id); nodes.update({{id:n.id,label:nn.label,title:nn.title}}); }}); }};\nnetwork.on('doubleClick',p=>{{ if(p.nodes&&p.nodes.length){{ const c=p.nodes[0]; const g=expandNode(c); document.getElementById('status').textContent=`Expanded \\${{c}} (+\\${{g}})`; }} }});\nfunction search(term){{ term=term.toLowerCase(); const candidates=Object.keys(allChildren).filter(c=>c.toLowerCase().includes(term)); if(!candidates.length) return document.getElementById('status').textContent='No match'; const first=candidates[0]; if(!added.has(first)) expandNode(first); network.selectNodes([first]); network.focus(first, {{scale:1.1, animation: {{duration:500,easing:'easeInOutQuad'}}}}); document.getElementById('status').textContent=`Focused \\${{first}} (\\${{candidates.length}} match(es))`; }}\ndocument.getElementById('searchBtn').onclick=()=>{{ const v=document.getElementById('searchBox').value.trim(); if(v) search(v); }};\ndocument.getElementById('searchBox').addEventListener('keydown',e=>{{ if(e.key==='Enter'){{ const v=e.target.value.trim(); if(v) search(v); }} }});\n</script>\n</body>\n</html>\n"""

# Perform safe replacements
html = (html_template
        .replace('__NODES__', json.dumps(nodes_js))
        .replace('__EDGES__', json.dumps(edges_js))
        .replace('__CHILDREN__', json.dumps(children_map_serializable))
        .replace('__META__', json.dumps(meta)))

OUTPUT_FILE.write_text(html, encoding='utf-8')
print(f"Wrote {OUTPUT_FILE} with {len(initial_nodes)} initial nodes (enhanced).")
