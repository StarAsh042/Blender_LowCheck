"""
缺陷回归测试

每一项对应一个已修复的具体缺陷：这些测试在修复之前会失败，
用于防止缺陷复发。
"""

import os
import sys
import unittest

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import bpy  # noqa: E402
import bmesh  # noqa: E402

from Blender_LowCheck.utils import (  # noqa: E402
    get_collinear_vertices,
)


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


class TestCollinearThresholdSemantics(unittest.TestCase):
    """回归：共线判据曾写作 ``|cos θ| > 1 - threshold``（线性近似），
    把阈值语义放大约 14 倍，且 threshold 接近 1.57 时判据恒真。"""

    def test_large_threshold_does_not_flag_right_angle(self):
        # A(0,0,0) — M(1,0,0) — B(1,1,0)：在 M 处转弯 90°，|cos θ| = 0
        verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, -1, 0)]
        faces = [(0, 1, 2, 3), (0, 1, 2, 4)]
        bm, obj, mesh = create_test_mesh("right_angle", verts, faces)
        try:
            # threshold = 1.5 rad ≈ 86°：90° 的转角显然不该算共线
            self.assertEqual(get_collinear_vertices(bm, 1.5), [])
        finally:
            cleanup_test_data(bm, obj, mesh)


if __name__ == "__main__":
    unittest.main(verbosity=2)
