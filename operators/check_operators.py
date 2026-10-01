"""
检查操作符模块
包含所有错误检查相关的操作符

设计说明:
    所有检测逻辑都拆分为独立的 ``_do_check_*`` 函数，它们：
      * 只依赖 ``context``，可被独立操作符与「运行全部检查」复用
      * 通过 ``utils.get_target_mesh_objects`` 获取待检测物体（支持仅选中物体）
      * 使用 ``utils.bmesh_from_object`` 获取 BMesh（在批量会话中自动复用）
      * 检测结果为空时会主动清除旧结果，避免「选择」按钮选中过期索引
"""

import bpy

from .base import (
    LowPolyBaseOperator,
    format_found,
    install_error_guard,
    run_pipeline,
    store_result,
    uninstall_error_guard,
)
from .optimize_operators import (
    optimize_results,
    _do_suggest_dense_vertices,
    _do_suggest_downward_faces,
    _do_suggest_high_poly_objects,
    _do_suggest_intersecting_objects,
    _do_suggest_non_uniform_scale,
    _do_suggest_small_bevels,
)
from .. import utils
from .. import registry


# 全局存储检查结果
check_results = {}


# 该模块负责更新的计数属性（用于「清除结果」）——由 registry 单一数据源派生
COUNT_PROPERTIES = registry.count_properties('check')


# 简写别名（保持本模块内调用简洁）
_store_result = store_result


def _collect_over_meshes(context, extractor):
    """
    对每个目标物体执行 ``extractor(bm)``，收集非空结果。

    Args:
        context: Blender 上下文
        extractor: callable(BMesh) -> list[int]

    Returns:
        tuple: (data 字典 {obj: [索引...]}, 元素总数)
    """
    data = {}
    total = 0
    for obj in utils.get_target_mesh_objects(context):
        with utils.bmesh_from_object(obj) as bm:
            items = extractor(bm)
            if items:
                data[obj] = items
                total += len(items)
    return data, total


def _do_check_ngon(context):
    """执行 N-gon 检查，返回报告消息"""
    props = context.scene.lowpoly
    data, total = _collect_over_meshes(
        context, lambda bm: [face.index for face in bm.faces if len(face.verts) > 4]
    )
    props.ngon_count = total
    _store_result(check_results, 'ngon_faces', data, 'FACE')
    return format_found("N-gon面", total)


def _do_check_overlapping_faces(context):
    """执行重叠面检查，返回报告消息"""
    props = context.scene.lowpoly
    data, total = _collect_over_meshes(context, utils.get_faces_sharing_all_edges)
    props.overlapping_face_count = total
    _store_result(check_results, 'overlapping_faces', data, 'FACE')
    return format_found("重叠面", total)


def _do_check_wrong_normals(context):
    """执行错误法线检查，返回报告消息"""
    props = context.scene.lowpoly
    data, total = _collect_over_meshes(context, utils.get_wrong_normal_faces)
    props.wrong_normal_count = total
    _store_result(check_results, 'wrong_normals', data, 'FACE')
    return format_found("法线错误的面", total)


def _do_check_non_manifold_edges(context):
    """执行非流形边检查，返回报告消息"""
    props = context.scene.lowpoly
    data, total = _collect_over_meshes(context, utils.get_non_manifold_edges)
    props.non_manifold_edge_count = total
    _store_result(check_results, 'non_manifold_edges', data, 'EDGE')
    return format_found("非流形边", total)


def _do_check_loose_geometry(context):
    """执行孤立几何体检查（悬浮顶点 + 悬浮边），返回报告消息"""
    props = context.scene.lowpoly

    data = {}
    total_verts = 0
    total_edges = 0

    for obj in utils.get_target_mesh_objects(context):
        with utils.bmesh_from_object(obj) as bm:
            loose_verts, loose_edges = utils.get_loose_geometry(bm)
            if loose_verts or loose_edges:
                data[obj] = loose_verts
                total_verts += len(loose_verts)
                total_edges += len(loose_edges)

    props.loose_vert_count = total_verts
    props.loose_edge_count = total_edges

    _store_result(check_results, 'loose_geometry', data, 'VERT')

    parts = []
    if total_verts > 0:
        parts.append(f"{total_verts} 个悬浮顶点")
    if total_edges > 0:
        parts.append(f"{total_edges} 条悬浮边")
    return "找到 " + "、".join(parts) if parts else "未找到孤立几何体"


def _do_check_unwelded_vertices(context):
    """执行未焊接点检查，返回报告消息"""
    props = context.scene.lowpoly
    threshold = props.unwelded_threshold
    data, total = _collect_over_meshes(
        context, lambda bm: utils.get_unwelded_vertices(bm, threshold)
    )
    props.unwelded_vert_count = total
    _store_result(check_results, 'unwelded_vertices', data, 'VERT')
    return format_found("未焊接点", total)


def _do_check_collinear_vertices(context):
    """执行共线顶点检查，返回报告消息"""
    props = context.scene.lowpoly
    threshold = props.collinear_threshold
    data, total = _collect_over_meshes(
        context, lambda bm: utils.get_collinear_vertices(bm, threshold)
    )
    props.collinear_vert_count = total
    _store_result(check_results, 'collinear_vertices', data, 'VERT')
    return format_found("共线顶点", total)


def _do_check_degenerate_geometry(context):
    """执行退化几何体检查（零长度边 + 零面积面），返回报告消息"""
    props = context.scene.lowpoly
    edge_threshold = props.degenerate_edge_threshold
    face_threshold = props.degenerate_face_threshold

    edge_data = {}
    face_data = {}
    total_edges = 0
    total_faces = 0

    for obj in utils.get_target_mesh_objects(context):
        with utils.bmesh_from_object(obj) as bm:
            zero_edges = utils.get_zero_length_edges(bm, edge_threshold)
            zero_faces = utils.get_zero_area_faces(bm, face_threshold)
            if zero_edges:
                edge_data[obj] = zero_edges
                total_edges += len(zero_edges)
            if zero_faces:
                face_data[obj] = zero_faces
                total_faces += len(zero_faces)

    props.degenerate_edge_count = total_edges
    props.degenerate_face_count = total_faces

    # 选择时以边为主（退化边可同时定位其所属的退化面）；若本次检测根本没有
    # 退化边，则退化为「选择退化面」。
    # 注意: 元素类型必须与索引来源一致——旧实现固定写入 'EDGE'，于是当模型
    # 只有退化面时，面索引会被当作边索引写进选择标志，用户点「选择」看到的
    # 是一堆无关的边，真正的退化面反而选不中。
    if edge_data:
        _store_result(check_results, 'degenerate_geometry', edge_data, 'EDGE')
    else:
        _store_result(check_results, 'degenerate_geometry', face_data, 'FACE')

    parts = []
    if total_edges > 0:
        parts.append(f"{total_edges} 条退化边")
    if total_faces > 0:
        parts.append(f"{total_faces} 个退化面")
    return "找到 " + "、".join(parts) if parts else "未找到退化几何体"


def _do_check_distorted_quads(context):
    """执行非平面四边面检查，返回报告消息"""
    props = context.scene.lowpoly
    threshold = props.distortion_threshold

    def extract(bm):
        return [
            face.index
            for face in bm.faces
            if len(face.verts) == 4 and utils.calculate_face_planarity(face) > threshold
        ]

    data, total = _collect_over_meshes(context, extract)
    props.distorted_quad_count = total
    _store_result(check_results, 'distorted_quads', data, 'FACE')
    return format_found("非平面四边面", total)


def _do_check_concave_quads(context):
    """执行内凹四边面检查，返回报告消息"""
    props = context.scene.lowpoly

    def extract(bm):
        return [
            face.index
            for face in bm.faces
            if len(face.verts) == 4 and utils.is_face_concave(face)
        ]

    data, total = _collect_over_meshes(context, extract)
    props.concave_quad_count = total
    _store_result(check_results, 'concave_quads', data, 'FACE')
    return format_found("内凹四边面", total)


#: 检测项键 → 检测函数（与 ``registry.CHECKS`` 的 ``key`` 一一对应）
_CHECK_FUNCTIONS = {
    'ngon_faces': _do_check_ngon,
    'overlapping_faces': _do_check_overlapping_faces,
    'wrong_normals': _do_check_wrong_normals,
    'non_manifold_edges': _do_check_non_manifold_edges,
    'loose_geometry': _do_check_loose_geometry,
    'unwelded_vertices': _do_check_unwelded_vertices,
    'collinear_vertices': _do_check_collinear_vertices,
    'dense_vertices': _do_suggest_dense_vertices,
    'degenerate_geometry': _do_check_degenerate_geometry,
    'distorted_quads': _do_check_distorted_quads,
    'concave_quads': _do_check_concave_quads,
    'high_poly_objects': _do_suggest_high_poly_objects,
    'small_bevels': _do_suggest_small_bevels,
    'downward_faces': _do_suggest_downward_faces,
    'intersecting_objects': _do_suggest_intersecting_objects,
    'non_uniform_scale': _do_suggest_non_uniform_scale,
}


def get_check_pipeline():
    """
    返回「运行全部检查」的执行清单。

    顺序完全由 ``registry.CHECKS`` 的声明顺序决定，与面板分组一致——
    新增检测项时无需再手工维护这份清单。

    Returns:
        list[tuple[str, callable]]: (中文标签, 检测函数)
    """
    return [(spec.label, _CHECK_FUNCTIONS[spec.key]) for spec in registry.CHECKS]


class LOWPOLY_OT_check_ngon_faces(bpy.types.Operator, LowPolyBaseOperator):
    """检查N-gon面"""
    bl_idname = "lowpoly.check_ngon_faces"
    bl_label = "检查N-gon面"
    bl_description = "检查多于4边的面"

    def execute(self, context):
        self.report({'INFO'}, _do_check_ngon(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_ngon_faces(bpy.types.Operator, LowPolyBaseOperator):
    """选择N-gon面"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_ngon_faces"
    bl_label = "选择N-gon面"
    bl_description = "选择已检查出的N-gon面"

    def execute(self, context):
        return self._execute_sub_element_select(context, check_results, 'ngon_faces', 'FACE', 'N-gon面')


class LOWPOLY_OT_check_overlapping_faces(bpy.types.Operator, LowPolyBaseOperator):
    """检查重叠面"""
    bl_idname = "lowpoly.check_overlapping_faces"
    bl_label = "检查重叠面"
    bl_description = "检查共用所有边的重叠面"

    def execute(self, context):
        self.report({'INFO'}, _do_check_overlapping_faces(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_overlapping_faces(bpy.types.Operator, LowPolyBaseOperator):
    """选择重叠面"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_overlapping_faces"
    bl_label = "选择重叠面"
    bl_description = "选择已检查出的重叠面"

    def execute(self, context):
        return self._execute_sub_element_select(context, check_results, 'overlapping_faces', 'FACE', '重叠面')


class LOWPOLY_OT_check_wrong_normals(bpy.types.Operator, LowPolyBaseOperator):
    """检查错误法线（反法线/朝内的面）"""
    bl_idname = "lowpoly.check_wrong_normals"
    bl_label = "检查错误法线"
    bl_description = "检测法线朝向与大多数面相反的面"

    def execute(self, context):
        self.report({'INFO'}, _do_check_wrong_normals(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_wrong_normals(bpy.types.Operator, LowPolyBaseOperator):
    """选择错误法线面（反法线/朝内的面）"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_wrong_normals"
    bl_label = "选择错误法线面"
    bl_description = "选择已检测出的法线朝内的面"

    def execute(self, context):
        return self._execute_sub_element_select(context, check_results, 'wrong_normals', 'FACE', '法线朝内的面')


class LOWPOLY_OT_check_non_manifold_edges(bpy.types.Operator, LowPolyBaseOperator):
    """检查非流形边"""
    bl_idname = "lowpoly.check_non_manifold_edges"
    bl_label = "检查非流形边"
    bl_description = "检测被3个及以上面共用的非流形边"

    def execute(self, context):
        self.report({'INFO'}, _do_check_non_manifold_edges(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_non_manifold_edges(bpy.types.Operator, LowPolyBaseOperator):
    """选择非流形边"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_non_manifold_edges"
    bl_label = "选择非流形边"
    bl_description = "选择已检测出的非流形边"

    def execute(self, context):
        return self._execute_sub_element_select(context, check_results, 'non_manifold_edges', 'EDGE', '非流形边')


class LOWPOLY_OT_check_loose_geometry(bpy.types.Operator, LowPolyBaseOperator):
    """检查孤立几何体"""
    bl_idname = "lowpoly.check_loose_geometry"
    bl_label = "检查孤立几何体"
    bl_description = "检测悬浮顶点和悬浮边（不属于任何面的几何体）"

    def execute(self, context):
        self.report({'INFO'}, _do_check_loose_geometry(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_loose_geometry(bpy.types.Operator, LowPolyBaseOperator):
    """选择孤立几何体"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_loose_geometry"
    bl_label = "选择孤立几何体"
    bl_description = "选择已检测出的悬浮顶点"

    def execute(self, context):
        return self._execute_sub_element_select(context, check_results, 'loose_geometry', 'VERT', '孤立几何体')


class LOWPOLY_OT_check_unwelded_vertices(bpy.types.Operator, LowPolyBaseOperator):
    """检查未焊接点"""
    bl_idname = "lowpoly.check_unwelded_vertices"
    bl_label = "检查未焊接点"
    bl_description = "检查相同位置下未焊接的点"

    def execute(self, context):
        self.report({'INFO'}, _do_check_unwelded_vertices(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_unwelded_vertices(bpy.types.Operator, LowPolyBaseOperator):
    """选择未焊接点"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_unwelded_vertices"
    bl_label = "选择未焊接点"
    bl_description = "选择已检查出的未焊接点"

    def execute(self, context):
        return self._execute_sub_element_select(context, check_results, 'unwelded_vertices', 'VERT', '未焊接点')


class LOWPOLY_OT_check_collinear_vertices(bpy.types.Operator, LowPolyBaseOperator):
    """检查共线顶点"""
    bl_idname = "lowpoly.check_collinear_vertices"
    bl_label = "检查共线顶点"
    bl_description = "检查直线上的废点（三点共线）"

    def execute(self, context):
        self.report({'INFO'}, _do_check_collinear_vertices(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_collinear_vertices(bpy.types.Operator, LowPolyBaseOperator):
    """选择共线顶点"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_collinear_vertices"
    bl_label = "选择共线顶点"
    bl_description = "选择已检查出的共线顶点"

    def execute(self, context):
        return self._execute_sub_element_select(context, check_results, 'collinear_vertices', 'VERT', '共线顶点')


class LOWPOLY_OT_check_degenerate_geometry(bpy.types.Operator, LowPolyBaseOperator):
    """检查退化几何体（零长度边 + 零面积面）"""
    bl_idname = "lowpoly.check_degenerate_geometry"
    bl_label = "检查退化几何体"
    bl_description = "检测零长度边和零面积面"

    def execute(self, context):
        self.report({'INFO'}, _do_check_degenerate_geometry(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_degenerate_geometry(bpy.types.Operator, LowPolyBaseOperator):
    """选择退化几何体"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_degenerate_geometry"
    bl_label = "选择退化几何体"
    bl_description = "选择已检测出的退化边；若没有退化边则选择退化面"

    def execute(self, context):
        return self._execute_sub_element_select(context, check_results, 'degenerate_geometry', 'EDGE', '退化几何体')


class LOWPOLY_OT_check_distorted_quads(bpy.types.Operator, LowPolyBaseOperator):
    """检查非平面四边面（扭曲四边面）"""
    bl_idname = "lowpoly.check_distorted_quads"
    bl_label = "检查非平面四边面"
    bl_description = "检查不共面的四边面（扭曲四边面）"

    def execute(self, context):
        self.report({'INFO'}, _do_check_distorted_quads(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_distorted_quads(bpy.types.Operator, LowPolyBaseOperator):
    """选择非平面四边面"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_distorted_quads"
    bl_label = "选择非平面四边面"
    bl_description = "选择已检查出的非平面四边面"

    def execute(self, context):
        return self._execute_sub_element_select(context, check_results, 'distorted_quads', 'FACE', '非平面四边面')


class LOWPOLY_OT_check_concave_quads(bpy.types.Operator, LowPolyBaseOperator):
    """检查内凹四边面"""
    bl_idname = "lowpoly.check_concave_quads"
    bl_label = "检查内凹四边面"
    bl_description = "检查内凹的四边面"

    def execute(self, context):
        self.report({'INFO'}, _do_check_concave_quads(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_concave_quads(bpy.types.Operator, LowPolyBaseOperator):
    """选择内凹四边面"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_concave_quads"
    bl_label = "选择内凹四边面"
    bl_description = "选择已检查出的内凹四边面"

    def execute(self, context):
        return self._execute_sub_element_select(context, check_results, 'concave_quads', 'FACE', '内凹四边面')


class LOWPOLY_OT_run_all_checks(bpy.types.Operator, LowPolyBaseOperator):
    """运行全部检查"""
    bl_idname = "lowpoly.run_all_checks"
    bl_label = "运行全部检查"
    bl_description = "运行全部网格质量和场景优化检查并更新计数"

    def execute(self, context):
        check_results.clear()
        optimize_results.clear()

        objects = utils.get_target_mesh_objects(context)
        if not objects:
            self.report({'WARNING'}, "没有可检测的网格物体（请检查可见性或「仅处理选中物体」选项）")
            return {'CANCELLED'}

        total_verts = sum(len(obj.data.vertices) for obj in objects)
        if total_verts > 500000:
            self.report(
                {'WARNING'},
                f"检测到大型网格（{total_verts} 个顶点），检查可能需要较长时间",
            )

        pipeline = get_check_pipeline()
        failed = run_pipeline(context, pipeline, report=self.report)

        if not failed:
            self.report({'INFO'}, f"全部检查已完成（共 {len(objects)} 个物体）")
        return {'FINISHED'}


class LOWPOLY_OT_clear_results(bpy.types.Operator, LowPolyBaseOperator):
    """清除全部检测结果"""
    bl_idname = "lowpoly.clear_results"
    bl_label = "清除检测结果"
    bl_description = "清空所有检测结果与计数（不修改模型）"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return self._clear_all_results(context)


# 检查操作符类列表
classes = [
    LOWPOLY_OT_check_ngon_faces,
    LOWPOLY_OT_select_ngon_faces,
    LOWPOLY_OT_check_overlapping_faces,
    LOWPOLY_OT_select_overlapping_faces,
    LOWPOLY_OT_check_wrong_normals,
    LOWPOLY_OT_select_wrong_normals,
    LOWPOLY_OT_check_non_manifold_edges,
    LOWPOLY_OT_select_non_manifold_edges,
    LOWPOLY_OT_check_loose_geometry,
    LOWPOLY_OT_select_loose_geometry,
    LOWPOLY_OT_check_unwelded_vertices,
    LOWPOLY_OT_select_unwelded_vertices,
    LOWPOLY_OT_check_collinear_vertices,
    LOWPOLY_OT_select_collinear_vertices,
    LOWPOLY_OT_check_degenerate_geometry,
    LOWPOLY_OT_select_degenerate_geometry,
    LOWPOLY_OT_check_distorted_quads,
    LOWPOLY_OT_select_distorted_quads,
    LOWPOLY_OT_check_concave_quads,
    LOWPOLY_OT_select_concave_quads,
    LOWPOLY_OT_run_all_checks,
    LOWPOLY_OT_clear_results,
]


def register():
    """注册检查操作符"""
    for cls in classes:
        install_error_guard(cls)
        bpy.utils.register_class(cls)


def unregister():
    """注销检查操作符（幂等：未注册的类会被安全跳过）"""
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
        uninstall_error_guard(cls)
