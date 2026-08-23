"""WebUI 后端服务包"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中（无论从哪个工作目录启动）
_ROOT = str(Path(__file__).parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
