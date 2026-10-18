"""
插件生命周期集成测试（在 Blender 3.4 中运行）

覆盖：
  1. 插件注册（enable）与注销（disable）的完整性与幂等性
  2. bl_info 元数据与 Blender 版本兼容性
  3. UI 面板使用的图标在目标 Blender 版本中全部有效
  4. 端到端检测：构造带缺陷的网格 → 运行全部检查 → 校验计数
  5. 选择功能：检查结果写入网格选择标志
  6. 过期结果清理、清除结果、参数重置
  7. 注销后环境完全还原

运行方式：
    blender --background --factory-startup --python-exit-code 1 \
        --python tests/test_addon_lifecycle.py
"""

import os
import re
import sys
import unittest

# ── 定位插件目录并加入 sys.path ──────────────────────────────────────
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
ADDON_NAME = os.path.basename(PLUGIN_DIR)

if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import bpy  # noqa: E402  (必须在 sys.path 设置之后导入)


# ── 版本号一致性 ────────────────────────────────────────────────────

def _changelog_latest_version():
    """
    从 ``CHANGELOG.md`` 解析最新版本段，返回 ``(major, minor, patch)``。

    版本号原本在此测试里硬编码。硬编码的问题是：每次发版都要记得改测试，
    忘记改就报一个「版本号应为 1.0.0」的误导性失败——测试本该守住一致性，
    反而变成第三处需要手工同步的地方。改为直接读 CHANGELOG，让「bl_info 版本
    ↔ CHANGELOG 版本」这条约束由测试自动校验。

    Returns:
        tuple[int, int, int]: CHANGELOG 中第一个版本段的版本号
    """
    changelog = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "CHANGELOG.md",
    )
    with open(changelog, encoding="utf-8") as fh:
        text = fh.read()
    match = re.search(r"^## \[(\d+)\.(\d+)\.(\d+)\]", text, re.M)
    if match is None:
        raise AssertionError(f"CHANGELOG.md 中找不到版本段标题：{changelog}")
    return tuple(int(part) for part in match.groups())


# ── 测试用缺陷网格 ───────────────────────────────────────────────────

def _make_object(name, verts, faces, edges=None):
    """通过 from_pydata 创建网格对象（不依赖 bpy.ops，后台模式可用）"""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, edges or [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def build_defect_scene():
    """
    构建包含已知缺陷的测试场景，返回 {名称: 对象}。

    各物体在空间上相互远离，避免触发「穿插物体」检测。
    """
    objects = {}

    # 1) N-gon：五边形（共面、非内凹、法线朝上）
    objects['ngon'] = _make_object(
        "T_Ngon",
        [(0, 0, 0), (1, 0, 0), (1.3, 1, 0), (0.5, 1.5, 0), (-0.3, 1, 0)],
        [(0, 1, 2, 3, 4)],
    )

    # 2) 非平面四边面：第 3 个顶点偏离平面 0.5
    objects['distorted'] = _make_object(
        "T_Distorted",
        [(10, 0, 0), (11, 0, 0), (11, 1, 0.5), (10, 1, 0)],
        [(0, 1, 2, 3)],
    )

    # 3) 未焊接点 + 重叠面：两个完全重合但未焊接的四边形
    quad = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    duplicated = [(x + 20.0, y, z) for (x, y, z) in quad]
    objects['unwelded'] = _make_object(
        "T_Unwelded",
        duplicated + duplicated,  # 4 个原始点 + 4 个重合副本
        [(0, 1, 2, 3), (4, 5, 6, 7)],
    )

    # 4) 退化边：四边形中两个相邻顶点位置重合
    objects['degenerate'] = _make_object(
        "T_Degenerate",
        [(30, 0, 0), (31, 0, 0), (31, 0, 0), (30, 1, 0)],
        [(0, 1, 2, 3)],
    )

    # 5) 孤立几何体：1 条悬浮边（其 2 个端点）+ 1 个悬浮顶点
    objects['loose'] = _make_object(
        "T_Loose",
        [(40, 0, 0), (41, 0, 0), (42, 0, 0),
         (43, 0, 0), (44, 0, 0), (44, 1, 0), (43, 1, 0)],
        [(3, 4, 5, 6)],
        edges=[(0, 1)],
    )

    # 6) 非流形边：被 3 个面共用的边
    objects['non_manifold'] = _make_object(
        "T_NonManifold",
        [(50, 0, 0), (51, 0, 0), (50, 1, 0), (50, -1, 0), (50, 0, 1)],
        [(0, 1, 2), (1, 0, 3), (0, 1, 4)],
    )

    for obj in objects.values():
        obj.select_set(False)
    return objects


# 期望的检测结果（与 build_defect_scene 一一对应）
EXPECTED_COUNTS = {
    'ngon_count': 1,
    'distorted_quad_count': 1,
    'concave_quad_count': 0,
    'unwelded_vert_count': 8,
    'collinear_vert_count': 0,
    'degenerate_edge_count': 1,
    'degenerate_face_count': 0,
    'overlapping_face_count': 2,
    'loose_vert_count': 3,
    'loose_edge_count': 1,
    'non_manifold_edge_count': 1,
    'wrong_normal_count': 0,
    'dense_vert_count': 0,
    'high_poly_count': 0,
    'downward_face_count': 0,
    'intersecting_object_count': 0,
    'non_uniform_scale_count': 0,
}

# UI 面板中使用的全部图标名称（需要逐个校验有效性）
UI_ICONS = (
    'MESH_DATA', 'FACESEL', 'NORMALS_FACE', 'EDGESEL', 'OUTLINER_OB_MESH',
    'VERTEXSEL', 'SCENE_DATA', 'OBJECT_DATA', 'RESTRICT_SELECT_OFF',
    'RESTRICT_SELECT_ON', 'INFO', 'ERROR', 'QUESTION', 'X',
    'FILE_REFRESH', 'LOOP_BACK',
)


class TestAddonLifecycle(unittest.TestCase):
    """插件加载 → 运行 → 卸载 的端到端验证

    .. note::
       unittest 按方法名排序执行，因此用 ``test_01`` … ``test_99``
       （以及最后的 ``test_zz_deferred``）保证阶段顺序。
    """

    objects = {}

    @classmethod
    def setUpClass(cls):
        # 清空默认场景，避免默认立方体干扰计数
        bpy.ops.wm.read_factory_settings(use_empty=True)

        # 先导入（验证「从路径加载」），再构建测试场景，最后注册
        import Blender_LowCheck  # noqa: F401
        cls.objects = build_defect_scene()

        from Blender_LowCheck import register
        register()

    # ── 阶段 1：属性组 / 操作符 / 面板注册完整性 ─────────────────
    def test_01_registration_complete(self):
        import Blender_LowCheck as addon

        self.assertTrue(hasattr(bpy.types.Scene, "lowpoly"), "Scene.lowpoly 未注册")
        props = bpy.context.scene.lowpoly
        self.assertIsInstance(props.only_selected, bool)

        for idname in (
            'LOWPOLY_OT_run_all_checks', 'LOWPOLY_OT_clear_results',
            'LOWPOLY_OT_check_ngon_faces', 'LOWPOLY_OT_select_ngon_faces',
            'LOWPOLY_OT_reset_param', 'LOWPOLY_OT_reset_all_params',
            'LOWPOLY_OT_run_all_optimization_checks',
        ):
            self.assertTrue(hasattr(bpy.types, idname), f"{idname} 未注册")

        self.assertTrue(hasattr(bpy.types, 'LOWPOLY_PT_quality_panel'))

        # 幂等：重复注册不应抛异常，也不应重复注册（否则 Blender 会报错）
        addon.register()

    # ── 阶段 2：元数据与版本兼容性 ───────────────────────────────
    def test_02_bl_info_metadata(self):
        import Blender_LowCheck as addon

        info = addon.bl_info
        declared = info['blender'][0] * 100 + info['blender'][1]
        running = bpy.app.version[0] * 100 + bpy.app.version[1]
        self.assertLessEqual(declared, running, "bl_info 声明的最低版本高于当前 Blender")
        self.assertTrue(info['name'])
        self.assertTrue(info['description'])
        self.assertEqual(info['category'], 'Mesh')
        self.assertEqual(
            tuple(info['version']),
            _changelog_latest_version(),
            "bl_info.version 必须与 CHANGELOG.md 的最新版本段一致"
            "（文档【九.2】：插件版本号必须与 git 标签一致，"
            "而标签是照 CHANGELOG 打的）",
        )

    # ── 阶段 3：UI 图标有效性 ───────────────────────────────────
    def test_03_ui_icons_valid(self):
        try:
            enum_items = bpy.types.UILayout.bl_rna.functions['label'] \
                .parameters['icon'].enum_items
            valid = {item.identifier for item in enum_items}
        except (AttributeError, KeyError, TypeError) as exc:  # pragma: no cover
            self.skipTest(f"当前 Blender 无法读取图标枚举: {exc}")

        self.assertGreater(len(valid), 100, "图标枚举异常，测试环境不可信")
        missing = sorted(icon for icon in UI_ICONS if icon not in valid)
        self.assertEqual(missing, [], f"以下图标在当前 Blender 中不存在: {missing}")

    # ── 阶段 3b：注册表 / 面板 / 属性三者一致性 ─────────────────
    def test_03b_panel_references_are_valid(self):
        """
        registry（单一数据源）、UI 面板、属性组、已注册操作符必须完全一致。

        面板是惰性绘制的：写错操作符 idname 或属性名不会立刻报错，只会在
        用户打开侧边栏时才可见地失败。改为校验 registry 后，本测试同时覆盖
        「UI 引用完整性」与「检测项声明完整性」——比过去用正则解析 ui.py
        源码更严格，也不会因为 UI 改成数据驱动而失效。
        """
        from Blender_LowCheck import registry
        from Blender_LowCheck.operators import check_operators, optimize_operators
        from Blender_LowCheck.properties import ALL_DEFAULTS, THRESHOLD_SUFFIX

        registered_ops = {
            cls.bl_idname
            for cls in bpy.types.Operator.__subclasses__()
            if getattr(cls, "bl_idname", "").startswith("lowpoly.")
        }
        # 注意：bpy.types.Scene.lowpoly 是属性声明对象（_PropertyDeferred），
        # 必须从实例上取 bl_rna
        available_props = {
            prop.identifier for prop in bpy.context.scene.lowpoly.bl_rna.properties
        }

        # 1) 检测项引用的操作符 / 属性必须真实存在
        for spec in registry.CHECKS:
            self.assertIn(spec.check_op, registered_ops, f"{spec.key} 的检查操作符未注册")
            self.assertIn(spec.select_op, registered_ops, f"{spec.key} 的选择操作符未注册")
            for name in spec.count_props:
                self.assertIn(
                    name, available_props, f"{spec.key} 引用了不存在的计数属性 {name}"
                )
            for name in spec.thresholds:
                self.assertIn(
                    name, available_props, f"{spec.key} 引用了不存在的阈值 {name}"
                )

        # 2) 分组必须覆盖全部检测项，且不存在空分组
        group_keys = [key for key, _label, _icon in registry.GROUPS]
        for key in group_keys:
            self.assertTrue(registry.checks_in_group(key), f"分组 {key} 下没有任何检测项")
        self.assertEqual(
            sorted({spec.group for spec in registry.CHECKS}), sorted(group_keys),
            "存在不属于任何分组的检测项",
        )

        # 3) 检测项 key 必须唯一（否则结果字典会互相覆盖）
        keys = [spec.key for spec in registry.CHECKS]
        self.assertEqual(len(keys), len(set(keys)), "registry.CHECKS 中存在重复的 key")

        # 4) 计数属性必须与两个模块的 COUNT_PROPERTIES 完全对齐
        self.assertEqual(
            set(registry.count_properties()),
            set(check_operators.COUNT_PROPERTIES) | set(optimize_operators.COUNT_PROPERTIES),
        )

        # 5) ALL_DEFAULTS 必须恰好等于「全部阈值参数」，且命名符合约定
        self.assertEqual(
            set(ALL_DEFAULTS), set(registry.threshold_parameters()),
            "ALL_DEFAULTS 与 registry 声明的阈值不一致",
        )
        for name in ALL_DEFAULTS:
            self.assertTrue(
                name.endswith(THRESHOLD_SUFFIX),
                f"阈值参数 {name} 未遵循 {THRESHOLD_SUFFIX} 命名约定，默认值将无法自动派生",
            )

        # 抽查具体值，防止 _populate_defaults 静默失败（返回空字典也能通过集合相等）
        # 注意：Blender 的 FloatProperty 以 float32 存储，0.01 会变成 0.0099999998，
        # 因此必须用近似比较。
        self.assertAlmostEqual(ALL_DEFAULTS.get('distortion_threshold'), 0.01, places=6)
        self.assertEqual(ALL_DEFAULTS.get('dense_count_threshold'), 5)
        self.assertEqual(ALL_DEFAULTS.get('polycount_threshold'), 50)

        # 6) 不允许存在「已注册但无人引用」的操作符（漏登记到 registry）
        orphan_ops = sorted(registered_ops - set(registry.all_operator_ids()))
        self.assertEqual(
            orphan_ops, [],
            f"以下操作符已注册但未登记到 registry（面板不会绘制它们）: {orphan_ops}",
        )

        # 7) 数量文案模板的占位符必须与 count_props 完全一致
        #    （模板写错属性名只会在用户打开面板时才暴露，这里提前拦住）
        for spec in registry.CHECKS:
            placeholders = set(re.findall(r"\{(\w+)\}", spec.count_template))
            self.assertEqual(
                placeholders, set(spec.count_props),
                f"{spec.key} 的数量文案模板占位符 {placeholders} "
                f"与 count_props {set(spec.count_props)} 不一致",
            )
            # 必须能真正渲染出来（且不抛 KeyError）
            rendered = spec.count_template.format(**{name: 0 for name in spec.count_props})
            self.assertTrue(rendered.strip(), f"{spec.key} 的数量文案渲染为空")

    # ── 阶段 4：端到端检测 ──────────────────────────────────────
    def test_04_run_all_checks(self):
        result = bpy.ops.lowpoly.run_all_checks()
        self.assertEqual(result, {'FINISHED'})

        props = bpy.context.scene.lowpoly
        actual = {name: getattr(props, name) for name in EXPECTED_COUNTS}

        lines = ["", "[结果] 全量检测计数:"]
        for name in sorted(EXPECTED_COUNTS):
            ok = actual[name] == EXPECTED_COUNTS[name]
            lines.append(
                f"  {'OK ' if ok else '!! '}{name:32s} 期望={EXPECTED_COUNTS[name]:>3}  实际={actual[name]:>3}"
            )
        print("\n".join(lines))

        for name, expected in EXPECTED_COUNTS.items():
            self.assertEqual(actual[name], expected, f"{name} 计数不符")

    def test_05_optimize_checks(self):
        props = bpy.context.scene.lowpoly
        self.assertEqual(bpy.ops.lowpoly.run_all_optimization_checks(), {'FINISHED'})
        # 测试网格中所有面都是孤立面（相邻面数 < 2），因此不会判定为小倒角
        self.assertEqual(props.small_bevel_count, 0)
        self.assertEqual(props.high_poly_count, 0)
        self.assertEqual(props.intersecting_object_count, 0)
        self.assertEqual(props.non_uniform_scale_count, 0)

    # ── 阶段 5：选择功能 ────────────────────────────────────────
    def test_06_selection(self):
        from Blender_LowCheck.operators import check_operators

        ngon_obj = self.objects['ngon']
        for polygon in ngon_obj.data.polygons:
            polygon.select = False

        self.assertEqual(bpy.ops.lowpoly.check_ngon_faces(), {'FINISHED'})
        self.assertIn('ngon_faces', check_operators.check_results)

        self.assertEqual(bpy.ops.lowpoly.select_ngon_faces(), {'FINISHED'})
        selected = [i for i, p in enumerate(ngon_obj.data.polygons) if p.select]
        self.assertEqual(selected, [0], "N-gon 面未被正确选中")

        unwelded_obj = self.objects['unwelded']
        self.assertEqual(bpy.ops.lowpoly.check_unwelded_vertices(), {'FINISHED'})
        self.assertEqual(bpy.ops.lowpoly.select_unwelded_vertices(), {'FINISHED'})
        selected_verts = [i for i, v in enumerate(unwelded_obj.data.vertices) if v.select]
        self.assertEqual(len(selected_verts), 8, "未焊接点选择数量不符")

        # 物体级选择
        self.assertEqual(bpy.ops.lowpoly.suggest_high_poly_objects(), {'FINISHED'})
        self.assertEqual(bpy.ops.lowpoly.select_high_poly_objects(), {'CANCELLED'})

    # ── 阶段 6：过期结果清理 ────────────────────────────────────
    def test_07_stale_result_cleanup(self):
        from Blender_LowCheck.operators import check_operators

        props = bpy.context.scene.lowpoly

        self.assertEqual(bpy.ops.lowpoly.check_ngon_faces(), {'FINISHED'})
        self.assertIn('ngon_faces', check_operators.check_results)

        # 切换为「仅处理选中物体」且不选中任何物体 → 结果为空并清除旧键
        props.only_selected = True
        try:
            self.assertEqual(bpy.ops.lowpoly.check_ngon_faces(), {'FINISHED'})
            self.assertNotIn(
                'ngon_faces', check_operators.check_results,
                "检测无结果时未清除历史结果，会导致「选择」选中过期索引",
            )
            self.assertEqual(props.ngon_count, 0)
            self.assertEqual(bpy.ops.lowpoly.select_ngon_faces(), {'CANCELLED'})
        finally:
            props.only_selected = False

        # 恢复后应能正常检测
        self.assertEqual(bpy.ops.lowpoly.check_ngon_faces(), {'FINISHED'})
        self.assertEqual(props.ngon_count, 1)

    # ── 阶段 7：清除结果与参数重置 ──────────────────────────────
    def test_08_clear_and_reset(self):
        props = bpy.context.scene.lowpoly
        self.assertEqual(bpy.ops.lowpoly.run_all_checks(), {'FINISHED'})
        self.assertGreater(props.ngon_count, 0)

        self.assertEqual(bpy.ops.lowpoly.clear_results(), {'FINISHED'})
        self.assertEqual(props.ngon_count, 0)
        self.assertEqual(props.unwelded_vert_count, 0)
        self.assertEqual(props.non_manifold_edge_count, 0)

        props.distortion_threshold = 5.0
        props.collinear_threshold = 1.0
        self.assertEqual(
            bpy.ops.lowpoly.reset_param(param_name='distortion_threshold'),
            {'FINISHED'},
        )
        self.assertAlmostEqual(props.distortion_threshold, 0.01, places=6)

        self.assertEqual(bpy.ops.lowpoly.reset_all_params(), {'FINISHED'})
        self.assertAlmostEqual(props.collinear_threshold, 0.01, places=6)

        # 非法参数名 / 缺少参数应安全返回，不抛异常
        self.assertEqual(bpy.ops.lowpoly.reset_param(param_name='not_a_param'), {'CANCELLED'})

    # ── 阶段 8：错误守卫已安装 ──────────────────────────────────
    def test_09_error_guard_installed(self):
        from Blender_LowCheck.operators import check_operators, optimize_operators

        for cls in list(check_operators.classes) + list(optimize_operators.classes):
            self.assertTrue(
                getattr(cls.__dict__.get('execute'), '_lowpoly_guarded', False),
                f"{cls.__name__} 未安装异常守卫",
            )

    # ── 阶段 9：注销（必须最后执行） ────────────────────────────
    def test_zz_unregister(self):
        import Blender_LowCheck as addon
        from Blender_LowCheck.operators import check_operators, optimize_operators

        addon.unregister()

        self.assertFalse(hasattr(bpy.types.Scene, "lowpoly"), "Scene.lowpoly 未清理")
        self.assertFalse(hasattr(bpy.types, 'LOWPOLY_PT_quality_panel'))

        for cls in list(check_operators.classes) + list(optimize_operators.classes):
            self.assertFalse(
                hasattr(bpy.types, cls.__name__),
                f"{cls.__name__} 注销后仍在 bpy.types 中",
            )
            # 回归测试：注销必须「还原」而不是「删除」execute，
            # 否则插件停用后再次启用时所有操作符都会失效（PASS_THROUGH）
            self.assertIsNotNone(
                cls.__dict__.get('execute'),
                f"{cls.__name__} 注销后 execute 方法丢失，重新启用将无法工作",
            )

        # 幂等：重复注销不应抛异常
        addon.unregister()
        self.assertFalse(hasattr(bpy.types.Scene, "lowpoly"))

    # ── 阶段 10：注销后重新注册仍可用 ────────────────────────────
    def test_zzz_reregister_still_works(self):
        import Blender_LowCheck as addon

        addon.register()
        self.addCleanup(addon.unregister)

        self.assertTrue(hasattr(bpy.types, 'LOWPOLY_OT_run_all_checks'))
        # 真正调用一次，确保操作符不是「已注册但 poll 失败」的坏状态
        self.assertEqual(bpy.ops.lowpoly.check_ngon_faces(), {'FINISHED'})
        self.assertEqual(bpy.ops.lowpoly.reset_all_params(), {'FINISHED'})

    # ── 阶段 11：reload_modules 不留下孤儿注册（必须最后执行） ────
    def test_zzzz_reload_modules_leaves_no_orphans(self):
        """
        ``reload_modules()`` 必须遵循「先注销 → 再 reload → 再注册」。

        回归测试：旧实现只 reload 不注销。``importlib.reload`` 会在同一
        模块命名空间中重新执行源码，从而**重建全部类对象**，而 ``bpy.types``
        里注册的仍是旧类——旧类成为孤儿，之后停用无法清理，再次启用还会
        因 ``bl_idname`` 冲突失败；同时 ``_GUARD_ORIGINALS`` 被清空，
        异常守卫的「原始 execute」映射丢失。
        """
        import Blender_LowCheck as addon
        from Blender_LowCheck.operators import base

        addon.reload_modules()
        self.addCleanup(addon.unregister)

        # 1) 注册状态完整
        self.assertTrue(hasattr(bpy.types, 'LOWPOLY_OT_run_all_checks'), "reload 后操作符未注册")
        self.assertTrue(hasattr(bpy.types.Scene, "lowpoly"), "reload 后属性组未注册")
        self.assertTrue(hasattr(bpy.types, 'LOWPOLY_PT_quality_panel'), "reload 后面板未注册")

        # 2) 异常守卫的原始 execute 映射必须被重建（37 个操作符）
        self.assertEqual(
            len(base._GUARD_ORIGINALS), 37,
            "reload 后异常守卫映射丢失，注销将无法还原原始 execute",
        )

        # 3) 真正调用一次，确认不是「已注册但 poll 失败」的坏状态
        self.assertEqual(bpy.ops.lowpoly.check_ngon_faces(), {'FINISHED'})
        self.assertEqual(bpy.ops.lowpoly.run_all_checks(), {'FINISHED'})

        # 4) 停用必须彻底（不能残留孤儿类）
        addon.unregister()
        self.assertFalse(
            hasattr(bpy.types, 'LOWPOLY_OT_run_all_checks'),
            "reload 后停用未能清理操作符（存在孤儿注册）",
        )
        self.assertFalse(hasattr(bpy.types.Scene, "lowpoly"))
        self.assertEqual(len(base._GUARD_ORIGINALS), 0)


if __name__ == "__main__":
    # 注意：Blender 会把自身的命令行参数放进 sys.argv，必须显式清空，
    # 否则 unittest 会因解析到 --background 等参数而报错。
    unittest.main(verbosity=2, argv=[sys.argv[0]])
