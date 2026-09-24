"""Create the distribution ZIP after successful packaged verification."""
import hashlib
import importlib.metadata
import json
import shutil
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent
portable = root / 'Portable' / 'MIR Cleanup'
verification = root / 'Verification'
report = json.loads((verification / 'packaged-verification.json').read_text(encoding='utf-8'))
if not report['passed'] or not report['frozen']:
    raise SystemExit('A successful frozen verification report is required.')
parity = json.loads((verification / 'numerical-parity.json').read_text(encoding='utf-8'))
if not parity['passed']:
    raise SystemExit('Numerical parity verification is required.')
if not (portable / 'MIR Cleanup.exe').is_file():
    raise SystemExit('Build the executable first.')
shutil.copy2(root / 'WINDOWS_APP_GUIDE.md', portable / 'WINDOWS_APP_GUIDE.md')
shutil.copy2(root / 'RELEASE_NOTES.md', portable / 'RELEASE_NOTES.md')
evidence = portable / 'Verification'
evidence.mkdir(exist_ok=True)
for name in ['packaged-verification.json', 'numerical-parity.json',
             'regression-tests.log', 'input-data-issues.json', 'release-verification.json']:
    shutil.copy2(verification / name, evidence / name)
licenses = portable / 'Third-party licenses'
licenses.mkdir(exist_ok=True)
inventory = []
for dist in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
    name = dist.metadata['Name']
    entry = {'name': name, 'version': dist.version,
             'homepage': dist.metadata.get('Home-page', ''),
             'project_urls': dist.metadata.get_all('Project-URL') or []}
    inventory.append(entry)
# Keep the distribution compact: the inventory records each package's license
# metadata; the bundled runtime already contains the files required to execute.
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if python_license.exists():
    shutil.copy2(python_license, licenses / 'Python-LICENSE.txt')
(licenses / 'dependency-inventory.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
(portable / 'START HERE.txt').write_text(
    'MIR Cleanup 1.2.1 - Windows build 1\n\n'
    'Extract the whole ZIP, then double-click MIR Cleanup.exe.\n'
    'Keep the _internal folder beside the executable. Python is included.\n'
    'Read WINDOWS_APP_GUIDE.md for the workflow and supplied-data notes.\n'
    'See RELEASE_NOTES.md for completed checks and remaining acceptance checks.\n', encoding='utf-8')
files = sorted(p for p in portable.rglob('*') if p.is_file() and p.name != 'SHA256SUMS.json')
manifest = {p.relative_to(portable).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
(portable / 'SHA256SUMS.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
archive = root / 'MIR Cleanup Windows 1.2.1.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as output:
    for path in sorted(portable.rglob('*')):
        if path.is_file():
            output.write(path, path.relative_to(portable.parent))
with zipfile.ZipFile(archive) as check:
    bad = check.testzip()
    if bad:
        raise RuntimeError(f'ZIP verification failed: {bad}')
checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix('.zip.sha256').write_text(f'{checksum}  {archive.name}\n', encoding='ascii')
print(json.dumps({'zip': str(archive), 'bytes': archive.stat().st_size, 'sha256': checksum}, indent=2))
