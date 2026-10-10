"""
Rust 内核 ↔ 纯 Python 实现一致性测试

对随机生成的网格，逐点比对两条实现的结果：Rust 只允许**更快**，
不允许**不同**。未构建内核扩展时整体跳过（不影响其余测试）。
"""

import os
import random
import sys
import unittest

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import bpy  # noqa: E402
import bmesh  # noqa: E402

from Blender_LowCheck import utils  # noqa: E402


def _to_bmesh(name, verts_co, faces_idx):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts_co, [], faces_idx)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    return bm, obj, mesh


def _cleanup(bm, obj, mesh):
    bm.free()
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.meshes.remove(mesh)


def _split_edge_cubes(seed, count):
    """
    构造 ``count`` 个「立方体一条边插入中点」的结构。

    每个中点都是**度数 2、非边界**的严格共线顶点——正是共线检测的目标。
    """
    rng = random.Random(seed)
    verts, faces = [], []
    expected = []
    for _ in range(count):
        ox, oy, oz = (rng.uniform(-5.0, 5.0) for _ in range(3))
        s = rng.uniform(0.5, 2.0)
        b = len(verts)
        for (x, y, z) in [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                          (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]:
            verts.append((ox + x * s, oy + y * s, oz + z * s))
        verts.append((ox + 0.5 * s, oy, oz))
        expected.append(b + 8)
        faces += [
            (b + 0, b + 8, b + 1, b + 2, b + 3),
            (b + 4, b + 5, b + 6, b + 7),
            (b + 0, b + 8, b + 1, b + 5, b + 4),
            (b + 1, b + 2, b + 6, b + 5),
            (b + 2, b + 3, b + 7, b + 6),
            (b + 3, b + 0, b + 4, b + 7),
        ]
    return verts, faces, expected


@unittest.skipUnless(utils.kernel_available(), "未构建 Rust 内核扩展（lowcheck_core.pyd）")
class TestRustParity(unittest.TestCase):
    """两条实现必须给出逐点一致的结果。"""

    def test_collinear_matches_python(self):
        verts, faces, expected = _split_edge_cubes(7, 6)
        bm, obj, mesh = _to_bmesh("parity_collinear", verts, faces)
        try:
            kernel = list(utils.get_collinear_vertices(bm, 0.01))
            pure = list(utils._collinear_vertices_py(bm, 0.01))
            self.assertEqual(kernel, pure)
            self.assertEqual(kernel, expected)
        finally:
            _cleanup(bm, obj, mesh)

    def test_unwelded_matches_python(self):
        rng = random.Random(11)
        verts = []
        for i in range(12):
            base = (rng.uniform(-1.0, 1.0), rng.uniform(-1.0, 1.0), rng.uniform(-1.0, 1.0))
            verts.append(base)
            if i % 3 == 0:
                # 制造近似重合点（距离 < 0.001）
                verts.append((base[0] + 0.0004, base[1] + 0.0002, base[2]))
        faces = []
        for i in range(0, len(verts) - 2, 3):
            faces.append((i, i + 1, i + 2))
        bm, obj, mesh = _to_bmesh("parity_unwelded", verts, faces)
        try:
            self.assertEqual(list(utils.get_unwelded_vertices(bm, 0.001)),
                             list(utils._unwelded_vertices_py(bm, 0.001)))
        finally:
            _cleanup(bm, obj, mesh)

    def test_dense_matches_python(self):
        rng = random.Random(23)
        verts = []
        for _ in range(4):
            cx, cy, cz = (rng.uniform(-2.0, 2.0) for _ in range(3))
            for _ in range(6):
                verts.append((cx + rng.uniform(-0.02, 0.02),
                              cy + rng.uniform(-0.02, 0.02),
                              cz + rng.uniform(-0.02, 0.02)))
        verts += [(20.0, 0.0, 0.0), (21.0, 0.0, 0.0), (20.0, 1.0, 0.0)]
        faces = []
        for i in range(0, len(verts) - 2, 3):
            faces.append((i, i + 1, i + 2))
        bm, obj, mesh = _to_bmesh("parity_dense", verts, faces)
        try:
            self.assertEqual(list(utils.get_dense_vertices(bm, 0.1, 5)),
                             list(utils._dense_vertices_py(bm, 0.1, 5)))
        finally:
            _cleanup(bm, obj, mesh)

    def test_random_meshes_do_not_false_positive(self):
        for seed in range(6):
            rng = random.Random(seed)
            verts = [(rng.uniform(-3.0, 3.0), rng.uniform(-3.0, 3.0),
                      rng.uniform(-3.0, 3.0)) for _ in range(24)]
            faces = [(i, i + 1, i + 2) for i in range(0, 21, 3)]
            bm, obj, mesh = _to_bmesh(f"parity_rand_{seed}", verts, faces)
            try:
                self.assertEqual(list(utils.get_collinear_vertices(bm, 0.01)),
                                 list(utils._collinear_vertices_py(bm, 0.01)))
                self.assertEqual(list(utils.get_unwelded_vertices(bm, 0.001)),
                                 list(utils._unwelded_vertices_py(bm, 0.001)))
            finally:
                _cleanup(bm, obj, mesh)


if __name__ == "__main__":
    unittest.main(verbosity=2)
