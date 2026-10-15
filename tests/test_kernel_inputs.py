"""
``kernel_inputs()`` 批量取数的测试

覆盖点：
  1. **顶点顺序契约**（最重要）：``obj.data`` 的顶点顺序必须与 ``bm.verts``
     一致。这是 ``foreach_get`` 能用的前提，而它是个**隐含契约**——一旦
     ``_build_bmesh`` 改成 ``bmesh.from_object``（应用 modifier），顺序可能
     变化，届时批量取数会**静默错位**、检测结果全部偏移而不报错。
     本测试把该契约变成显式断言。
  2. **数据等价性**：``kernel_inputs(obj, bm)`` 与 ``_vertex_kernel_inputs(bm)``
     产出的 points / edges / boundary 必须逐项相同。
  3. **回退路径**：``obj=None`` 或 ``foreach_get`` 抛异常时，必须静默回退到
     Python 摊平且数据仍正确。

运行方式:
    blender --background --factory-startup --python-exit-code 1 --python tests/run_tests.py
"""

import os
import sys
import unittest

import bmesh
import bpy

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from Blender_LowCheck import utils  # noqa: E402


def _make_grid(n=4, jitter=False):
    """构造 (n+1)x(n+1) 的四边形网格，返回 (obj, mesh, bm)"""
    verts, faces = [], []
    for i in range(n + 1):
        for j in range(n + 1):
            z = ((i * 7 + j * 13) % 11) * 0.01 if jitter else 0.0
            verts.append((float(i), float(j), z))
    for i in range(n):
        for j in range(n):
            a = i * (n + 1) + j
            faces.append((a, a + 1, a + n + 2, a + n + 1))
    mesh = bpy.data.meshes.new('ki_probe')
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new('ki_probe', mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    return obj, mesh, bm


class TestVertexOrderContract(unittest.TestCase):
    """守卫 foreach_get 的隐含前提：mesh 与 bmesh 的顶点顺序一致"""

    def setUp(self):
        self._owned = []

    def tearDown(self):
        for obj, mesh, bm in self._owned:
            bm.free()
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.meshes.remove(mesh)

    def test_mesh_and_bmesh_share_vertex_order(self):
        obj, mesh, bm = _make_grid(n=4, jitter=True)
        self._owned.append((obj, mesh, bm))

        self.assertEqual(len(bm.verts), len(mesh.vertices),
                         "bm.verts 与 mesh.vertices 数量不一致")
        for i, vert in enumerate(bm.verts):
            mesh_co = tuple(round(c, 9) for c in mesh.vertices[i].co)
            bm_co = tuple(round(c, 9) for c in vert.co)
            self.assertEqual(
                bm_co, mesh_co,
                f"第 {i} 个顶点坐标不一致：bm={bm_co} mesh={mesh_co}。"
                f"foreach_get 依赖顶点顺序一致，此处若失败说明 _build_bmesh "
                f"的构建方式变了，批量取数会静默错位",
            )

    def test_mesh_and_bmesh_share_edge_order(self):
        obj, mesh, bm = _make_grid(n=4, jitter=True)
        self._owned.append((obj, mesh, bm))

        self.assertEqual(len(bm.edges), len(mesh.edges))
        for i, edge in enumerate(bm.edges):
            got = (edge.verts[0].index, edge.verts[1].index)
            want = tuple(mesh.edges[i].vertices)
            self.assertEqual(
                sorted(got), sorted(want),
                f"第 {i} 条边的顶点对不一致：bm={got} mesh={want}",
            )


class TestKernelInputsEquivalence(unittest.TestCase):
    """批量取数与 Python 摊平的数据必须逐项相同"""

    def setUp(self):
        self._owned = []

    def tearDown(self):
        for obj, mesh, bm in self._owned:
            bm.free()
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.meshes.remove(mesh)

    def test_batch_and_manual_produce_identical_data(self):
        obj, mesh, bm = _make_grid(n=6, jitter=True)
        self._owned.append((obj, mesh, bm))

        batch = utils.kernel_inputs(obj, bm)
        manual = utils._vertex_kernel_inputs(bm)

        self.assertEqual(len(batch), 3)
        points_b, edges_b, boundary_b = batch
        points_m, edges_m, boundary_m = manual

        self.assertEqual(list(points_b), points_m, "points 不一致")
        self.assertEqual(list(edges_b), edges_m, "edges 不一致")
        self.assertEqual(list(boundary_b), boundary_m, "boundary 不一致")

    def test_kernel_detection_results_identical(self):
        """走批量取数路径与走 Python 摊平路径，检测结果必须一致"""
        obj, mesh, bm = _make_grid(n=6, jitter=True)
        self._owned.append((obj, mesh, bm))

        for label, kwargs in (
            ("collinear", {}),
            ("unwelded", {"threshold": 0.001}),
            ("dense", {"distance_threshold": 0.1, "count_threshold": 5}),
        ):
            fn = getattr(utils, f"get_{label}_vertices")
            with_obj = fn(bm, obj=obj, **kwargs)
            without_obj = fn(bm, obj=None, **kwargs)
            self.assertEqual(
                sorted(with_obj), sorted(without_obj),
                f"{label} 检测结果因取数路径不同而不一致",
            )


class _NoForeachCollection:
    """故意缺少 ``foreach_get`` 的假顶点/边集合。

    Blender 的 ``bpy_prop_collection`` 是不可变类型，无法用 mock 打补丁，
    所以改用「属性缺失」来触发 :func:`utils.kernel_inputs` 内部的
    AttributeError，从而验证回退路径。
    """

    def __len__(self):
        return 4


class _FakeMesh:
    vertices = _NoForeachCollection()
    edges = _NoForeachCollection()


class _FakeObj:
    data = _FakeMesh()


class TestKernelInputsFallback(unittest.TestCase):
    """回退路径：obj 缺失或 foreach_get 失败时仍须正确"""

    def setUp(self):
        self._owned = []

    def tearDown(self):
        for obj, mesh, bm in self._owned:
            bm.free()
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.meshes.remove(mesh)

    def test_falls_back_when_obj_is_none(self):
        obj, mesh, bm = _make_grid(n=4)
        self._owned.append((obj, mesh, bm))

        points, edges, boundary = utils.kernel_inputs(None, bm)
        manual_p, manual_e, manual_b = utils._vertex_kernel_inputs(bm)

        self.assertEqual(list(points), manual_p)
        self.assertEqual(list(edges), manual_e)
        self.assertEqual(list(boundary), manual_b)

    def test_falls_back_when_obj_has_no_data(self):
        obj, mesh, bm = _make_grid(n=4)
        self._owned.append((obj, mesh, bm))

        points, edges, _boundary = utils.kernel_inputs(object(), bm)
        manual_p, manual_e, _ = utils._vertex_kernel_inputs(bm)
        self.assertEqual(list(points), manual_p)
        self.assertEqual(list(edges), manual_e)

    def test_falls_back_when_foreach_is_unavailable(self):
        """mesh 缺少 foreach_get 时必须静默回退，而不是把异常抛给调用方"""
        obj, mesh, bm = _make_grid(n=4)
        self._owned.append((obj, mesh, bm))

        points, edges, boundary = utils.kernel_inputs(_FakeObj(), bm)

        manual_p, manual_e, manual_b = utils._vertex_kernel_inputs(bm)
        self.assertEqual(list(points), manual_p, "回退后 points 不正确")
        self.assertEqual(list(edges), manual_e, "回退后 edges 不正确")
        self.assertEqual(list(boundary), manual_b, "回退后 boundary 不正确")

    def test_raises_without_bmesh(self):
        with self.assertRaises(ValueError):
            utils.kernel_inputs(obj=None, bm=None)


class TestKernelInputsSessionCache(unittest.TestCase):
    """会话内缓存：同一物体在一次批处理里只摊平一次"""

    def setUp(self):
        self._owned = []

    def tearDown(self):
        for obj, mesh, bm in self._owned:
            bm.free()
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.meshes.remove(mesh)

    def _make(self, name, n=6):
        obj, mesh, bm = _make_grid(n=n, jitter=True)
        self._owned.append((obj, mesh, bm))
        return obj, mesh, bm

    def test_session_returns_same_object_on_second_call(self):
        """会话内第二次调用应命中缓存——用 is 断言直接证明「没重算」"""
        obj, _mesh, bm = self._make('cache_hit')

        with utils.detection_session():
            first = utils.kernel_inputs(obj, bm)
            second = utils.kernel_inputs(obj, bm)

        self.assertIs(first, second,
                      "会话内第二次调用返回了不同对象，说明缓存未生效")

    def test_cache_is_per_object(self):
        """不同物体必须各有自己的缓存，不能互相串用"""
        obj_a, _m_a, bm_a = self._make('cache_a', n=5)
        obj_b, _m_b, bm_b = self._make('cache_b', n=7)

        with utils.detection_session():
            inputs_a = utils.kernel_inputs(obj_a, bm_a)
            inputs_b = utils.kernel_inputs(obj_b, bm_b)
            inputs_a2 = utils.kernel_inputs(obj_a, bm_a)

        self.assertIs(inputs_a, inputs_a2, "物体 A 的缓存未生效")
        self.assertIsNot(inputs_a, inputs_b, "物体 A 与 B 的缓存串了")

    def test_cache_data_is_still_correct(self):
        """命中缓存返回的数据必须与手动摊平一致"""
        obj, _mesh, bm = self._make('cache_correct', n=6)

        with utils.detection_session():
            utils.kernel_inputs(obj, bm)               # 第一次：填充缓存
            cached_again = utils.kernel_inputs(obj, bm)  # 第二次：命中

        manual = utils._vertex_kernel_inputs(bm)
        for got, want in zip(cached_again, manual):
            self.assertEqual(list(got), want)

    def test_no_cache_outside_session(self):
        """会话外不应缓存——每次都重新摊平（返回新对象）"""
        obj, _mesh, bm = self._make('no_cache', n=4)

        first = utils.kernel_inputs(obj, bm)
        second = utils.kernel_inputs(obj, bm)

        self.assertIsNot(first, second,
                         "会话外也返回了同一对象，说明缓存泄漏到了会话外")

    def test_detection_results_unchanged_with_cache(self):
        """开了缓存之后，三个内核检测的结果必须与不开缓存时一致"""
        obj, _mesh, bm = self._make('cache_results', n=6)

        results_no_session = {
            label: sorted(fn(bm, obj=obj))
            for label, fn in (
                ("collinear", utils.get_collinear_vertices),
                ("unwelded", utils.get_unwelded_vertices),
                ("dense", utils.get_dense_vertices),
            )
        }

        with utils.detection_session():
            # 同一物体跑三遍，命中缓存的应是后两次
            results_with_session = {}
            for label, fn in (
                ("collinear", utils.get_collinear_vertices),
                ("unwelded", utils.get_unwelded_vertices),
                ("dense", utils.get_dense_vertices),
            ):
                results_with_session[label] = sorted(fn(bm, obj=obj))
                results_with_session[label + "_again"] = sorted(fn(bm, obj=obj))

        self.assertEqual(results_no_session["collinear"],
                         results_with_session["collinear"])
        self.assertEqual(results_no_session["unwelded"],
                         results_with_session["unwelded"])
        self.assertEqual(results_no_session["dense"],
                         results_with_session["dense"])
        self.assertEqual(results_with_session["collinear"],
                         results_with_session["collinear_again"])


if __name__ == "__main__":
    unittest.main(verbosity=2, argv=[""])
