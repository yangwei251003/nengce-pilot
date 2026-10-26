"""Archive full license texts from locked installed dependencies, never binaries/caches."""
from pathlib import Path
from importlib import metadata
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r'^(?:licen[cs]e|copying|notice)(?:$|[._-])', re.I)


def decode(raw):
    try:
        return raw.decode('utf-8-sig')
    except UnicodeError:
        return raw.decode('latin-1')


def write(group, packages):
    folder = ROOT/'licenses'/group
    folder.mkdir(parents=True, exist_ok=True)
    lines = [f'# {group} dependency notices', '', 'Installed locked package notices; each dependency retains its original license.', '']
    missing = []
    inventory = []
    for name, version, notices in packages:
        lines += [f'## {name} {version}', '']
        if not notices:
            missing.append(name)
        for filename, text in notices:
            lines += [f'### {filename}', '', '```text', text.strip(), '```', '']
        inventory.append({'package':name,'version':version,'notices':[f for f,_ in notices]})
    (folder/'THIRD_PARTY_NOTICES.md').write_text('\n'.join(lines), encoding='utf-8')
    (folder/'inventory.json').write_text(json.dumps(inventory, indent=2)+'\n', encoding='utf-8')
    if missing:
        raise RuntimeError(f'Unresolved {group} package notices: {missing}')
    return len(inventory)


def main():
    packages = []
    for line in (ROOT/'product/requirements-lock-windows-py312.txt').read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        name, expected = line.split('==')
        dist = metadata.distribution(name)
        if dist.version != expected:
            raise ValueError(f'Installed dependency mismatch: {name}')
        notices, seen = [], set()
        for relative in dist.files or []:
            if not NAME.match(relative.name):
                continue
            file = dist.locate_file(relative)
            if not file.is_file() or file.stat().st_size > 4_000_000:
                continue
            text = decode(file.read_bytes())
            digest = hashlib.sha256(text.encode()).hexdigest()
            if digest not in seen:
                seen.add(digest)
                notices.append((str(relative).replace('\\','/'), text))
        packages.append((dist.metadata['Name'], dist.version, notices))
    python_count = write('python', packages)
    frontend = ROOT/'product/frontend'
    lock = json.loads((frontend/'package-lock.json').read_text())
    packages = []
    for relative, item in lock['packages'].items():
        if not relative or item.get('dev') or item.get('optional'):
            continue
        folder = frontend/relative
        manifest = json.loads((folder/'package.json').read_text())
        notices = [(p.name, decode(p.read_bytes())) for p in folder.iterdir() if p.is_file() and NAME.match(p.name)]
        packages.append((manifest['name'], manifest['version'], notices))
    javascript_count = write('javascript', packages)
    print(json.dumps({'pythonPackages':python_count,'javascriptPackages':javascript_count,'missingNotices':0}))


if __name__ == '__main__':
    main()
