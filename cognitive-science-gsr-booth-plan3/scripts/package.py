from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json

root = Path('python/oriori_gsr')
output = Path('public/downloads/oriori_gsr.zip')
output.parent.mkdir(parents=True, exist_ok=True)
excluded = {'.venv', '__pycache__', 'data', '.env', '.DS_Store', 'analysis_summary.csv'}
manifest = {}
with ZipFile(output, 'w', ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root)
        if not path.is_file() or any(p in excluded for p in rel.parts) or path.suffix in ('.pyc', '.log'):
            continue
        data = path.read_bytes()
        manifest[str(rel)] = hashlib.sha256(data).hexdigest()
        archive.writestr('oriori_gsr/' + str(rel), data)
    archive.writestr('oriori_gsr/MANIFEST.json', json.dumps(manifest, indent=2))
print(f'{output}: {output.stat().st_size:,} bytes, {len(manifest)} files + SHA-256 manifest')
