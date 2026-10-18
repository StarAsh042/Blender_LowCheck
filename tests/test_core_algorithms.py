"""
核心检测算法单元测试

运行方式（在 Blender Python 环境中）:
    blender --background --factory-startup --python-exit-code 1 --python tests/run_tests.py
"""

import math
import os
import sys
import unittest

# 将插件所在目录加入 sys.path，以便以包的形式导入插件
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import bpy  # noqa: E402
import bmesh  # noqa: E402

from Blender_LowCheck.utils import (  # noqa: E402
    EPSILON,
    ZERO_THRESHOLD,
    CONCAVITY_TOLERANCE,
    is_face_concave,
    calculate_face_planarity,
)


# ---------------------------------------------------------------------------
# 测试辅助函数
# ---------------------------------------------------------------------------

def create_test_mesh(name, verts_co, faces_idx):
    """创建一个测试用 mesh 并返回 (bmesh, obj, mesh)"""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts_co, [], faces_idx)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    return bm, obj, mesh


def cleanup_test_data(bm, obj, mesh):
    """清理测试数据"""
    bm.free()
    bpy.data.objects.remove(obj)
    bpy.data.meshes.remove(mesh)


# ---------------------------------------------------------------------------
# is_face_concave 测试
# ---------------------------------------------------------------------------

class TestIsFaceConcave(unittest.TestCase):
    """测试内凹/外凸四边面判断"""

    def test_convex_square(self):
        """正方形应返回 False（外凸）"""
        bm, obj, mesh = create_test_mesh("ConvexSquare", [
            (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
        ], [(0, 1, 2, 3)])
        self.assertFalse(is_face_concave(bm.faces[0]))
        cleanup_test_data(bm, obj, mesh)

    def test_concave_dart_quad(self):
        """内凹四边形（飞镖形）应返回 True"""
        bm, obj, mesh = create_test_mesh("ConcaveDart", [
            (0, 0, 0), (0.2, 0.2, 0), (1, 0, 0), (0.5, 1, 0),
        ], [(0, 1, 2, 3)])
        self.assertTrue(is_face_concave(bm.faces[0]))
        cleanup_test_data(bm, obj, mesh)

    def test_triangle_is_not_concave(self):
        """三角形（非四边形）应返回 False"""
        bm, obj, mesh = create_test_mesh("Triangle", [
            (0, 0, 0), (1, 0, 0), (0, 1, 0),
        ], [(0, 1, 2)])
        self.assertFalse(is_face_concave(bm.faces[0]))
        cleanup_test_data(bm, obj, mesh)

    def test_near_collinear_but_convex(self):
        """
        近乎共线的顶点在凸四边形中不应被误判为内凹

        说明: 顶点 (0.5, -0.005) 位于 0-2 连线下方，四边形仍为凸多边形，
              只是某个内角接近 180°，检测结果应为 False。
        """
        bm, obj, mesh = create_test_mesh("NearFlatConvex", [
            (0, 0, 0), (0.5, -0.005, 0), (1, 0, 0), (1, 1, 0),
        ], [(0, 1, 2, 3)])
        self.assertFalse(is_face_concave(bm.faces[0]))
        cleanup_test_data(bm, obj, mesh)

    def test_near_collinear_reflex_is_concave(self):
        """顶点向多边形内部凸起（内角接近 180° 的反向）时应判定为内凹"""
        bm, obj, mesh = create_test_mesh("NearFlatConcave", [
            (0, 0, 0), (0.5, 0.005, 0), (1, 0, 0), (1, 1, 0),
        ], [(0, 1, 2, 3)])
        self.assertTrue(is_face_concave(bm.faces[0]))
        cleanup_test_data(bm, obj, mesh)

    def test_concave_detection_is_scale_invariant(self):
        """
        回归：内凹判定必须与模型尺度无关。

        旧实现把**叉积的模**（量纲为长度²）与固定容差比较，小尺寸面的叉积
        天然很小，会被误判为「共线角」而跳过 —— 边长 ≲1e-3 的模型会静默
        漏检内凹面。修复后改用无量纲的 ``|sin θ|`` 判据。

        注：缩放下限取到 0.0005（最短边约 1.4e-4）。再小就会落入「退化边」
        的**绝对**长度阈值（``ZERO_THRESHOLD = 1e-4``），此时按定义属于
        退化面，返回 False 是预期行为。
        """
        base = [(0, 0, 0), (0.2, 0.2, 0), (1, 0, 0), (0.5, 1, 0)]
        for scale in (1.0, 0.1, 0.01, 0.005, 0.002, 0.001, 0.0005):
            verts = [(x * scale, y * scale, z * scale) for (x, y, z) in base]
            bm, obj, mesh = create_test_mesh(
                f"ConcaveScale{scale}", verts, [(0, 1, 2, 3)]
            )
            try:
                self.assertTrue(
                    is_face_concave(bm.faces[0]),
                    f"尺度 {scale} 下的内凹四边形被漏判为凸",
                )
            finally:
                cleanup_test_data(bm, obj, mesh)


# ---------------------------------------------------------------------------
# calculate_face_planarity 测试
# ---------------------------------------------------------------------------

class TestCalculateFacePlanarity(unittest.TestCase):
    """测试四边面平面度计算"""

    def test_perfectly_planar_quad(self):
        """完全共面的四边面返回 0.0"""
        bm, obj, mesh = create_test_mesh("PerfectPlanar", [
            (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
        ], [(0, 1, 2, 3)])
        self.assertAlmostEqual(calculate_face_planarity(bm.faces[0]), 0.0, places=6)
        cleanup_test_data(bm, obj, mesh)

    def test_non_planar_greater_than_zero(self):
        """不共面四边面返回 > 0"""
        bm, obj, mesh = create_test_mesh("NonPlanar", [
            (0, 0, 0), (1, 0, 0), (1, 1, 0.5), (0, 1, 0),
        ], [(0, 1, 2, 3)])
        self.assertGreater(calculate_face_planarity(bm.faces[0]), 0.0)
        cleanup_test_data(bm, obj, mesh)

    def test_triangle_returns_zero(self):
        """三角形应返回 0.0（非四边面）"""
        bm, obj, mesh = create_test_mesh("TriPlanar", [
            (0, 0, 0), (1, 0, 0), (0, 1, 0),
        ], [(0, 1, 2)])
        self.assertEqual(calculate_face_planarity(bm.faces[0]), 0.0)
        cleanup_test_data(bm, obj, mesh)

    def test_collinear_first_three_verts_fallback(self):
        """
        前三点**精确**共线时走「回退法线」分支，返回 0.0

        注意：本用例的四点恰好共面（v1 在 v0→v2 线段上，必在
        v0/v2/v3 所定平面内），所以结果是 0.0。但这**不是普遍规律**——
        「四边形有三点共线 ⇒ 四点共面」是错的，共面的只是这一例的几何。
        这里锁定的是「回退分支不抛异常且对共面几何给 0」。
        """
        bm, obj, mesh = create_test_mesh("CollinearFirst3", [
            (0, 0, 0), (0.5, 0, 0), (1, 0, 0), (0.5, 1, 0.5),
        ], [(0, 1, 2, 3)])
        self.assertEqual(calculate_face_planarity(bm.faces[0]), 0.0)
        cleanup_test_data(bm, obj, mesh)

    def test_near_collinear_first_three_uses_fallback(self):
        """
        前三点**近**共线时必须走回退，而不是拿噪声法线算垃圾值。

        回归：原实现的退化判据是 ``geometry.normal(...).length_squared
        < EPSILON``，而 ``geometry.normal`` 返回**单位向量**——归一化后
        长度恒为 1，该判据只在**精确**共线时成立，对近共线面永不触发。
        于是近共线面拿到一个由浮点噪声主导方向的「法线」，平面度是垃圾
        （实测：本例旧实现返回 0.2，而它其实几乎是平面）。

        本例前三点夹角正弦 ~1e-9（远低于 COLLINEAR_SIN_THRESHOLD=1e-6），
        且四点共面，故正确结果应≈0。
        """
        bm, obj, mesh = create_test_mesh("NearCollinear", [
            (0, 0, 0), (1, 0, 0), (2, 1e-9, 0), (0.5, 0.3, 0.2),
        ], [(0, 1, 2, 3)])
        result = calculate_face_planarity(bm.faces[0])
        self.assertLess(result, 1e-6,
                        f"近共线面应走回退分支得到≈0，实得 {result}")
        cleanup_test_data(bm, obj, mesh)

    def test_collinear_guard_is_scale_invariant(self):
        """
        共线判据必须**无量纲**：同一形状在不同尺度下结论一致。

        回归风险：若改用绝对长度阈值（如 |cross| < 常数），小尺度模型上
        正常面会被误判为退化。实测踩坑过——边长 3 厘米的正常四边形面，
        |cross|² ≈ 8e-8，会小于 1e-6 量级的绝对阈值。
        """
        for scale in (1.0, 0.03, 0.001, 1e-4):
            verts = [
                (0, 0, 0),
                (1 * scale, 0, 0),
                (2 * scale, 1e-3 * scale, 0),
                (0.5 * scale, 0.3 * scale, 0.2 * scale),
            ]
            bm, obj, mesh = create_test_mesh(f"Scale{scale}", verts,
                                             [(0, 1, 2, 3)])
            # 良态面（夹角正弦 1e-3 > 阈值），各尺度应得到同一结论
            result = calculate_face_planarity(bm.faces[0])
            self.assertGreater(result, 0.0,
                               f"尺度 {scale} 下良态面被判成退化了")
            cleanup_test_data(bm, obj, mesh)

    def test_nearly_collinear_helper(self):
        """/_nearly_collinear/ 本身的行为：无量纲、零边也判共线"""
        from Blender_LowCheck.utils import _nearly_collinear
        from mathutils import Vector

        # 平行（夹角正弦 0）→ 共线
        self.assertTrue(_nearly_collinear(Vector((1, 0, 0)), Vector((2, 0, 0))))
        # 垂直（夹角正弦 1）→ 不共线
        self.assertFalse(_nearly_collinear(Vector((1, 0, 0)), Vector((0, 1, 0))))
        # 尺度无关：同样夹角，放大 1e6 倍结论不变
        self.assertTrue(_nearly_collinear(Vector((1e6, 0, 0)),
                                          Vector((2e6, 1e-3, 0))))
        # 零长度边 → 共线（退化）
        self.assertTrue(_nearly_collinear(Vector((0, 0, 0)), Vector((1, 0, 0))))

    def test_all_collinear_returns_zero(self):
        """所有点共线时退化为 0.0"""
        bm, obj, mesh = create_test_mesh("AllCollinear", [
            (0, 0, 0), (0.3, 0, 0), (0.6, 0, 0), (1, 0, 0),
        ], [(0, 1, 2, 3)])
        self.assertEqual(calculate_face_planarity(bm.faces[0]), 0.0)
        cleanup_test_data(bm, obj, mesh)


# ---------------------------------------------------------------------------
# 数值精度 / 浮点常量测试
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    """测试模块常量的合理性"""

    def test_epsilon_is_reasonable(self):
        """EPSILON 在合理范围内"""
        self.assertGreater(EPSILON, 0)
        self.assertLess(EPSILON, 1e-3)

    def test_concavity_tolerance(self):
        """内凹容差应小于 0.01 弧度（约 0.57 度）"""
        self.assertLess(CONCAVITY_TOLERANCE, 0.01)

    def test_zero_threshold(self):
        """零长度/零面积阈值应为正的小量"""
        self.assertGreater(ZERO_THRESHOLD, 0)


# ---------------------------------------------------------------------------
# 几何辅助测试
# ---------------------------------------------------------------------------

class TestGeometryHelpers(unittest.TestCase):
    """测试内联几何辅助逻辑"""

    def test_face_area_is_positive(self):
        """正常面的面积应为正数"""
        bm, obj, mesh = create_test_mesh("AreaTest", [
            (0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0),
        ], [(0, 1, 2, 3)])
        self.assertGreater(bm.faces[0].calc_area(), 0)
        cleanup_test_data(bm, obj, mesh)

    def test_edge_length(self):
        """边长度计算正确"""
        bm, obj, mesh = create_test_mesh("EdgeLength", [
            (0, 0, 0), (3, 4, 0),
        ], [(0, 1)])
        bm.edges.ensure_lookup_table()
        self.assertAlmostEqual(bm.edges[0].calc_length(), 5.0, places=6)
        cleanup_test_data(bm, obj, mesh)

    def test_face_normal_upward(self):
        """朝上的面法线应接近 (0, 0, 1)"""
        bm, obj, mesh = create_test_mesh("NormalUp", [
            (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
        ], [(0, 1, 2, 3)])
        normal = bm.faces[0].normal
        self.assertAlmostEqual(normal.x, 0.0, places=6)
        self.assertAlmostEqual(normal.y, 0.0, places=6)
        self.assertAlmostEqual(abs(normal.z), 1.0, places=6)
        cleanup_test_data(bm, obj, mesh)

    def test_face_normal_downward(self):
        """顶点顺序反转的法线应朝下"""
        bm, obj, mesh = create_test_mesh("NormalDown", [
            (0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0),
        ], [(0, 1, 2, 3)])
        normal = bm.faces[0].normal
        self.assertAlmostEqual(normal.z, -1.0, places=6)
        cleanup_test_data(bm, obj, mesh)

    def test_math_module_available(self):
        """math 模块可用（保证测试环境完整）"""
        self.assertAlmostEqual(math.radians(180), math.pi, places=9)


def load_tests(loader, standard_tests, pattern):
    """测试加载器"""
    suite = unittest.TestSuite()
    for case in (TestIsFaceConcave, TestCalculateFacePlanarity,
                 TestConstants, TestGeometryHelpers):
        suite.addTests(loader.loadTestsFromTestCase(case))
    return suite


if __name__ == "__main__":
    unittest.main(verbosity=2, argv=[sys.argv[0]])
