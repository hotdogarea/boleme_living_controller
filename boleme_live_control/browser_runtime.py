"""Validate the bundled automation driver before opening a browser session."""

import os
import subprocess
import sys
from pathlib import Path


def prepare_browser_runtime(notice=lambda _text: None):
    try:
        import playwright
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        from playwright._repo_version import version
    except ImportError as exc:
        raise RuntimeError(
            "Playwright浏览器组件缺失，请重新解压完整助手包及_internal目录；"
            "源码运行请使用助手自己的虚拟环境并安装requirements.txt"
        ) from exc

    if getattr(sys, "frozen", False):
        driver = Path(playwright.__file__).parent / "driver"
        os.environ["PLAYWRIGHT_NODEJS_PATH"] = str(driver / "node.exe")
        removed = [key for key in ("NODE_OPTIONS", "NODE_PATH") if os.environ.pop(key, None)]
        if removed:
            notice("已隔离外部Node启动参数，浏览器驱动使用助手自带运行环境")

    node, cli = compute_driver_executable()
    missing = [str(path) for path in (node, cli) if not Path(path).is_file()]
    if missing:
        raise RuntimeError(
            "浏览器驱动文件缺失：" + "；".join(missing)
            + "。请完整解压安装包（包括_internal），并检查安全软件是否隔离了文件；无需单独安装Python"
        )
    try:
        result = subprocess.run(
            [node, cli, "--version"], capture_output=True, encoding="utf-8", errors="replace",
            timeout=10, env=get_driver_env(),
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("浏览器驱动自检超过10秒，请检查安全软件拦截或系统资源占用") from exc
    except OSError as exc:
        raise RuntimeError(f"浏览器驱动无法启动（{type(exc).__name__}）：{exc}；请检查文件权限或隔离记录") from exc
    if result.returncode != 0 or not result.stdout.strip().startswith("Version "):
        detail = (result.stderr or result.stdout).strip()[:400]
        raise RuntimeError(f"浏览器驱动自检失败，退出码={result.returncode}；{detail or '驱动未返回版本信息'}")
    if result.stdout.strip() != f"Version {version}":
        raise RuntimeError(
            f"浏览器组件版本不一致（程序要求{version}，驱动返回{result.stdout.strip()}）；"
            "请将完整新版解压到新目录，不要只替换EXE或混用旧版_internal"
        )
    notice(f"浏览器驱动自检通过（{result.stdout.strip()}）")
