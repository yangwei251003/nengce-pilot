"""Restore only the hash-locked public research archive; never copy private imports."""
from pathlib import Path
import argparse
import hashlib
import json
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def destination(relative):
    path = (ROOT / relative).resolve()
    if ROOT not in path.parents or not relative.startswith(('data/reference/', 'data/v3/')) or 'private-imports' in path.parts:
        raise ValueError('Archive member outside the public-data boundary')
    return path


def prepare(archive=None, download=False, fetch_rsf_reference=False):
    manifest = json.loads((ROOT/'data/archive-manifest.json').read_text(encoding='utf-8'))
    archive = Path(archive or ROOT/'data'/manifest['archive']).resolve()
    if not archive.is_file():
        if not download:
            raise SystemExit('缺少公开研究数据包。请下载 README 的 Release 附件，或显式使用 --download。')
        archive.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(manifest['downloadUrl'], archive)
    if digest(archive) != manifest['archiveSha256']:
        raise ValueError('Public archive SHA256 mismatch; no files extracted')
    expected = {item['path']: item for item in manifest['files']}
    with zipfile.ZipFile(archive) as source:
        if set(source.namelist()) != set(expected):
            raise ValueError('Public archive member list mismatch')
        for name, info in expected.items():
            output = destination(name)
            if output.exists():
                if digest(output) != info['sha256']:
                    raise ValueError(f'Existing data differs; refusing overwrite: {name}')
                continue
            raw = source.read(name)
            if len(raw) != info['bytes'] or hashlib.sha256(raw).hexdigest() != info['sha256']:
                raise ValueError(f'Archive member hash mismatch: {name}')
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('xb') as target:
                target.write(raw)
    references = manifest.get('excludedReferenceDocuments', [])
    if fetch_rsf_reference:
        for record in references:
            output = destination(record['path'])
            if not output.exists():
                raw = urllib.request.urlopen(record['url'], timeout=60).read()
                if hashlib.sha256(raw).hexdigest() != record['sha256']:
                    raise ValueError('Official reference bytes changed; refusing old-data identity')
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open('xb') as target:
                    target.write(raw)
            if digest(output) != record['sha256']:
                raise ValueError('Existing RSF reference SHA256 mismatch')
    print(f'已校验并准备 {len(expected)} 个公开文件；未导入私人数据。')
    if any(not destination(item['path']).exists() for item in references):
        print('RSF参考PDF未捆绑：该案例仍需按README自行取得官方文献并校验；UCI默认案例可运行。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='准备哈希锁定的公开研究数据')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--download', action='store_true', help='显式下载 GitHub Release 数据附件')
    parser.add_argument('--fetch-rsf-reference', action='store_true', help='从官方现取未再分发的 RSF 文献，仅保存本地')
    options = parser.parse_args()
    prepare(options.archive, options.download, options.fetch_rsf_reference)
