"""config.json 读写与输出目录定位"""

import json
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_FILE = PROJECT_ROOT / "config.json"
CONFIG_EXAMPLE = PROJECT_ROOT / "config.example.json"


def load_config() -> dict:
    # 首次运行：从示例配置生成 config.json
    if not CONFIG_FILE.exists() and CONFIG_EXAMPLE.exists():
        shutil.copy2(CONFIG_EXAMPLE, CONFIG_FILE)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    """写回配置，写前备份上一版"""
    if CONFIG_FILE.exists():
        shutil.copy2(CONFIG_FILE, CONFIG_FILE.with_suffix(".json.bak"))
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def output_root() -> Path:
    """下载输出根目录（与 DouyinDownloader 保持一致的定位方式）"""
    config = load_config()
    download_dir = config.get("douyin", {}).get("download_dir", "output")
    return (PROJECT_ROOT / download_dir).resolve()
