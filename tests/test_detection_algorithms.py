"""
检测算法单元测试

覆盖各检测函数在正常/异常输入下的行为，以及本次改进引入的
关键修复（未焊接点量化漏检、法线翻转误报、BMesh 会话复用等）。

运行方式:
    blender --background --factory-startup --python-exit-code 1 --python tests/run_tests.py
"""

import math
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


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def make_bmesh(name, verts, faces=None, edges=None):
    """创建测试用 mesh 并返回 (bmesh, obj, mesh)"""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, edges or [], faces or [])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    return bm, obj, mesh


def drop(bm, obj, mesh):
    bm.free()
    if obj.name in bpy.data.objects:
        bpy.data.objects.remove(obj, do_unlink=True)
    if mesh.name in bpy.data.meshes:
        bpy.data.meshes.remove(mesh)


# ---------------------------------------------------------------------------
# 未焊接点检测
# ---------------------------------------------------------------------------

class TestUnweldedVertices(unittest.TestCase):
    """未焊接点检测（KDTree 版本）"""

    def test_detects_coincident_unconnected_verts(self):
        bm, obj, mesh = make_bmesh("Unwelded", [
            # 面 A
            (0.0, 0, 0), (1, 0, 0), (1, 1, 0),
            # 面 B（第一个顶点与面 A 的第一个顶点位置几乎重合）
            (0.002, 0, 0), (2, 0, 0), (2, 1, 0),
        ], [(0, 1, 2), (3, 4, 5)])
        result = utils.get_unwelded_vertices(bm, 0.01)
        self.assertEqual(result, [0, 3])
        drop(bm, obj, mesh)

    def test_regression_quantization_boundary(self):
        """
        回归测试：旧实现按「量化坐标分桶」分组，两点若恰好落在相邻
        格子交界两侧会被漏检。KDTree 方案应稳定检出。
        """
        bm, obj, mesh = make_bmesh("QuantBoundary", [
            (0.049, 0, 0), (1, 0, 0), (1, 1, 0),
            (0.051, 0, 0), (3, 0, 0), (3, 1, 0),
        ], [(0, 1, 2), (3, 4, 5)])
        result = utils.get_unwelded_vertices(bm, 0.1)
        self.assertIn(0, result, "位于量化边界两侧的重合点被漏检")
        self.assertIn(3, result)
        drop(bm, obj, mesh)

    def test_welded_verts_are_not_reported(self):
        """由边直接相连的顶点不应被判定为未焊接"""
        bm, obj, mesh = make_bmesh("Welded", [
            (0, 0, 0), (1, 0, 0), (0, 1, 0),
        ], [(0, 1, 2)])
        self.assertEqual(utils.get_unwelded_vertices(bm, 0.01), [])
        drop(bm, obj, mesh)

    def test_zero_threshold_returns_empty(self):
        """阈值 <= 0 时安全返回空列表（不会除零）"""
        bm, obj, mesh = make_bmesh("ZeroThresh", [
            (0, 0, 0), (0, 0, 0), (1, 1, 0),
        ], [(0, 1, 2)])
        self.assertEqual(utils.get_unwelded_vertices(bm, 0.0), [])
        self.assertEqual(utils.get_unwelded_vertices(bm, -1.0), [])
        drop(bm, obj, mesh)

    def test_empty_mesh(self):
        bm = bmesh.new()
        self.assertEqual(utils.get_unwelded_vertices(bm, 0.01), [])
        bm.free()


# ---------------------------------------------------------------------------
# 退化几何体
# ---------------------------------------------------------------------------

class TestDegenerateGeometry(unittest.TestCase):

    def test_zero_length_edge(self):
        bm, obj, mesh = make_bmesh("ZeroEdge", [
            (0, 0, 0), (1, 0, 0), (1, 0, 0), (0, 1, 0),
        ], [(0, 1, 2, 3)])
        edges = utils.get_zero_length_edges(bm, 0.0001)
        self.assertEqual(len(edges), 1)
        drop(bm, obj, mesh)

    def test_zero_area_face(self):
        bm, obj, mesh = make_bmesh("ZeroArea", [
            (0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0),
        ], [(0, 1, 2, 3)])
        faces = utils.get_zero_area_faces(bm, 0.0001)
        self.assertEqual(faces, [0])
        drop(bm, obj, mesh)

    def test_normal_face_not_degenerate(self):
        bm, obj, mesh = make_bmesh("NormalQuad", [
            (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
        ], [(0, 1, 2, 3)])
        self.assertEqual(utils.get_zero_length_edges(bm, 0.0001), [])
        self.assertEqual(utils.get_zero_area_faces(bm, 0.0001), [])
        drop(bm, obj, mesh)


# ---------------------------------------------------------------------------
# 拓扑问题
# ---------------------------------------------------------------------------

class TestTopologyChecks(unittest.TestCase):

    def test_non_manifold_edge(self):
        bm, obj, mesh = make_bmesh("NonManifold", [
            (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1),
        ], [(0, 1, 2), (1, 0, 3), (0, 1, 4)])
        self.assertEqual(len(utils.get_non_manifold_edges(bm)), 1)
        drop(bm, obj, mesh)

    def test_manifold_cube_has_no_non_manifold_edges(self):
        bm, obj, mesh = make_bmesh("Cube", *CUBE_DATA)
        self.assertEqual(utils.get_non_manifold_edges(bm), [])
        drop(bm, obj, mesh)

    def test_loose_geometry(self):
        bm, obj, mesh = make_bmesh("Loose", [
            (0, 0, 0), (1, 0, 0), (2, 0, 0),
            (3, 0, 0), (4, 0, 0), (4, 1, 0), (3, 1, 0),
        ], [(3, 4, 5, 6)], edges=[(0, 1)])
        loose_verts, loose_edges = utils.get_loose_geometry(bm)
        self.assertEqual(sorted(loose_verts), [0, 1, 2])
        self.assertEqual(len(loose_edges), 1)
        drop(bm, obj, mesh)

    def test_overlapping_faces(self):
        quad = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
        bm, obj, mesh = make_bmesh("Overlap", quad + quad,
                                   [(0, 1, 2, 3), (4, 5, 6, 7)])
        self.assertEqual(sorted(utils.get_faces_sharing_all_edges(bm)), [0, 1])
        drop(bm, obj, mesh)

    def test_overlapping_faces_zero_threshold(self):
        """阈值为 0 时不应除零崩溃"""
        quad = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
        bm, obj, mesh = make_bmesh("OverlapZero", quad,
                                   [(0, 1, 2, 3)])
        self.assertEqual(utils.get_faces_sharing_all_edges(bm, 0.0), [])
        drop(bm, obj, mesh)


# ---------------------------------------------------------------------------
# 法线方向
# ---------------------------------------------------------------------------

CUBE_VERTS = [
    (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
    (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
]
# 朝外的面（顺序即绕序）
CUBE_FACES = [
    (0, 3, 2, 1),  # 底 (-Z)
    (4, 5, 6, 7),  # 顶 (+Z)
    (0, 1, 5, 4),  # 前 (-Y)
    (1, 2, 6, 5),  # 右 (+X)
    (2, 3, 7, 6),  # 后 (+Y)
    (3, 0, 4, 7),  # 左 (-X)
]
CUBE_DATA = (CUBE_VERTS, CUBE_FACES)


class TestWrongNormals(unittest.TestCase):

    def test_consistent_cube_has_no_wrong_normals(self):
        bm, obj, mesh = make_bmesh("CubeOK", *CUBE_DATA)
        self.assertEqual(utils.get_wrong_normal_faces(bm), [])
        drop(bm, obj, mesh)

    def test_single_flipped_face_is_detected(self):
        """旧算法会因法线相互抵消而漏检，新算法应稳定检出"""
        faces = list(CUBE_FACES)
        faces[1] = (4, 7, 6, 5)  # 翻转顶面
        bm, obj, mesh = make_bmesh("CubeFlipped", CUBE_VERTS, faces)
        self.assertEqual(utils.get_wrong_normal_faces(bm), [1])
        drop(bm, obj, mesh)

    def test_fully_inverted_cube_is_detected(self):
        """整体朝内的闭合体：应报告全部面"""
        faces = [tuple(reversed(face)) for face in CUBE_FACES]
        bm, obj, mesh = make_bmesh("CubeInverted", CUBE_VERTS, faces)
        self.assertEqual(sorted(utils.get_wrong_normal_faces(bm)), [0, 1, 2, 3, 4, 5])
        drop(bm, obj, mesh)

    def test_two_flipped_faces(self):
        faces = list(CUBE_FACES)
        faces[0] = (0, 1, 2, 3)
        faces[3] = (1, 5, 6, 2)
        bm, obj, mesh = make_bmesh("CubeFlipped2", CUBE_VERTS, faces)
        self.assertEqual(sorted(utils.get_wrong_normal_faces(bm)), [0, 3])
        drop(bm, obj, mesh)

    def test_non_manifold_fin_no_false_positive(self):
        """非流形边上的绕序无明确定义，不应误报"""
        bm, obj, mesh = make_bmesh("Fin", [
            (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1),
        ], [(0, 1, 2), (1, 0, 3), (0, 1, 4)])
        self.assertEqual(utils.get_wrong_normal_faces(bm), [])
        drop(bm, obj, mesh)

    def test_signed_volume_of_outward_cube_is_positive(self):
        bm, obj, mesh = make_bmesh("CubeVolume", *CUBE_DATA)
        volume = utils._signed_volume(list(bm.faces), set())
        self.assertAlmostEqual(volume, 1.0, places=6)
        drop(bm, obj, mesh)


# ---------------------------------------------------------------------------
# 场景级检测
# ---------------------------------------------------------------------------

class TestSceneChecks(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def test_get_target_mesh_objects_excludes_non_mesh(self):
        camera_data = bpy.data.cameras.new("Cam")
        camera = bpy.data.objects.new("Cam", camera_data)
        bpy.context.scene.collection.objects.link(camera)

        _, obj, mesh = make_bmesh("MeshOnly", [
            (0, 0, 0), (1, 0, 0), (0, 1, 0),
        ], [(0, 1, 2)])
        try:
            found = utils.get_target_mesh_objects(bpy.context)
            self.assertIn(obj, found)
            self.assertNotIn(camera, found)
        finally:
            drop(bmesh.new(), obj, mesh)
            bpy.data.objects.remove(camera, do_unlink=True)
            bpy.data.cameras.remove(camera_data)

    def test_non_uniform_scale_detection(self):
        _, obj, mesh = make_bmesh("Scaled", [
            (0, 0, 0), (1, 0, 0), (0, 1, 0),
        ], [(0, 1, 2)])
        try:
            self.assertEqual(utils.get_non_uniform_scale_objects(bpy.context), [])
            obj.scale = (2.0, 1.0, 1.0)
            self.assertIn(obj, utils.get_non_uniform_scale_objects(bpy.context))
        finally:
            drop(bmesh.new(), obj, mesh)

    def test_intersecting_objects_skips_empty_meshes(self):
        """空网格的包围盒退化在原点，不应被判定为互相穿插"""
        empty_meshes = []
        for name in ("EmptyA", "EmptyB"):
            mesh = bpy.data.meshes.new(name)
            obj = bpy.data.objects.new(name, mesh)
            bpy.context.scene.collection.objects.link(obj)
            empty_meshes.append((obj, mesh))
        try:
            result = utils.get_intersecting_objects(bpy.context, 0.0)
            for obj, _mesh in empty_meshes:
                self.assertNotIn(obj, result)
        finally:
            for obj, mesh in empty_meshes:
                bpy.data.objects.remove(obj, do_unlink=True)
                bpy.data.meshes.remove(mesh)


# ---------------------------------------------------------------------------
# 朝下水平面：世界空间判定
# ---------------------------------------------------------------------------

class TestDownwardFacesWorldSpace(unittest.TestCase):
    """朝下水平面必须按**世界空间**法线判定。

    回归：旧实现直接使用 BMesh 的局部空间法线，物体一旦旋转就会同时
    产生漏检与误报。立方体绕 X 轴旋转 90° 后，世界空间朝下的是面 2
    （世界法线 (0, 0, -1)），而面 0 的世界法线已变成 (0, 1, 0)。
    """

    #: 单位立方体，外法线朝外
    CUBE_VERTS = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                  (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    CUBE_FACES = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                  (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]

    def test_unrotated_object_matches_local_space(self):
        bm, obj, mesh = make_bmesh("down_flat", self.CUBE_VERTS, self.CUBE_FACES)
        try:
            bpy.context.view_layer.update()
            found = utils.get_downward_faces(bm, 0.0, 5.0, matrix_world=obj.matrix_world)
            self.assertEqual(found, [0])
        finally:
            drop(bm, obj, mesh)

    def test_rotated_object_reports_world_downward_face(self):
        bm, obj, mesh = make_bmesh("down_rotated", self.CUBE_VERTS, self.CUBE_FACES)
        try:
            obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
            bpy.context.view_layer.update()
            found = utils.get_downward_faces(bm, 0.0, 5.0, matrix_world=obj.matrix_world)
            self.assertEqual(found, [2])
        finally:
            drop(bm, obj, mesh)

    def test_local_space_normals_miss_the_world_downward_face(self):
        """同一网格不传 matrix_world 时会漏掉真正朝下的面（说明该参数不可省）"""
        bm, obj, mesh = make_bmesh("down_rotated_local", self.CUBE_VERTS, self.CUBE_FACES)
        try:
            obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
            bpy.context.view_layer.update()
            self.assertNotIn(2, utils.get_downward_faces(bm, 0.0, 5.0))
        finally:
            drop(bm, obj, mesh)

    def test_uniform_scale_does_not_change_result(self):
        bm, obj, mesh = make_bmesh("down_scaled", self.CUBE_VERTS, self.CUBE_FACES)
        try:
            obj.scale = (3.0, 3.0, 3.0)
            bpy.context.view_layer.update()
            found = utils.get_downward_faces(bm, 0.0, 5.0, matrix_world=obj.matrix_world)
            self.assertEqual(found, [0])
        finally:
            drop(bm, obj, mesh)

    def test_area_threshold_uses_world_space_area(self):
        """面积阈值按世界空间面积比较：均匀放大 3 倍后面积为 9 倍"""
        bm, obj, mesh = make_bmesh("down_area_uniform", self.CUBE_VERTS, self.CUBE_FACES)
        try:
            obj.scale = (3.0, 3.0, 3.0)
            bpy.context.view_layer.update()
            # 底面局部面积 = 2*2 = 4；世界面积 = 4 * 3² = 36
            self.assertEqual(utils.get_downward_faces(bm, 30.0, 5.0), [])
            self.assertEqual(
                utils.get_downward_faces(bm, 30.0, 5.0, matrix_world=obj.matrix_world),
                [0],
            )
        finally:
            drop(bm, obj, mesh)

    def test_area_threshold_uses_world_space_area_non_uniform(self):
        """非均匀缩放：只在 X 方向放大 3 倍时，底面世界面积为 4 * 3 = 12"""
        bm, obj, mesh = make_bmesh("down_area_scaled_x", self.CUBE_VERTS, self.CUBE_FACES)
        try:
            obj.scale = (3.0, 1.0, 1.0)
            bpy.context.view_layer.update()
            self.assertEqual(utils.get_downward_faces(bm, 10.0, 5.0), [])
            self.assertEqual(
                utils.get_downward_faces(bm, 10.0, 5.0, matrix_world=obj.matrix_world),
                [0],
            )
        finally:
            drop(bm, obj, mesh)


# ---------------------------------------------------------------------------
# BMesh 会话复用
# ---------------------------------------------------------------------------

class TestBMeshSession(unittest.TestCase):

    def test_session_reuses_bmesh(self):
        _, obj, mesh = make_bmesh("SessionMesh", *CUBE_DATA)
        try:
            with utils.detection_session():
                with utils.bmesh_from_object(obj) as bm1:
                    with utils.bmesh_from_object(obj) as bm2:
                        self.assertIs(bm1, bm2, "同一物体在会话中应复用 BMesh")
        finally:
            drop(bmesh.new(), obj, mesh)

    def test_without_session_creates_new_bmesh(self):
        _, obj, mesh = make_bmesh("NoSessionMesh", *CUBE_DATA)
        try:
            with utils.bmesh_from_object(obj) as bm1:
                pass
            with utils.bmesh_from_object(obj) as bm2:
                self.assertIsNot(bm1, bm2, "未开启会话时不应复用 BMesh")
        finally:
            drop(bmesh.new(), obj, mesh)

    def test_session_releases_resources(self):
        _, obj, mesh = make_bmesh("ReleaseMesh", *CUBE_DATA)
        try:
            with utils.detection_session() as session:
                with utils.bmesh_from_object(obj) as bm:
                    self.assertEqual(len(bm.faces), 6)
                self.assertEqual(len(session._cache), 1)
            self.assertEqual(len(session._cache), 0, "会话结束后应释放全部 BMesh")
        finally:
            drop(bmesh.new(), obj, mesh)

    def test_bmesh_indices_match_mesh_indices(self):
        """会话中 BMesh 的元素索引必须与 mesh 索引一致（选择功能依赖此约定）"""
        _, obj, mesh = make_bmesh("IndexMesh", *CUBE_DATA)
        try:
            with utils.detection_session():
                with utils.bmesh_from_object(obj) as bm:
                    for i, face in enumerate(bm.faces):
                        self.assertEqual(face.index, i)
        finally:
            drop(bmesh.new(), obj, mesh)


# ---------------------------------------------------------------------------
# 健壮性辅助
# ---------------------------------------------------------------------------

class TestRobustnessHelpers(unittest.TestCase):

    def test_is_object_alive_true(self):
        _, obj, mesh = make_bmesh("AliveMesh", *CUBE_DATA)
        try:
            self.assertTrue(utils.is_object_alive(obj))
        finally:
            drop(bmesh.new(), obj, mesh)

    def test_is_object_alive_false_after_removal(self):
        _, obj, mesh = make_bmesh("DeadMesh", *CUBE_DATA)
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        self.assertFalse(utils.is_object_alive(obj))

    def test_apply_mesh_selection_ignores_out_of_range(self):
        _, obj, mesh = make_bmesh("SelectMesh", *CUBE_DATA)
        try:
            count = utils._apply_mesh_selection(obj, 'FACE', [0, 99, -5])
            self.assertEqual(count, 1)
            self.assertTrue(obj.data.polygons[0].select)
            self.assertEqual(
                sum(1 for polygon in obj.data.polygons if polygon.select), 1
            )
        finally:
            drop(bmesh.new(), obj, mesh)

    def test_apply_selection_skips_dead_objects(self):
        _, obj, mesh = make_bmesh("DeadSelectMesh", *CUBE_DATA)
        # 必须先删物体再删网格：先删网格会让物体引用立即失效
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(mesh, do_unlink=True)

        processed, total, skipped = utils.apply_selection(
            bpy.context, {obj: [0]}, 'FACE'
        )
        self.assertEqual((processed, total, skipped), (0, 0, 1))


# ---------------------------------------------------------------------------
# 退化几何体：结果的元素类型（回归测试）
# ---------------------------------------------------------------------------

class TestDegenerateGeometrySelection(unittest.TestCase):
    """
    退化几何体的结果必须记录正确的元素类型。

    旧实现无论是否存在退化边，都把结果以 ``EDGE`` 类型写入
    （``edge_data or face_data``），当模型只有退化面而没有退化边时，
    面索引会被当作边索引写入选择标志：用户点「选择」看到的是一堆
    无关的边，真正的退化面反而选不中。
    """

    @classmethod
    def setUpClass(cls):
        import Blender_LowCheck

        cls._addon = Blender_LowCheck
        # 记录进入本类之前插件的注册状态，避免误改全局状态
        cls._was_registered = hasattr(bpy.types.Scene, "lowpoly")
        Blender_LowCheck.register()

    @classmethod
    def tearDownClass(cls):
        if not cls._was_registered:
            cls._addon.unregister()

    def setUp(self):
        from Blender_LowCheck.operators import check_operators

        # 隔离：删除其它测试类遗留在场景中的物体，否则它们的退化元素
        # 会被一起统计（检测项遍历场景里全部可见网格物体）
        self.addCleanup(self._remove_created_objects)
        self._created = []
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        check_operators.check_results.clear()

    def _remove_created_objects(self):
        for obj in self._created:
            if obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)

    def _make_mesh_object(self, name, verts, faces):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        self._created.append(obj)
        return obj

    @staticmethod
    def _deselect_all(obj):
        """from_pydata 创建的元素默认处于选中态，先全部清空再验证选择结果"""
        for collection in (obj.data.vertices, obj.data.edges, obj.data.polygons):
            for element in collection:
                element.select = False
        obj.data.update()

    def test_faces_only_result_uses_face_element_type(self):
        """只有退化面（无零长度边）时，结果必须是 FACE 类型"""
        from Blender_LowCheck.operators import check_operators

        # 四个共线顶点构成零面积四边形；所有边长均为 1，不存在退化边
        obj = self._make_mesh_object(
            "DegenerateFaceOnly",
            [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)],
            [(0, 1, 2, 3)],
        )
        self._deselect_all(obj)

        props = bpy.context.scene.lowpoly
        self.assertEqual(bpy.ops.lowpoly.check_degenerate_geometry(), {'FINISHED'})
        self.assertEqual(props.degenerate_edge_count, 0)
        self.assertEqual(props.degenerate_face_count, 1)

        stored = check_operators.check_results.get('degenerate_geometry')
        self.assertIsNotNone(stored, "退化面未被写入检测结果")
        self.assertEqual(
            stored['element_type'], 'FACE',
            "没有退化边时必须以 FACE 类型记录，否则面索引会被当成边索引",
        )

        self.assertEqual(bpy.ops.lowpoly.select_degenerate_geometry(), {'FINISHED'})
        self.assertEqual(
            [i for i, polygon in enumerate(obj.data.polygons) if polygon.select],
            [0],
            "退化面未被选中",
        )
        self.assertEqual(
            [edge.index for edge in obj.data.edges if edge.select], [],
            "退化面的索引被错误地当作边索引使用",
        )

    def test_edges_present_result_uses_edge_element_type(self):
        """存在退化边时仍以 EDGE 类型记录，并选中该退化边"""
        from Blender_LowCheck.operators import check_operators

        # 顶点 1、2 位置重合 → 零长度边
        obj = self._make_mesh_object(
            "DegenerateEdge",
            [(0, 0, 0), (1, 0, 0), (1, 0, 0), (2, 0, 0)],
            [(0, 1, 2, 3)],
        )
        self._deselect_all(obj)

        props = bpy.context.scene.lowpoly
        self.assertEqual(bpy.ops.lowpoly.check_degenerate_geometry(), {'FINISHED'})
        self.assertEqual(props.degenerate_edge_count, 1)

        stored = check_operators.check_results.get('degenerate_geometry')
        self.assertIsNotNone(stored)
        self.assertEqual(stored['element_type'], 'EDGE')

        self.assertEqual(bpy.ops.lowpoly.select_degenerate_geometry(), {'FINISHED'})
        selected = [edge.index for edge in obj.data.edges if edge.select]
        self.assertEqual(len(selected), 1, f"应恰好选中 1 条退化边，实际 {selected}")
        edge = obj.data.edges[selected[0]]
        start = obj.data.vertices[edge.vertices[0]].co
        end = obj.data.vertices[edge.vertices[1]].co
        self.assertLess((start - end).length, 1e-6, "选中的不是零长度边")


# ---------------------------------------------------------------------------
# 批处理流水线的进度条（回归测试）
# ---------------------------------------------------------------------------

class TestRunPipelineProgress(unittest.TestCase):
    """run_pipeline 的进度条必须成对 begin/end，异常路径也要结束"""

    def test_progress_end_called_when_update_fails(self):
        from Blender_LowCheck.operators.base import run_pipeline

        events = []

        class FakeWindowManager:
            def progress_begin(self, _min, _max):
                events.append("begin")

            def progress_update(self, _value):
                events.append("update")
                raise RuntimeError("进度条不可用")

            def progress_end(self):
                events.append("end")

        class FakeContext:
            window_manager = FakeWindowManager()

        def check_fn(_context):
            events.append("check")

        failed = run_pipeline(FakeContext(), [("项目", check_fn)])

        self.assertEqual(failed, [])
        self.assertIn("check", events, "进度条失败不应阻止检测项执行")
        self.assertEqual(events.count("begin"), 1)
        self.assertEqual(
            events.count("end"), 1,
            "progress_begin 成功后必须调用 progress_end，否则进度条会一直留在界面上",
        )


# ---------------------------------------------------------------------------
# 共线顶点阈值（回归测试：线性近似导致的灵敏度偏差）
# ---------------------------------------------------------------------------

class TestCollinearThreshold(unittest.TestCase):
    """
    共线阈值必须严格按「允许偏离直线的最大弧度」解释。

    旧实现用 ``|cos θ| > 1 - threshold``。由于 ``cos(α) ≈ 1 - α²/2`` 只在
    α→0 时成立，该线性近似远比声明宽松：``threshold = 0.01`` 时实际等价于
    8.11°，而文档承诺 0.01 rad = 0.573°，灵敏度相差约 14 倍；
    ``threshold`` 接近 1.57 时判据甚至恒真。
    """

    @staticmethod
    def _make_pillow(apex_offset):
        """
        构造「枕头」网格：两片反向绕序的重合四边形。

        这样每条边都被 2 个面共用，四个顶点都是**内部顶点**（非边界）
        且度数为 2 —— 正是共线检测的处理对象。
        """
        verts = [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (2.0, apex_offset, 0.0),
            (2.0, 1.0 + apex_offset, 0.0),
        ]
        return make_bmesh("CollinearPillow", verts, [(0, 1, 2, 3), (3, 2, 1, 0)])

    def _collinear_verts(self, apex_offset, threshold):
        bm, obj, mesh = self._make_pillow(apex_offset)
        try:
            return utils.get_collinear_vertices(bm, threshold)
        finally:
            drop(bm, obj, mesh)

    def test_exactly_collinear_vertex_is_detected(self):
        """严格共线的中间顶点必须被检出"""
        self.assertIn(1, self._collinear_verts(0.0, 0.01))

    def test_deviation_within_threshold_is_detected(self):
        """偏离 0.001 rad（远小于阈值 0.01 rad）仍算共线"""
        self.assertIn(1, self._collinear_verts(math.tan(0.001), 0.01))

    def test_deviation_beyond_threshold_is_not_detected(self):
        """
        回归：偏离 2°（0.0349 rad）明显超过阈值 0.01 rad，不得报为共线。

        旧判据等价于 8.11°，会把这种明显有折角的顶点误报为共线。
        """
        offset = math.tan(math.radians(2.0))
        self.assertNotIn(
            1, self._collinear_verts(offset, 0.01),
            "偏离 2° 的顶点被误报为共线（阈值被线性近似放大）",
        )


# ---------------------------------------------------------------------------
# 重叠面检测（回归测试：坐标量化边界漏检）
# ---------------------------------------------------------------------------

class TestOverlappingFacesQuantization(unittest.TestCase):
    """重叠面检测不得因坐标量化网格边界而漏检"""

    def test_regression_quantization_boundary(self):
        """
        0.049 与 0.051 分属相邻量化格（``round(0.49) == 0``、``round(0.51) == 1``），
        旧实现会给它们算出不同的键从而漏检。
        """
        quad_a = [(0.049, 0, 0), (1.049, 0, 0), (1.049, 1, 0), (0.049, 1, 0)]
        quad_b = [(0.051, 0, 0), (1.051, 0, 0), (1.051, 1, 0), (0.051, 1, 0)]
        bm, obj, mesh = make_bmesh(
            "OverlapQuant", quad_a + quad_b, [(0, 1, 2, 3), (4, 5, 6, 7)]
        )
        try:
            self.assertEqual(
                sorted(utils.get_faces_sharing_all_edges(bm, 0.1)), [0, 1],
                "跨量化网格边界的重合面被漏检",
            )
        finally:
            drop(bm, obj, mesh)

    def test_identical_faces_are_detected(self):
        """完全重合的面仍须检出（不得因算法替换而回归）"""
        quad = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
        bm, obj, mesh = make_bmesh(
            "OverlapIdentical", quad + quad, [(0, 1, 2, 3), (4, 5, 6, 7)]
        )
        try:
            self.assertEqual(sorted(utils.get_faces_sharing_all_edges(bm)), [0, 1])
        finally:
            drop(bm, obj, mesh)


# ---------------------------------------------------------------------------
# BMesh 会话：缓存命中必须校验对象身份
# ---------------------------------------------------------------------------

class TestBMeshSessionIdentity(unittest.TestCase):
    """缓存键是对象名；对象名会被新对象复用，因此必须用身份校验兜底"""

    def test_name_reuse_does_not_return_stale_bmesh(self):
        _, obj1, mesh1 = make_bmesh("ReusedName", *CUBE_DATA)

        with utils.detection_session() as session:
            with utils.bmesh_from_object(obj1) as bm1:
                self.assertEqual(len(bm1.faces), 6)
            self.assertEqual(len(session._cache), 1)

            # 删除原对象，让同名对象出现（Blender 允许复用已释放的名字）
            bpy.data.objects.remove(obj1, do_unlink=True)
            bpy.data.meshes.remove(mesh1)

            _, obj2, mesh2 = make_bmesh(
                "ReusedName", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)]
            )
            try:
                with utils.bmesh_from_object(obj2) as bm2:
                    self.assertIsNot(bm2, bm1)
                    self.assertEqual(
                        len(bm2.faces), 1,
                        "同名新对象命中了旧对象的 BMesh 缓存（缓存未校验对象身份）",
                    )
            finally:
                drop(bmesh.new(), obj2, mesh2)


# ---------------------------------------------------------------------------
# 穿插物体检测：结果确定 + 分离物体不误报 + 阈值可过滤
# ---------------------------------------------------------------------------

class TestIntersectingObjects(unittest.TestCase):

    BOX_VERTS = [
        (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
        (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
    ]
    BOX_FACES = [
        (0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    ]

    @classmethod
    def setUpClass(cls):
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def setUp(self):
        self.addCleanup(self._cleanup)
        self._created = []

    def _cleanup(self):
        for obj in self._created:
            mesh = obj.data
            if obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.name in bpy.data.meshes:
                bpy.data.meshes.remove(mesh)

    def _make_box(self, name, x):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(self.BOX_VERTS, [], self.BOX_FACES)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = (x, 0.0, 0.0)
        self._created.append(obj)
        return obj

    def test_separated_boxes_are_not_reported(self):
        self._make_box("BoxFarA", 0.0)
        self._make_box("BoxFarB", 10.0)
        self.assertEqual(utils.get_intersecting_objects(bpy.context, 0.0), [])

    def test_overlapping_boxes_are_reported_deterministically(self):
        near_a = self._make_box("BoxNearA", 0.0)
        near_b = self._make_box("BoxNearB", 0.25)
        far = self._make_box("BoxFar", 50.0)

        result = utils.get_intersecting_objects(bpy.context, 0.0)
        self.assertIn(near_a, result)
        self.assertIn(near_b, result)
        self.assertNotIn(far, result)

        # 结果顺序必须确定（旧实现用 list(set(...)) 去重，顺序随哈希变化）
        self.assertEqual(
            result, utils.get_intersecting_objects(bpy.context, 0.0),
            "穿插检测结果顺序不稳定",
        )

    def test_threshold_filters_shallow_overlap(self):
        """重叠体积占比 0.1 时，阈值 0.5 应把它过滤掉"""
        near_a = self._make_box("BoxShallowA", 0.0)
        self._make_box("BoxShallowB", 0.9)

        self.assertEqual(
            utils.get_intersecting_objects(bpy.context, 0.5), [],
            "高阈值下浅重叠仍被报为穿插",
        )
        self.assertIn(near_a, utils.get_intersecting_objects(bpy.context, 0.0))


if __name__ == "__main__":
    unittest.main(verbosity=2, argv=[sys.argv[0]])
