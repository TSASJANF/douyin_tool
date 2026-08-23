#!/usr/bin/env python3
"""
WebUI 启动入口

用法:
    python web.py                # 生产模式（托管 webui/dist 构建产物）
    python web.py --port 9000    # 指定端口
    python web.py --reload       # 开发模式（配合 cd webui && npm run dev）
"""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="抖音视频智能解析工具 WebUI")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    parser.add_argument("--reload", action="store_true", help="开发模式：代码改动自动重载")
    args = parser.parse_args()

    uvicorn.run(
        "server.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
