"""
构建 Rust 内核，并把产物放置为可被 Blender 导入的扩展模块。

用法:
    python tools/build_rust.py              # 输出到 <插件目录>/
    python tools/build_rust.py <输出目录>

说明:
    Blender 内置的是 CPython，扩展模块必须与其 ABI 兼容。本 crate 全程使用
    PyO3 的 ``abi3-py38``（CPython 稳定 ABI），因此**不需要**针对 Blender
    内置的具体小版本重新编译。

    Windows 上 abi3 扩展依赖 ``python3.dll``（稳定 ABI 转发层）。该 DLL 位于
    Blender 安装根目录，Blender 启动时已在搜索路径中；若在独立 Python 里
    测试，需要把 Blender 根目录加入 ``PATH``。
"""

import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(SCRIPT_DIR)
CRATE_NAME = "lowcheck_core"

if os.name == "nt":
    BUILT_NAME = f"{CRATE_NAME}.dll"
    MODULE_SUFFIX = ".pyd"
elif sys.platform == "darwin":
    BUILT_NAME = f"lib{CRATE_NAME}.dylib"
    MODULE_SUFFIX = ".so"
else:
    BUILT_NAME = f"lib{CRATE_NAME}.so"
    MODULE_SUFFIX = ".so"


def build(output_dir=None):
    """
    执行 ``cargo build --release`` 并把产物复制为扩展模块。

    Args:
        output_dir: 输出目录；缺省为插件根目录

    Returns:
        str: 生成的扩展模块绝对路径
    """
    output_dir = output_dir or PLUGIN_DIR
    subprocess.run(["cargo", "build", "--release"], cwd=PLUGIN_DIR, check=True)

    built = os.path.join(PLUGIN_DIR, "target", "release", BUILT_NAME)
    if not os.path.isfile(built):
        raise RuntimeError(f"未找到构建产物: {built}")

    os.makedirs(output_dir, exist_ok=True)
    dest = os.path.join(output_dir, CRATE_NAME + MODULE_SUFFIX)
    shutil.copy2(built, dest)
    print(f"[build_rust] 源文件: {built}")
    print(f"[build_rust] 输出  : {dest}")
    return dest


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else None)
