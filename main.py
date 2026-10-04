#!/usr/bin/env python3
"""
抖音视频智能解析工具 - 命令行主程序
下载 + MiMo 解析（视频直链推送模式，与 WebUI 共用 server.pipeline 流程）
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from server.pipeline import run_pipeline, PipelineError

CONFIG_FILE = Path(__file__).parent / "config.json"
OUTPUT_DIR = Path(__file__).parent / "output"


def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def check_config() -> bool:
    config = load_config()
    mimo = config.get("mimo_api", {})
    if not mimo.get("api_key"):
        print("错误: 请先配置MiMo API Key")
        print(f"配置文件: {CONFIG_FILE}")
        return False

    return True


def cli_event_handler(event_type: str, data: dict):
    """将 pipeline 事件转为命令行输出（保持原有格式）"""
    if event_type == "stage":
        print("\n" + "=" * 50)
        print(f"步骤 {data['index']}/3: {data['label']}")
        print("=" * 50)
    elif event_type == "log":
        print(data.get("text", ""))
    elif event_type == "download_progress":
        # CLI 下下载器自身已打印进度，这里无需处理
        pass


async def main():
    print("=" * 60)
    print("抖音视频智能解析工具")
    print("=" * 60)

    if not check_config():
        print("\n请先编辑配置文件后重新运行。")
        print(f"配置文件路径: {CONFIG_FILE}")
        return

    config = load_config()
    print("使用直链模式解析视频")

    while True:
        try:
            print("\n" + "-" * 40)
            url_text = input("请输入抖音/视频号链接或口令（输入 'q' 退出）: ").strip()

            if url_text.lower() in ('q', 'quit', 'exit'):
                print("再见！")
                break

            if not url_text:
                print("链接不能为空，请重新输入。")
                continue

            print("\n正在处理...")

            try:
                result = await run_pipeline(url_text, config, cli_event_handler)
            except PipelineError as e:
                print(f"\n处理失败: {e}")
                continue

            content = result["content"]

            if content:
                print("\n解析结果预览:")
                print("-" * 40)
                preview = content[:500] + "..." if len(content) > 500 else content
                print(preview)
                print("-" * 40)
                print(f"输出目录: {result['output_dir']}")
                print("保存的文件:")
                for file in result["files"]:
                    print(f"  - {file}")

        except KeyboardInterrupt:
            print("\n\n程序被用户中断。")
            break
        except Exception as e:
            print(f"\n发生错误: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    asyncio.run(main())
