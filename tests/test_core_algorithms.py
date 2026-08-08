"""
核心检测算法单元测试

运行方式（在 Blender Python 环境中）:
    blender --background --factory-startup --python-exit-code 1 --python tests/run_tests.py
"""

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
    get_collinear_vertices,
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
# 浮点常量测试
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    """浮点常量应当为正、且量级合理"""

    def test_epsilon_positive(self):
        self.assertGreater(EPSILON, 0.0)

    def test_zero_threshold_positive(self):
        self.assertGreater(ZERO_THRESHOLD, 0.0)

    def test_zero_threshold_small(self):
        self.assertLess(ZERO_THRESHOLD, 1e-2)


# ---------------------------------------------------------------------------
# 共线顶点检测测试
# ---------------------------------------------------------------------------

class TestCollinearVertices(unittest.TestCase):
    """共线顶点检测"""

    def test_empty_mesh_returns_empty(self):
        bm, obj, mesh = create_test_mesh("empty", [], [])
        try:
            self.assertEqual(get_collinear_vertices(bm), [])
        finally:
            cleanup_test_data(bm, obj, mesh)

    def test_cube_has_no_collinear_vertex(self):
        """立方体所有顶点度数均为 3，不应报告任何共线顶点"""
        verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                 (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
        faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        bm, obj, mesh = create_test_mesh("cube", verts, faces)
        try:
            self.assertEqual(get_collinear_vertices(bm), [])
        finally:
            cleanup_test_data(bm, obj, mesh)

    def test_detects_midpoint_of_split_edge(self):
        """在立方体一条边上插入中点后，该中点度数为 2 且三点严格共线"""
        verts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                 (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
                 (0.5, 0, 0)]  # index 8：边 0-1 的中点
        faces = [(0, 8, 1, 2, 3), (4, 5, 6, 7), (0, 8, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        bm, obj, mesh = create_test_mesh("split_edge", verts, faces)
        try:
            result = get_collinear_vertices(bm)
            self.assertEqual(result, [8])
        finally:
            cleanup_test_data(bm, obj, mesh)


if __name__ == "__main__":
    unittest.main(verbosity=2)
