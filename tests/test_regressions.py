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

from Blender_LowCheck import utils  # noqa: E402
from Blender_LowCheck.utils import (  # noqa: E402
    get_collinear_vertices,
    get_faces_sharing_all_edges,
    get_unwelded_vertices,
    is_face_concave,
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


class TestConcaveScaleIndependence(unittest.TestCase):
    """回归：内凹判据曾把**带量纲**的叉积模与无量纲容差直接比较，
    导致小尺寸面被静默漏判为凸。"""

    def test_small_concave_quad_is_detected(self):
        verts = [(0, 0, 0), (0.02, 0, 0), (0.01, 0.005, 0), (0, 0.02, 0)]
        bm, obj, mesh = create_test_mesh("small_concave", verts, [(0, 1, 2, 3)])
        try:
            self.assertTrue(is_face_concave(bm.faces[0]))
        finally:
            cleanup_test_data(bm, obj, mesh)


class TestQuantizationBoundary(unittest.TestCase):
    """回归：坐标量化分桶在相邻网格边界两侧会漏检
    （未焊接点与重叠面检测同源缺陷）。"""

    def test_unwelded_vertices_across_bucket_boundary(self):
        # 两点相距 0.0002（< 阈值 0.001），但量化后落在相邻桶
        verts = [(0.0004, 0, 0), (0.0006, 0, 0), (1, 0, 0), (1, 0, 0.5), (1, 0.5, 0)]
        faces = [(0, 2, 3), (1, 2, 4)]
        bm, obj, mesh = create_test_mesh("unwelded_edge_case", verts, faces)
        try:
            self.assertEqual(get_unwelded_vertices(bm, 0.001), [0, 1])
        finally:
            cleanup_test_data(bm, obj, mesh)

    def test_overlapping_faces_across_bucket_boundary(self):
        verts = [(0.0004, 0, 0), (1.0004, 0, 0), (0.0004, 1, 0),
                 (0.0006, 0, 0), (1.0006, 0, 0), (0.0006, 1, 0)]
        faces = [(0, 1, 2), (3, 4, 5)]
        bm, obj, mesh = create_test_mesh("overlap_edge_case", verts, faces)
        try:
            self.assertEqual(sorted(get_faces_sharing_all_edges(bm, 0.001)), [0, 1])
        finally:
            cleanup_test_data(bm, obj, mesh)


#: 单位立方体（外法线朝外），供需要闭合网格的回归用例复用
CUBE_VERTS = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
              (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
CUBE_FACES = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
              (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


class TestSelectionClearsResidualSubElements(unittest.TestCase):
    """回归：``_clear_mesh_selection`` 曾只清目标元素类型，上一次操作遗留的
    顶点/边选择会在进入编辑模式时被 Blender 的选择传播放大成「整个网格
    全选」——用户点「选择」看到的是一堆边，而不是检测出的那几个面。"""

    def test_selecting_one_face_clears_residual_edge_and_vert_selection(self):
        bm, obj, mesh = create_test_mesh("selection_residue", CUBE_VERTS, CUBE_FACES)
        try:
            # 模拟上一次操作遗留：顶点与边全部处于选中状态
            for edge in mesh.edges:
                edge.select = True
            for vert in mesh.vertices:
                vert.select = True

            utils._apply_mesh_selection(obj, 'FACE', [0])

            self.assertEqual(sum(1 for p in mesh.polygons if p.select), 1)
            self.assertEqual(sum(1 for e in mesh.edges if e.select), 0)
            self.assertEqual(sum(1 for v in mesh.vertices if v.select), 0)
        finally:
            cleanup_test_data(bm, obj, mesh)

    def test_selecting_vertices_clears_residual_face_selection(self):
        bm, obj, mesh = create_test_mesh("selection_residue_vert", CUBE_VERTS, CUBE_FACES)
        try:
            for polygon in mesh.polygons:
                polygon.select = True

            utils._apply_mesh_selection(obj, 'VERT', [0, 1])

            self.assertEqual(sum(1 for v in mesh.vertices if v.select), 2)
            self.assertEqual(sum(1 for p in mesh.polygons if p.select), 0)
            self.assertEqual(sum(1 for e in mesh.edges if e.select), 0)
        finally:
            cleanup_test_data(bm, obj, mesh)


if __name__ == "__main__":
    unittest.main(verbosity=2)
