"""Online dependency installation plus verified local frontend/public-data preparation."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import venv
import zipfile

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description='能策 Pilot 开源版首次准备')
    parser.add_argument('--archive', type=Path, help='已下载的公开研究数据ZIP')
    parser.add_argument('--download-data', action='store_true')
    parser.add_argument('--skip-install', action='store_true')
    parser.add_argument('--environment', type=Path, default=ROOT/'.venv', help='可选：复用已准备的独立Python环境')
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error('请用 Python 3.12；本交付实际验证 Windows x64 / Python 3.12')
    environment = args.environment.resolve()
    python = environment/('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    if not args.skip_install:
        subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                        '-r', str(ROOT/'product/requirements-lock-windows-py312.txt')], check=True)
        subprocess.run([str(python), '-m', 'pip', 'check'], check=True)
    subprocess.run([str(python), str(ROOT/'tools/prepare_public_data.py'),
                    *(['--archive', str(args.archive)] if args.archive else []),
                    *(['--download'] if args.download_data else [])], check=True)
    manifest = json.loads((ROOT/'distribution/frontend-manifest.json').read_text(encoding='utf-8'))
    archive = ROOT/'distribution'/manifest['archive']
    if hashlib.sha256(archive.read_bytes()).hexdigest() != manifest['sha256']:
        raise ValueError('Prebuilt frontend hash mismatch')
    target = ROOT/'product/frontend/dist'
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            output = (target/member.filename).resolve()
            if target.resolve() not in output.parents:
                raise ValueError('Invalid frontend archive path')
            if output.exists():
                if output.read_bytes() != source.read(member):
                    raise ValueError('Existing frontend differs; rebuild from source or use a fresh directory')
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('xb') as stream:
                stream.write(source.read(member))
    print('准备完成。请用所选环境中的 Python 运行 start.py，浏览器打开 http://127.0.0.1:8003')


if __name__ == '__main__':
    main()
