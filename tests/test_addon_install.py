"""
真实安装流程验证（addon_utils）

本脚本模拟用户把插件目录放进 Blender 用户脚本目录后，通过
「编辑 > 首选项 > 插件」启用/停用的全过程。

前置条件:
    环境变量 BLENDER_USER_SCRIPTS 指向一个包含
    ``addons/Blender_LowCheck`` 的临时脚本目录。
    由 ``tools/run_install_test.ps1`` 自动准备。

运行方式:
    blender --background --factory-startup --python-exit-code 1 \
        --python tests/test_addon_install.py
"""

import os
import sys
import unittest

import addon_utils  # noqa: E402  (Blender 内置模块)
import bpy  # noqa: E402

ADDON_NAME = "Blender_LowCheck"


class TestAddonInstall(unittest.TestCase):
    """验证「安装 → 启用 → 使用 → 停用」全流程"""

    @classmethod
    def setUpClass(cls):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def test_01_addon_is_discoverable(self):
        """
        插件目录能被 Blender 的插件扫描器发现

        说明: Blender 的扫描器只解析 ``bl_info`` 而不会执行整个模块
              （因此这里拿到的模块对象只有 bl_info，register/unregister
              需要等 enable 时真正导入后才存在）。
        """
        modules = {module.__name__: module for module in addon_utils.modules(refresh=True)}
        self.assertIn(
            ADDON_NAME, modules,
            f"未在脚本目录中发现插件 {ADDON_NAME}；"
            f"请确认 BLENDER_USER_SCRIPTS={os.environ.get('BLENDER_USER_SCRIPTS')!r}",
        )

        module = modules[ADDON_NAME]
        self.assertTrue(hasattr(module, "bl_info"), "缺少 bl_info")

        info = module.bl_info
        self.assertEqual(info.get("category"), "Mesh")
        self.assertEqual(
            tuple(info.get("version", (0,))), (1, 0, 0),
            "bl_info 版本必须与 README/CHANGELOG 声明的 1.0.0 一致",
        )

        # 确认扫描到的正是本次测试部署的副本（而不是别处的同名插件）
        addon_dir = os.path.dirname(os.path.abspath(module.__file__))
        expected_dir = os.path.join(
            os.environ.get("BLENDER_USER_SCRIPTS", ""), "addons", ADDON_NAME
        )
        self.assertEqual(os.path.normcase(addon_dir), os.path.normcase(expected_dir))

    def test_02_default_state_is_disabled(self):
        """启动时插件默认处于未启用状态"""
        loaded_default, loaded_state = addon_utils.check(ADDON_NAME)
        self.assertFalse(loaded_state, "插件不应在 factory-startup 下自动启用")
        self.assertFalse(hasattr(bpy.types, 'LOWPOLY_OT_run_all_checks'))

    def test_03_enable_addon(self):
        """启用插件后：属性组 / 操作符 / 面板全部就绪"""
        addon_utils.enable(ADDON_NAME, default_set=False, persistent=False)

        self.assertTrue(
            hasattr(bpy.types, 'LOWPOLY_OT_run_all_checks'),
            "启用后操作符未注册（可能 register() 抛出了异常，请查看上方日志）",
        )
        self.assertTrue(hasattr(bpy.types, 'LOWPOLY_PT_quality_panel'))
        self.assertTrue(hasattr(bpy.types.Scene, "lowpoly"))

        # 启用后模块才被真正导入，此时应包含完整的插件接口
        module = sys.modules.get(ADDON_NAME)
        self.assertIsNotNone(module, "插件模块未被导入到 sys.modules")
        for attr in ("register", "unregister", "reload_modules", "bl_info"):
            self.assertTrue(hasattr(module, attr), f"插件模块缺少 {attr}")

        _, loaded_state = addon_utils.check(ADDON_NAME)
        self.assertTrue(loaded_state, "addon_utils 认为插件未处于启用状态")

    def test_04_use_addon(self):
        """启用后可以正常执行检测（端到端可用）"""
        mesh = bpy.data.meshes.new("InstallTestMesh")
        mesh.from_pydata(
            [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (1.5, 1.5, 0)],
            [],
            [(0, 1, 2, 3), (1, 4, 2)],
        )
        mesh.update()
        obj = bpy.data.objects.new("InstallTestMesh", mesh)
        bpy.context.scene.collection.objects.link(obj)

        try:
            self.assertEqual(bpy.ops.lowpoly.run_all_checks(), {'FINISHED'})
            props = bpy.context.scene.lowpoly
            self.assertEqual(props.ngon_count, 0)
            self.assertGreaterEqual(props.loose_vert_count, 0)

            self.assertEqual(bpy.ops.lowpoly.reset_all_params(), {'FINISHED'})
        finally:
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.meshes.remove(mesh)

    def test_05_disable_addon(self):
        """停用插件后环境完全还原"""
        addon_utils.disable(ADDON_NAME, default_set=False)

        self.assertFalse(
            hasattr(bpy.types, 'LOWPOLY_OT_run_all_checks'),
            "停用后操作符仍然存在",
        )
        self.assertFalse(hasattr(bpy.types, 'LOWPOLY_PT_quality_panel'))
        self.assertFalse(hasattr(bpy.types.Scene, "lowpoly"), "停用后 Scene.lowpoly 未清理")

        _, loaded_state = addon_utils.check(ADDON_NAME)
        self.assertFalse(loaded_state, "addon_utils 认为插件仍处于启用状态")

    def test_06_reenable_after_disable(self):
        """
        可重复启用/停用（开发者热重载与「停用后再启用」场景）

        回归测试：早期版本在注销时会把操作符类的 ``execute`` 方法一并删除，
        导致停用后再次启用时操作符虽然「已注册」但 poll 失败，调用只会
        返回 PASS_THROUGH。这里必须真正调用一次来验证。
        """
        for i in range(2):
            addon_utils.enable(ADDON_NAME, default_set=False, persistent=False)
            self.assertTrue(
                hasattr(bpy.types, 'LOWPOLY_OT_check_ngon_faces'),
                f"第 {i + 1} 次启用后操作符未注册",
            )
            # 真正调用，确保不是「已注册但 poll 失败」的坏状态
            self.assertEqual(
                bpy.ops.lowpoly.check_ngon_faces(), {'FINISHED'},
                f"第 {i + 1} 次启用后操作符无法执行（可能 execute 已丢失）",
            )
            self.assertEqual(bpy.ops.lowpoly.reset_all_params(), {'FINISHED'})

            addon_utils.disable(ADDON_NAME, default_set=False)
            self.assertFalse(hasattr(bpy.types, 'LOWPOLY_OT_check_ngon_faces'))


if __name__ == "__main__":
    unittest.main(verbosity=2, argv=[sys.argv[0]])
