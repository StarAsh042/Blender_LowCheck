"""
打包脚本：生成可直接在 Blender 中安装的 ZIP。

用法:
    python tools/build_addon.py            # 输出到 <插件目录>/dist/
    python tools/build_addon.py <输出目录>

生成的 ZIP 结构（ZIP 根目录即为插件包名，可直接通过
「编辑 > 首选项 > 插件 > 安装...」安装）:

    Blender_LowCheck/
        __init__.py
        registry.py
        utils.py
        properties.py
        ui.py
        operators/...
        lowcheck_core.pyd      # Rust 内核扩展（由 tools/build_rust.py 产出）
        README.md
        CHANGELOG.md
        LICENSE

注意:
    打包前请先运行 ``python tools/build_rust.py``；若扩展模块缺失，
    插件仍可安装并启用（会自动回退到纯 Python 实现），但会失去 Rust
    内核带来的性能收益。
"""

import os
import sys
import zipfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(SCRIPT_DIR)
ADDON_NAME = os.path.basename(PLUGIN_DIR)

# 随插件分发的文件（目录会递归打包）
INCLUDE_FILES = ("__init__.py", "registry.py", "utils.py", "properties.py",
                 "ui.py", "README.md", "CHANGELOG.md", "LICENSE")
INCLUDE_DIRS = ("operators",)

# 可选：Rust 内核扩展模块（各平台后缀不同，存在才打包）
EXTENSION_SUFFIXES = (".pyd", ".so", ".dylib")
EXTENSION_STEM = "lowcheck_core"

# 打包时需要跳过的内容
EXCLUDE_NAMES = {
    "__pycache__", ".codebuddy", ".workbuddy-ai", "deliverables",
    "dist", "tests", "tools", "src", "target", "Cargo.toml", "Cargo.lock",
    ".git", ".github", ".idea", ".vscode",
}
EXCLUDE_SUFFIXES = (".pyc", ".pyo")


def read_version():
    """从 __init__.py 的 bl_info 中解析版本号"""
    init_path = os.path.join(PLUGIN_DIR, "__init__.py")
    with open(init_path, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped.startswith('"version"'):
                raw = stripped.split(":", 1)[1].strip().rstrip(",").strip("()")
                parts = [int(p.strip()) for p in raw.split(",") if p.strip()]
                return ".".join(str(p) for p in parts)
    return "0.0.0"


def iter_addon_files():
    """产出 (绝对路径, ZIP 内相对路径)"""
    for name in INCLUDE_FILES:
        path = os.path.join(PLUGIN_DIR, name)
        if os.path.isfile(path):
            yield path, f"{ADDON_NAME}/{name}"

    # Rust 内核扩展（可选）
    for suffix in EXTENSION_SUFFIXES:
        path = os.path.join(PLUGIN_DIR, EXTENSION_STEM + suffix)
        if os.path.isfile(path):
            yield path, f"{ADDON_NAME}/{EXTENSION_STEM}{suffix}"

    for dir_name in INCLUDE_DIRS:
        root = os.path.join(PLUGIN_DIR, dir_name)
        if not os.path.isdir(root):
            continue
        for current, sub_dirs, files in os.walk(root):
            sub_dirs[:] = [d for d in sub_dirs if d not in EXCLUDE_NAMES]
            for file_name in sorted(files):
                if file_name in EXCLUDE_NAMES or file_name.endswith(EXCLUDE_SUFFIXES):
                    continue
                abs_path = os.path.join(current, file_name)
                rel_path = os.path.relpath(abs_path, PLUGIN_DIR).replace(os.sep, "/")
                yield abs_path, f"{ADDON_NAME}/{rel_path}"


def build(output_dir=None):
    version = read_version()
    output_dir = output_dir or os.path.join(PLUGIN_DIR, "dist")
    os.makedirs(output_dir, exist_ok=True)

    zip_path = os.path.join(output_dir, f"{ADDON_NAME}-v{version}.zip")
    entries = list(iter_addon_files())
    if not entries:
        raise RuntimeError(f"未找到任何可打包的文件，请检查 {PLUGIN_DIR}")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for abs_path, rel_path in entries:
            archive.write(abs_path, rel_path)

    print(f"[build] 版本: {version}")
    print(f"[build] 输出: {zip_path}")
    print(f"[build] 文件数: {len(entries)}")
    for _abs_path, rel_path in entries:
        print(f"        + {rel_path}")
    return zip_path


def resolve_output_dir(argv):
    """
    解析输出目录。

    使用 ``blender --background --python tools/build_addon.py`` 调用时，
    Blender 自身的参数（``--background``、``--python-exit-code 3`` 等）
    同样会出现在 ``sys.argv`` 中，因此**不能**简单地取第一个位置参数。

    仅识别以下两种显式写法：
      * ``blender ... --python build_addon.py -- <输出目录>``
      * 环境变量 ``LOWCHECK_DIST_DIR``

    否则返回 ``None``，使用默认的 ``<插件目录>/dist``。
    """
    if "--" in argv:
        for arg in argv[argv.index("--") + 1:]:
            if not arg.startswith("-"):
                return arg
    return os.environ.get("LOWCHECK_DIST_DIR") or None


if __name__ == "__main__":
    build(resolve_output_dir(sys.argv))
