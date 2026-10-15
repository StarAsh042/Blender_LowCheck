"""
``is_face_concave`` 预计算优化的回归测试

回归点：原实现在判定循环内现算 ``edge1`` / ``edge2``，而第 ``i`` 轮的
``edge2`` 恰是第 ``i+1`` 轮的 ``edge1``——8 次向量减法与 8 次开方里各有一半
是重复计算。改为预计算四条边后，**判定结果必须逐面完全一致**。

本测试用一份「优化前实现的副本」作参照，对随机网格逐面比对。这是唯一能捕获
「优化时顺手改坏了判定逻辑」的手段——若只测几个已知形状，无法排除
「新实现和旧实现错得一样」这种情况。

运行方式:
    blender --background --factory-startup --python-exit-code 1 --python tests/run_tests.py
"""

import os
import random
import sys
import unittest

import bmesh
import bpy

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from Blender_LowCheck import utils  # noqa: E402
from Blender_LowCheck.utils import (  # noqa: E402
    CONCAVITY_TOLERANCE,
    ZERO_THRESHOLD,
)


def _is_valid_vector(vec):
    """优化前 :func:`utils._is_valid_vector` 的副本"""
    return vec.length_squared >= ZERO_THRESHOLD * ZERO_THRESHOLD


def is_face_concave_reference(face):
    """
    **优化前**的 ``is_face_concave`` 实现副本，仅作测试参照，不参与生产。

    与 ``utils.is_face_concave`` 的唯一差异是循环内现算边向量——判定逻辑、
    判据、常量全部一致。
    """
    if len(face.verts) != 4:
        return False

    verts = [v.co for v in face.verts]

    for i in range(4):
        if (verts[i] - verts[(i + 1) % 4]).length_squared < ZERO_THRESHOLD * ZERO_THRESHOLD:
            return False

    prev_sign = 0
    for i in range(4):
        a = verts[i]
        b = verts[(i + 1) % 4]
        c = verts[(i + 2) % 4]

        edge1 = b - a
        edge2 = c - b

        if not _is_valid_vector(edge1) or not _is_valid_vector(edge2):
            return False

        cross = edge1.cross(edge2)
        sin_angle = cross.length / (edge1.length * edge2.length)
        if sin_angle < CONCAVITY_TOLERANCE:
            continue

        cross.normalize()
        dot_with_normal = cross.dot(face.normal)

        if abs(dot_with_normal) < CONCAVITY_TOLERANCE:
            continue

        sign = 1 if dot_with_normal > 0 else -1

        if prev_sign == 0:
            prev_sign = sign
        elif sign != prev_sign:
            return True

    return False


def _make_mesh(name, verts, faces):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj, mesh


def _free(obj, mesh):
    bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.meshes.remove(mesh)


class TestFaceConcaveKnownShapes(unittest.TestCase):
    """已知形状的判定必须正确，防止「两个实现错得一样」"""

    def setUp(self):
        self._owned = []

    def tearDown(self):
        for obj, mesh in self._owned:
            _free(obj, mesh)

    def _quad(self, verts, name='q'):
        obj, mesh = _make_mesh(name, verts, [(0, 1, 2, 3)])
        self._owned.append((obj, mesh))
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        self.addCleanup(bm.free)
        return bm

    def test_convex_square(self):
        bm = self._quad([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)])
        self.assertFalse(utils.is_face_concave(bm.faces[0]))

    def test_concave_dart(self):
        # 顶点 2 落在 (0,0)-(2,0)-(2,2) 构成的三角形内部 → 内角 > 180°
        bm = self._quad([(0, 0, 0), (2, 0, 0), (1.2, 0.5, 0), (2, 2, 0)])
        self.assertTrue(utils.is_face_concave(bm.faces[0]))

    def test_triangle_is_skipped(self):
        obj, mesh = _make_mesh('tri', [(0, 0, 0), (1, 0, 0), (1, 1, 0)], [(0, 1, 2)])
        self._owned.append((obj, mesh))
        bm = bmesh.new()
        self.addCleanup(bm.free)
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        self.assertFalse(utils.is_face_concave(bm.faces[0]))

    def test_degenerate_face_is_skipped(self):
        # 相邻顶点重合（边长 < ZERO_THRESHOLD）→ 直接返回 False
        tiny = ZERO_THRESHOLD * 0.5
        bm = self._quad([(0, 0, 0), (tiny, 0, 0), (1, 0, 0), (1, 1, 0)])
        self.assertFalse(utils.is_face_concave(bm.faces[0]))

    def test_sin_denominator_must_be_both_lengths(self):
        """
        ``sin_angle`` 的分母必须是 ``|e1| * |e2|``，写成 ``|e1| * |e1|`` 会出错。

        本用例**由暴力搜索得到**（2 万个随机四边形中筛出「正确实现判 False、
        错误实现判 True」的样本）。之所以用搜索而非手算：手工构造时容易把
        凹/凸搞错——曾构造出一个凸四边形，两个实现判定相同，测试根本抓不到
        分母写错这类错误（实测可证伪失败过一轮）。

        它与上方的随机比对互为补充：随机样本极少让 ``sin_angle`` 落在
        ``CONCAVITY_TOLERANCE``（0.001）附近，而本用例恰好卡在阈值两侧。
        """
        bm = self._quad([
            (-0.20156, 0.44119, 0.0), (-0.23050, 0.34749, 0.0),
            (-0.37724, -0.12613, 0.0), (0.34019, -0.18398, 0.0),
        ])
        self.assertFalse(utils.is_face_concave(bm.faces[0]))


class TestFaceConcaveMatchesReference(unittest.TestCase):
    """随机网格上逐面与「优化前实现副本」比对（AC6 的核心）"""

    def test_random_quads_match_reference(self):
        rng = random.Random(20261016)

        # 生成 300 个随机四边形：顶点带随机扰动，形状覆盖凸/凹/退化
        mismatches = []
        checked = 0
        concave_found = 0

        for trial in range(300):
            scale = 10.0 ** rng.uniform(-3, 2)      # 跨 5 个数量级，检验尺度无关性
            base = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)]
            verts = []
            for (x, y, z) in base:
                jitter = rng.uniform(-0.45, 0.45)
                verts.append((
                    (x + (jitter if x else 0.0)) * scale,
                    (y + (jitter if y else 0.0)) * scale,
                    rng.uniform(-0.05, 0.05) * scale,
                ))
            # 随机挑一个顶点内缩，制造内凹
            if rng.random() < 0.5:
                idx = rng.randrange(4)
                verts[idx] = (
                    (verts[idx][0] + verts[(idx + 2) % 4][0]) / 2,
                    (verts[idx][1] + verts[(idx + 2) % 4][1]) / 2,
                    verts[idx][2],
                )

            mesh = bpy.data.meshes.new('rand')
            mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
            mesh.update()
            obj = bpy.data.objects.new('rand', mesh)
            bpy.context.collection.objects.link(obj)

            bm = bmesh.new()
            try:
                bm.from_mesh(mesh)
                bm.verts.ensure_lookup_table()
                bm.faces.ensure_lookup_table()
                face = bm.faces[0]
                got = utils.is_face_concave(face)
                want = is_face_concave_reference(face)
                checked += 1
                if got:
                    concave_found += 1
                if got != want:
                    mismatches.append((trial, got, want))
            finally:
                bm.free()
                bpy.data.objects.remove(obj, do_unlink=True)
                bpy.data.meshes.remove(mesh)

        self.assertGreaterEqual(checked, 250, f'实际检查面数过少：{checked}')
        self.assertGreater(concave_found, 20,
                           f'内凹样本过少（{concave_found}），测试可能没覆盖到凹形')
        self.assertEqual(
            mismatches, [],
            f'有 {len(mismatches)} 个面与优化前实现判定不一致，'
            f'前 3 例（trial, 新实现, 参照）：{mismatches[:3]}',
        )


if __name__ == "__main__":
    # Blender 会把自己的命令行参数塞进 sys.argv，unittest.main 会误解析。
    # 传空 argv 让它只跑本文件的用例（默认行为），便于单独调试本文件。
    unittest.main(verbosity=2, argv=[""])
