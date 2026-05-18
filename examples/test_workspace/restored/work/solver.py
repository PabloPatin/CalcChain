from pathlib import Path


mesh = Path('input/mesh.txt').read_text(encoding='utf-8')
Path('results').mkdir(exist_ok=True)
Path('logs').mkdir(exist_ok=True)
Path('results/value.txt').write_text(mesh.upper(), encoding='utf-8')
Path('logs/solver.log').write_text('done', encoding='utf-8')
