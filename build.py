"""Nuitka 打包脚本。

用法：
    python build.py            # 单文件 exe（推荐分发）
    python build.py --standalone   # 目录模式，启动更快
    python build.py --clean        # 先清理 build/ 再打包

产物：build/TempMailManager.exe（单文件）或 build/run.dist/ 目录（--standalone）
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD_DIR = ROOT / "build"
ENTRY = ROOT / "run.py"
APP_NAME = "TempMailManager"
# 发布版本号：升级版本时同步改这里，并在 github/version/CHANGELOG.md 追加记录
APP_VERSION = "1.1.1"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def ensure_nuitka() -> None:
    try:
        import nuitka  # noqa: F401
        return
    except ImportError:
        pass
    print("[1/3] 安装 Nuitka ...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade",
         "nuitka", "ordered-set", "zstandard"],
        check=True,
    )


def build(onefile: bool = True, clean: bool = False) -> int:
    ensure_nuitka()

    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--remove-output" if clean else "--quiet",
        f"--output-dir={BUILD_DIR}",
        f"--output-filename={APP_NAME}.exe",
        "--windows-console-mode=force",
        # 模板与前端资源必须一起打包
        f"--include-data-dir={ROOT / 'app' / 'templates'}=app/templates",
        f"--include-data-dir={ROOT / 'app' / 'static'}=app/static",
        # 站点点对点调用，无需额外插件
        "--nofollow-import-to=tkinter,unittest,pydoc,test",
        "--company-name=TempMail",
        "--product-name=TempMail Manager",
        "--file-version={v}".format(v=APP_VERSION),
        "--product-version={v}".format(v=APP_VERSION),
        "--file-description=OneTimeEmail temp mail manager",
    ]
    if onefile:
        # 固定解包目录：避免 %TEMP% 下残留大量 onefile_* 目录（强杀进程时解包不完整会卡启动）
        cmd.append("--onefile")
        cmd.append(f"--onefile-tempdir-spec={{TEMP}}/{APP_NAME}-{APP_VERSION}")
    cmd.append(str(ENTRY))

    print("[2/3] 开始编译（首次编译较慢，可能需要几分钟）...")
    print("    " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print("[3/3] 编译失败，请检查上方日志。")
        return result.returncode

    print("[3/3] 编译完成。")
    if onefile:
        print(f"    可执行文件：{BUILD_DIR / (APP_NAME + '.exe')}")
    else:
        print(f"    可执行文件：{BUILD_DIR / 'run.dist' / (APP_NAME + '.exe')}")
    print("    运行后数据保存在 exe 同级的 data/ 目录。")
    return 0


if __name__ == "__main__":
    args = set(sys.argv[1:])
    sys.exit(build(onefile="--standalone" not in args, clean="--clean" in args))
