"""
测试运行器

在 Blender 中运行全部测试（把 <Blender 可执行文件> 换成实际路径）:
    "<Blender 可执行文件>" ^
        --background --factory-startup --python-exit-code 1 ^
        --python tests/run_tests.py

退出码: 任何测试失败/出错时返回 1（配合 --python-exit-code 1 使用）。
"""

import os
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(TESTS_DIR)
PARENT_DIR = os.path.dirname(PLUGIN_DIR)

for path in (TESTS_DIR, PARENT_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

# 需要特殊环境（BLENDER_USER_SCRIPTS + 独立进程）的模块，由
# tools/run_install_test.ps1 单独驱动，不参与本运行器的批量发现
EXCLUDED_MODULES = {"test_addon_install"}


def _filter_suite(suite):
    """递归剔除被排除的测试模块"""
    filtered = unittest.TestSuite()
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            sub = _filter_suite(item)
            if sub.countTestCases():
                filtered.addTest(sub)
        elif type(item).__module__ not in EXCLUDED_MODULES:
            filtered.addTest(item)
    return filtered


def main():
    print("=" * 72)
    print(" 低模质量检查插件 — 测试套件")
    print(f" Blender : {'.'.join(str(v) for v in __import__('bpy').app.version)}")
    print(f" Python  : {sys.version.split()[0]}")
    print(f" 插件目录: {PLUGIN_DIR}")
    print(f" 已跳过  : {', '.join(sorted(EXCLUDED_MODULES))} (见 tools/run_install_test.ps1)")
    print("=" * 72)

    loader = unittest.TestLoader()
    suite = _filter_suite(
        loader.discover(start_dir=TESTS_DIR, pattern="test_*.py",
                        top_level_dir=TESTS_DIR)
    )

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    print("=" * 72)
    print(f" 共运行 {result.testsRun} 个测试 | "
          f"失败 {len(result.failures)} | 错误 {len(result.errors)} | "
          f"跳过 {len(result.skipped)}")
    print("=" * 72)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    exit_code = main()
    # 使用 os._exit 之外的常规退出：Blender 会依据 --python-exit-code 处理 SystemExit
    sys.exit(exit_code)
