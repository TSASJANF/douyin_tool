#!/usr/bin/env python3
"""
服务管理脚本 —— 启动/停止/重启/状态查询

用法:
    python ctl.py start  [--host 127.0.0.1] [--port 8000]   启动（后台运行，日志写入 logs/webui.log）
    python ctl.py stop                                       停止
    python ctl.py restart [--host ...] [--port ...]          重启
    python ctl.py status                                     查询状态（退出码 0=运行中, 3=未运行）

特性:
    - PID 文件记录托管进程，停止时校验进程映像名，避免 PID 复用误杀
    - 启动前检测端口占用；健康检查确认服务真正就绪后才报告成功
    - PID 文件丢失时可按端口反查监听进程（netstat/lsof），仍校验为 python 进程才终止
    - 幂等：重复启动/停止不会报错，只提示当前状态

Windows 下可直接使用 start.bat / stop.bat / restart.bat。
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB_PY = ROOT / "web.py"
PID_FILE = ROOT / ".server.pid"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "webui.log"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
STARTUP_TIMEOUT = 30      # 启动后等待就绪的秒数
SHUTDOWN_TIMEOUT = 8      # 优雅停止等待秒数，超时强杀

IS_WINDOWS = os.name == "nt"


# ---------------- 状态文件 ----------------

def read_pid_info() -> dict | None:
    try:
        return json.loads(PID_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_pid_info(info: dict):
    PID_FILE.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_pid_info():
    PID_FILE.unlink(missing_ok=True)


# ---------------- 探测工具 ----------------

def health_ok(port: int, host: str = "127.0.0.1", timeout: float = 1.5) -> bool:
    """健康检查：GET /api/health"""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if IS_WINDOWS:
        import ctypes
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if k32.GetExitCodeProcess(h, ctypes.byref(exit_code)):
                return exit_code.value == STILL_ACTIVE
            return True
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def run_capture(cmd: list, timeout: float = 15) -> str:
    """运行命令并解码输出。Windows 中文系统的 netstat/tasklist 输出为 GBK，
    需按编码回退链解码，避免 UnicodeDecodeError。"""
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    for enc in ("utf-8", "gbk", "mbcs"):
        try:
            return r.stdout.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return r.stdout.decode("utf-8", errors="replace")


def pid_image_name(pid: int) -> str | None:
    """进程映像名（如 python.exe）。PID 不存在返回 None。"""
    if IS_WINDOWS:
        out = run_capture(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and parts[1] == str(pid):
                return parts[0].lower()
        return None
    try:
        comm = Path(f"/proc/{pid}/comm")
        if comm.exists():
            return comm.read_text().strip().lower()
    except OSError:
        pass
    out = run_capture(["ps", "-p", str(pid), "-o", "comm="]).strip().lower()
    return out or None


def is_python_process(pid: int) -> bool:
    """安全校验：目标必须是 python 进程，防止 PID 复用后误杀其他程序"""
    name = pid_image_name(pid)
    return bool(name) and (name.startswith("python") or name in ("py.exe", "py"))


def find_listener_pids(port: int) -> set[int]:
    """按端口反查监听进程 PID（用于 PID 文件丢失时的兜底）"""
    pids: set[int] = set()
    if IS_WINDOWS:
        out = run_capture(["netstat", "-ano", "-p", "tcp"])
        for line in out.splitlines():
            fields = line.split()
            # TCP  0.0.0.0:8000  0.0.0.0:0  LISTENING  1234
            if (len(fields) >= 5 and fields[3] == "LISTENING"
                    and fields[1].rsplit(":", 1)[-1] == str(port)):
                pids.add(int(fields[4]))
    else:
        try:
            out = run_capture(["lsof", "-t", "-i", f":{port}"])
            pids.update(int(x) for x in out.split())
        except (OSError, ValueError):
            pass
    return pids


def port_in_use(port: int) -> bool:
    """端口是否被监听（不区分进程）"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ---------------- 命令实现 ----------------

def resolve_managed_pid() -> tuple[int | None, int]:
    """返回 (托管PID或None, 端口)"""
    info = read_pid_info()
    if not info:
        return None, DEFAULT_PORT
    pid = info.get("pid")
    port = int(info.get("port", DEFAULT_PORT))
    if pid and is_pid_alive(pid):
        return pid, port
    # 进程已死但文件残留 → 清理
    clear_pid_info()
    return None, port


def cmd_start(host: str, port: int) -> int:
    pid, _ = resolve_managed_pid()

    if health_ok(port):
        if pid:
            print(f"服务已在运行（PID {pid}），无需重复启动")
            print(f"    地址: http://{host}:{port}   日志: {LOG_FILE}")
            return 0
        print(f"端口 {port} 上已有服务在响应（非本脚本托管），地址: http://{host}:{port}")
        return 0

    if port_in_use(port):
        listeners = find_listener_pids(port)
        detail = f"（PID: {', '.join(map(str, sorted(listeners)))} ）" if listeners else ""
        print(f"错误: 端口 {port} 已被其他程序占用{detail}，请换端口 (--port) 或先停止占用进程")
        return 1

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [sys.executable, str(WEB_PY), "--host", host, "--port", str(port)]
    kwargs: dict = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True

    with open(LOG_FILE, "ab") as log:
        log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 =====\n".encode("utf-8"))
        log.flush()
        proc = subprocess.Popen(
            cmd, cwd=str(ROOT), stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, **kwargs,
        )

    write_pid_info({"pid": proc.pid, "port": port, "host": host,
                    "started_at": time.strftime("%Y-%m-%d %H:%M:%S")})

    # 等待健康检查通过，确认真正就绪
    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if health_ok(port):
            print(f"服务已启动: http://{host}:{port}   (PID {proc.pid})")
            print(f"    日志: {LOG_FILE}    停止: python ctl.py stop")
            return 0
        if proc.poll() is not None:
            break  # 进程已退出
        time.sleep(0.3)

    # 启动失败：打印日志尾部辅助排查
    clear_pid_info()
    print(f"错误: 服务启动失败（退出码 {proc.poll()}），日志尾部:")
    try:
        tail = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
        print("  " + "\n  ".join(tail))
    except OSError:
        pass
    return 1


def _kill_pid_tree(pid: int) -> bool:
    """终止进程树。先温和后强杀，返回是否成功。"""
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T"],
                       capture_output=True, timeout=15)
        deadline = time.time() + SHUTDOWN_TIMEOUT
        while time.time() < deadline and is_pid_alive(pid):
            time.sleep(0.3)
        if is_pid_alive(pid):
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=15)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        deadline = time.time() + SHUTDOWN_TIMEOUT
        while time.time() < deadline and is_pid_alive(pid):
            time.sleep(0.3)
        if is_pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    time.sleep(0.5)
    return not is_pid_alive(pid)


def cmd_stop() -> int:
    pid, port = resolve_managed_pid()

    # 托管 PID 有效 → 直接停
    if pid:
        if not is_python_process(pid):
            print(f"错误: PID {pid} 已不是 python 进程（可能被系统复用），拒绝终止，请手动处理")
            return 1
        ok = _kill_pid_tree(pid)
        clear_pid_info()
        if ok:
            print(f"服务已停止 (PID {pid})")
            return 0
        print(f"错误: 无法终止进程 PID {pid}，请手动处理（任务管理器）")
        return 1

    # PID 文件缺失 → 按端口反查兜底
    if port_in_use(port):
        listeners = find_listener_pids(port)
        targets = [p for p in listeners if is_python_process(p)]
        if not targets:
            print(f"端口 {port} 被非 python 进程占用（PID: {sorted(listeners) or '未知'}），未自动终止")
            return 1
        for p in targets:
            if not _kill_pid_tree(p):
                print(f"错误: 无法终止进程 PID {p}，请手动处理（任务管理器）")
                return 1
        clear_pid_info()
        print(f"服务已停止 (按端口 {port} 反查, PID {', '.join(map(str, targets))})")
        return 0

    print("服务未在运行")
    return 0


def cmd_status() -> int:
    pid, port = resolve_managed_pid()
    info = read_pid_info()

    if health_ok(port):
        who = f"PID {pid}（本脚本托管, 启动于 {info['started_at']}）" if pid else "非本脚本托管"
        print(f"运行中  http://127.0.0.1:{port}   {who}")
        return 0
    print("未运行")
    return 3


def main() -> int:
    parser = argparse.ArgumentParser(description="抖音视频智能解析工具 - 服务管理")
    sub = parser.add_subparsers(dest="command", required=True)
    p_start = sub.add_parser("start", help="启动服务（后台）")
    p_start.add_argument("--host", default=DEFAULT_HOST)
    p_start.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_restart = sub.add_parser("restart", help="重启服务")
    p_restart.add_argument("--host", default=DEFAULT_HOST)
    p_restart.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub.add_parser("stop", help="停止服务")
    sub.add_parser("status", help="查询状态")

    args = parser.parse_args()

    if args.command == "start":
        return cmd_start(args.host, args.port)
    if args.command == "restart":
        # 沿用原端口参数（若未显式指定且存在托管记录）
        _, old_port = resolve_managed_pid()
        port = args.port if args.port != DEFAULT_PORT or not read_pid_info() else old_port
        cmd_stop()
        time.sleep(0.5)
        return cmd_start(args.host, port)
    if args.command == "stop":
        return cmd_stop()
    if args.command == "status":
        return cmd_status()
    return 1


if __name__ == "__main__":
    sys.exit(main())
