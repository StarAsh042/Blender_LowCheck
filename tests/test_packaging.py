"""
打包完整性测试

回归：新增 ``i18n.py`` 后漏改 :data:`tools.build_addon.INCLUDE_FILES`，打包出的
ZIP 缺少该模块，插件**无法启用**——而 Blender 只会静默把插件弹回未启用状态，
错误信息还误导性地提示「circular import」，极难定位。

本测试把「白名单必须覆盖所有根级 Python 模块」变成一条断言，让这类遗漏在测试
阶段就暴露，而不是等用户装不上。

运行方式:
    blender --background --factory-startup --python-exit-code 1 --python tests/run_tests.py
"""

import importlib.util
import os
import sys
import unittest

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

BUILD_SCRIPT = os.path.join(PLUGIN_DIR, "tools", "build_addon.py")


def _load_build_addon():
    """
    按路径加载打包脚本。

    ``tools`` 不是包（无 ``__init__.py``），无法用 ``import`` 直接取到，
    因此用 ``importlib`` 按文件路径加载。脚本的构建逻辑在
    ``if __name__ == "__main__"`` 之下，加载时不会触发打包。
    """
    spec = importlib.util.spec_from_file_location("lowpoly_build_addon", BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _root_modules():
    """插件目录下所有根级 Python 模块文件名"""
    return {
        name for name in os.listdir(PLUGIN_DIR)
        if name.endswith(".py") and os.path.isfile(os.path.join(PLUGIN_DIR, name))
    }


class TestPackagingIntegrity(unittest.TestCase):
    """打包白名单必须覆盖所有根级 Python 模块。"""

    def test_root_modules_are_enumerable(self):
        """自检：避免下一条测试因目录读取失败而空转通过"""
        self.assertGreaterEqual(len(_root_modules()), 6)
        self.assertIn("i18n.py", _root_modules())

    def test_every_root_module_is_packaged(self):
        included = set(_load_build_addon().INCLUDE_FILES)
        missing = sorted(_root_modules() - included)
        self.assertEqual(
            missing, [],
            "以下根级模块未加入 INCLUDE_FILES，打包后会缺失并导致插件无法启用："
            f"{missing}",
        )

    def test_included_files_exist(self):
        """白名单里的文件必须真实存在，避免写了名字却没这个文件"""
        absent = [
            name for name in _load_build_addon().INCLUDE_FILES
            if not os.path.isfile(os.path.join(PLUGIN_DIR, name))
        ]
        self.assertEqual(absent, [], f"以下白名单文件不存在：{absent}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
