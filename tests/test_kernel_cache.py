"""
内核扩展缓存测试

回归 1：扩展原本从插件目录**内**加载。Windows 上**已加载的 .pyd 无法删除**
（``os.unlink`` 报 ``WinError 5 拒绝访问``），而 CPython **从不卸载扩展模块**
——即使从 ``sys.modules`` 移除也无效（已实测：导入前可删、导入后不可删、
移除引用后仍不可删）。Blender 卸载插件时会 ``shutil.rmtree`` 整个插件目录，
于是用户**永远卸载不掉插件**。

回归 2：内核改为从缓存副本加载后，副本的「新鲜度」判断与「卸载后清理」
又各自引入一个缺陷——前者用 mtime 判断导致升级插件后仍加载旧内核，后者
缺失导致缓存目录残留。两者一并守住。

运行方式:
    blender --background --factory-startup --python-exit-code 1 --python tests/run_tests.py
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

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


#: ZIP 内扩展模块记录的时间戳（构建时间）。用它复现「升级后 mtime 反而更早」。
_BUILD_TIME = time.mktime((2026, 10, 14, 9, 9, 18, 0, 0, -1))


class TestKernelCopyStaysFresh(unittest.TestCase):
    """
    升级插件后必须加载**新**内核。

    回归：``_ensure_kernel_copy`` 原以 mtime 判断是否需要重新复制，而 ZIP 内的
    ``.pyd`` 时间戳是**构建时间**（早于用户机器上的「现在」），缓存副本的 mtime
    却是首次复制时的当前时间。于是升级后 ``源 > 缓存`` 恒为 False、缓存永不
    更新——用户装上新版本，跑的仍是旧内核。实测：内容已变，缓存哈希不变。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kernel_copy_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.src_dir = os.path.join(self.tmp, "addon")
        self.cache_dir = os.path.join(self.tmp, "cache")
        os.makedirs(self.src_dir)
        # 真实 _kernel_cache_dir() 会以 create=True 建目录；这里被 mock 成
        # 直接返回路径，所以要自己建好，否则 copy2 会因目标目录缺失而失败。
        os.makedirs(self.cache_dir)
        self.src = os.path.join(self.src_dir, "lowcheck_core.pyd")

    def _write(self, payload, mtime):
        """写入扩展模块并指定 mtime"""
        with open(self.src, "wb") as fh:
            fh.write(payload)
        os.utime(self.src, (mtime, mtime))

    def _ensure(self, utils):
        """在隔离的缓存目录下调用 _ensure_kernel_copy"""
        with mock.patch.object(utils, "_kernel_cache_dir",
                               return_value=self.cache_dir):
            return utils._ensure_kernel_copy(self.src)

    def test_cache_updates_when_content_changes(self):
        """内容变了就必须重新复制——即便新文件的 mtime 更早"""
        from Blender_LowCheck import utils

        self._write(b"OLD-KERNEL-PAYLOAD", _BUILD_TIME)
        cache = self._ensure(utils)
        self.assertTrue(os.path.isfile(cache), "首次复制未产出缓存文件")

        # 模拟升级：内容已变，mtime 仍是构建时间（甚至更早）
        self._write(b"NEW-KERNEL-PAYLOAD", _BUILD_TIME - 86400)
        self._ensure(utils)

        with open(cache, "rb") as fh:
            self.assertEqual(
                fh.read(), b"NEW-KERNEL-PAYLOAD",
                "缓存未随内容更新：升级插件后仍会加载旧内核",
            )

    def test_cache_not_rewritten_when_content_identical(self):
        """内容相同就不该重复写盘（避免每次启动都做无谓 IO）"""
        from Blender_LowCheck import utils

        self._write(b"SAME-PAYLOAD", _BUILD_TIME)
        cache = self._ensure(utils)
        before = os.stat(cache).st_mtime_ns

        time.sleep(0.01)
        self._ensure(utils)

        self.assertEqual(os.stat(cache).st_mtime_ns, before,
                         "内容未变时不应重复复制")


class TestKernelCacheCleanup(unittest.TestCase):
    """
    插件注销时尽力清理缓存目录。

    .. note::
       内核已被加载时文件被进程锁定、删不掉，属 Windows 硬限制。这里只验证
       「可删时应删净」与「不可删时不抛异常、不误建目录」两条。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kernel_cleanup_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_cleanup_does_not_create_missing_dir(self):
        """清理缓存不能「为了删除而先把目录建出来」"""
        from Blender_LowCheck import utils

        missing = os.path.join(self.tmp, "never_created")
        with mock.patch.object(utils, "_kernel_cache_dir",
                               return_value=missing) as patched:
            utils.cleanup_kernel_cache()  # 不应抛异常

        # 关键：必须显式传 create=False，否则会「为删除而建目录」
        patched.assert_called_once_with(create=False)
        self.assertFalse(os.path.isdir(missing),
                         "缓存目录本不存在，清理后却出现了")

    def test_cleanup_removes_files_and_dir(self):
        """可删除时应连目录一起清掉"""
        from Blender_LowCheck import utils

        cache = os.path.join(self.tmp, "cache_with_files")
        os.makedirs(cache)
        with open(os.path.join(cache, "lowcheck_core.pyd"), "wb") as fh:
            fh.write(b"payload")

        with mock.patch.object(utils, "_kernel_cache_dir", return_value=cache):
            utils.cleanup_kernel_cache()

        self.assertFalse(os.path.isdir(cache), "可删除时缓存目录应被清掉")


if __name__ == "__main__":
    unittest.main(verbosity=2)
