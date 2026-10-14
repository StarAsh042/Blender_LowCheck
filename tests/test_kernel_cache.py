"""
内核扩展缓存测试

回归：扩展原本从插件目录**内**加载。Windows 上**已加载的 .pyd 无法删除**
（``os.unlink`` 报 ``WinError 5 拒绝访问``），而 CPython **从不卸载扩展模块**
——即使从 ``sys.modules`` 移除也无效（已实测：导入前可删、导入后不可删、
移除引用后仍不可删）。Blender 卸载插件时会 ``shutil.rmtree`` 整个插件目录，
于是用户**永远卸载不掉插件**。

解法是把扩展复制到插件目录**之外**再从副本加载。本测试守住这条不变量。

运行方式:
    blender --background --factory-startup --python-exit-code 1 --python tests/run_tests.py
"""

import os
import sys
import unittest

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)


class TestKernelLoadsOutsideAddon(unittest.TestCase):
    """
    扩展模块必须从插件目录**之外**加载。

    回归：扩展原本从插件目录内加载。Windows 上**已加载的 .pyd 无法删除**
    （``os.unlink`` 报 ``WinError 5 拒绝访问``），而 CPython 从不卸载扩展模块
    ——即使从 ``sys.modules`` 移除也无效（已实测）。Blender 卸载插件时会
    ``shutil.rmtree`` 整个插件目录，于是用户**永远卸载不掉插件**。

    解法是把扩展复制到插件目录之外再从副本加载。本测试守住这条不变量。
    """

    def test_kernel_cache_dir_is_outside_addon(self):
        from Blender_LowCheck import utils  # 延迟导入：需要 bpy

        cache = os.path.abspath(utils._kernel_cache_dir())
        addon = os.path.abspath(PLUGIN_DIR)
        self.assertFalse(
            cache == addon or cache.startswith(addon + os.sep),
            f"内核缓存目录 {cache} 位于插件目录内，会导致插件无法卸载",
        )

    def test_kernel_copy_helper_is_exposed(self):
        """自检：确保上一条测试没有因为函数被重命名而空转"""
        from Blender_LowCheck import utils

        self.assertTrue(callable(getattr(utils, "_ensure_kernel_copy", None)))
        self.assertTrue(callable(getattr(utils, "_kernel_cache_dir", None)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
