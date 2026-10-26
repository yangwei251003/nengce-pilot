"""Start the local, prebuilt V3.1 workbench. Does not install packages or open ports remotely."""
from pathlib import Path
import argparse
import subprocess
import sys

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description='能策 Pilot V3.1 本机工作台')
parser.add_argument('--port', type=int, default=8003)
args = parser.parse_args()
if not 1024 <= args.port <= 65535:
    parser.error('端口必须为1024—65535')
if not (root/'product/frontend/dist/index.html').is_file():
    parser.error('缺少编译界面；请按README在product/frontend执行锁定依赖构建')
print(f'能策 Pilot V3.1： http://127.0.0.1:{args.port}', flush=True)
print('按 Ctrl+C 结束本次服务。核心计算无需网络；在线助手为单独可选功能。', flush=True)
try:
    subprocess.run([sys.executable, '-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', str(args.port)],
                   cwd=root/'product', check=True)
except KeyboardInterrupt:
    pass
