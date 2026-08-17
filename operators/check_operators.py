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
    install_error_guard,
    store_result,
    uninstall_error_guard,
)
from .. import utils


# 全局存储检查结果
check_results = {}


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


def _format_message(label, count):
    """统一的「找到 N 个 X / 未找到 X」报告文案"""
    return f"找到 {count} 个{label}" if count > 0 else f"未找到{label}"


def _do_check_ngon(context):
    """执行 N-gon 检查，返回报告消息"""
    props = context.scene.lowpoly
    data, total = _collect_over_meshes(
        context, lambda bm: [face.index for face in bm.faces if len(face.verts) > 4]
    )
    props.ngon_count = total
    _store_result(check_results, 'ngon_faces', data, 'FACE')
    return _format_message("N-gon面", total)


def _do_check_overlapping_faces(context):
    """执行重叠面检查，返回报告消息"""
    props = context.scene.lowpoly
    data, total = _collect_over_meshes(context, utils.get_faces_sharing_all_edges)
    props.overlapping_face_count = total
    _store_result(check_results, 'overlapping_faces', data, 'FACE')
    return _format_message("重叠面", total)


def _do_check_wrong_normals(context):
    """执行错误法线检查，返回报告消息"""
    props = context.scene.lowpoly
    data, total = _collect_over_meshes(context, utils.get_wrong_normal_faces)
    props.wrong_normal_count = total
    _store_result(check_results, 'wrong_normals', data, 'FACE')
    return _format_message("法线错误的面", total)


def _do_check_non_manifold_edges(context):
    """执行非流形边检查，返回报告消息"""
    props = context.scene.lowpoly
    data, total = _collect_over_meshes(context, utils.get_non_manifold_edges)
    props.non_manifold_edge_count = total
    _store_result(check_results, 'non_manifold_edges', data, 'EDGE')
    return _format_message("非流形边", total)


def _do_check_collinear_vertices(context):
    """执行共线顶点检查，返回报告消息"""
    props = context.scene.lowpoly
    threshold = props.collinear_threshold
    data, total = _collect_over_meshes(
        context, lambda bm: utils.get_collinear_vertices(bm, threshold)
    )
    props.collinear_vert_count = total
    _store_result(check_results, 'collinear_vertices', data, 'VERT')
    return _format_message("共线顶点", total)


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
    LOWPOLY_OT_check_collinear_vertices,
    LOWPOLY_OT_select_collinear_vertices,
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
