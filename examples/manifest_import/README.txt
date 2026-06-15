CalcChain manifest import example
=================================

Use this folder to test importing an existing calculation from manifest.json.

In the CalcChain UI:

1. Click Import in the graph toolbar, or drag manifest.json onto the graph canvas.
2. Choose:

   examples/manifest_import/manifest.json

3. The imported graph should appear as a separate group of nodes.
4. The backend creates the imported job environment under:

   .calcchain_backend/manifest_imports/manifest_<id>/job

This example describes one code source and two local input sources. The imported
graph includes local source nodes, a calculation node, an output artifact node,
and a local target output node.
