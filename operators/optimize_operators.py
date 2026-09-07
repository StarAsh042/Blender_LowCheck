"""
优化操作符模块
包含所有优化建议相关的操作符

设计说明与 ``check_operators`` 保持一致：检测逻辑与操作符分离，
结果为空时清除旧键，注册时统一安装异常守卫。
"""

import bpy

from .base import (
    LowPolyBaseOperator,
    install_error_guard,
    store_object_result,
    store_result,
    uninstall_error_guard,
)

from .. import utils


# 全局存储优化结果
optimize_results = {}


def _format_message(label, count):
    """「检测到 N 个 X / 未检测到 X」报告文案"""
    return f"检测到 {count} 个{label}" if count > 0 else f"未检测到{label}"


def _do_suggest_dense_vertices(context):
    """执行密集顶点检测，返回报告消息"""
    props = context.scene.lowpoly
    distance = props.dense_distance_threshold
    count = props.dense_count_threshold

    data = {}
    total_count = 0

    for obj in utils.get_target_mesh_objects(context):
        with utils.bmesh_from_object(obj) as bm:
            dense_verts = utils.get_dense_vertices(bm, distance, count)
            if dense_verts:
                data[obj] = dense_verts
                total_count += len(dense_verts)

    props.dense_vert_count = total_count
    store_result(optimize_results, 'dense_vertices', data, 'VERT')
    return _format_message("密集顶点", total_count)


def _do_suggest_high_poly_objects(context):
    """执行高面数物体检测，返回报告消息"""
    props = context.scene.lowpoly
    threshold = props.polycount_threshold

    high_poly_objects = [
        obj
        for obj in utils.get_target_mesh_objects(context)
        if len(obj.data.polygons) > threshold
    ]

    props.high_poly_count = len(high_poly_objects)
    store_object_result(optimize_results, 'high_poly_objects', high_poly_objects)
    return _format_message("高面数物体", len(high_poly_objects))


def _do_suggest_small_bevels(context):
    """执行小倒角结构检测，返回报告消息"""
    props = context.scene.lowpoly
    threshold = props.bevel_width_threshold

    data = {}
    total_count = 0

    for obj in utils.get_target_mesh_objects(context):
        with utils.bmesh_from_object(obj) as bm:
            small_bevels = utils.get_small_bevels(bm, threshold)
            if small_bevels:
                data[obj] = small_bevels
                total_count += len(small_bevels)

    props.small_bevel_count = total_count
    store_result(optimize_results, 'small_bevels', data, 'FACE')
    return _format_message("小倒角结构", total_count)


def _do_suggest_downward_faces(context):
    """执行朝下水平面检测，返回报告消息"""
    props = context.scene.lowpoly
    area = props.downward_area_threshold
    angle = props.downward_angle_threshold

    data = {}
    total_count = 0

    for obj in utils.get_target_mesh_objects(context):
        with utils.bmesh_from_object(obj) as bm:
            downward_faces = utils.get_downward_faces(bm, area, angle)
            if downward_faces:
                data[obj] = downward_faces
                total_count += len(downward_faces)

    props.downward_face_count = total_count
    store_result(optimize_results, 'downward_faces', data, 'FACE')
    return _format_message("朝下水平面", total_count)


class LOWPOLY_OT_suggest_dense_vertices(bpy.types.Operator, LowPolyBaseOperator):
    """密集顶点"""
    bl_idname = "lowpoly.suggest_dense_vertices"
    bl_label = "密集顶点"
    bl_description = "检测顶点过于密集的结构"

    def execute(self, context):
        self.report({'INFO'}, _do_suggest_dense_vertices(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_dense_vertices(bpy.types.Operator, LowPolyBaseOperator):
    """选择密集顶点"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_dense_vertices"
    bl_label = "选择密集顶点"
    bl_description = "选择已检测出的密集顶点"

    def execute(self, context):
        return self._execute_sub_element_select(context, optimize_results, 'dense_vertices', 'VERT', '密集顶点')


class LOWPOLY_OT_suggest_high_poly_objects(bpy.types.Operator, LowPolyBaseOperator):
    """高面数物体"""
    bl_idname = "lowpoly.suggest_high_poly_objects"
    bl_label = "高面数物体"
    bl_description = "检测面数较高的物体"

    def execute(self, context):
        self.report({'INFO'}, _do_suggest_high_poly_objects(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_high_poly_objects(bpy.types.Operator, LowPolyBaseOperator):
    """选择高面数物体"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_high_poly_objects"
    bl_label = "选择高面数物体"
    bl_description = "选择已检测出的高面数物体"

    def execute(self, context):
        return self._execute_sub_element_select(context, optimize_results, 'high_poly_objects', 'OBJECT', '高面数物体')


class LOWPOLY_OT_suggest_small_bevels(bpy.types.Operator, LowPolyBaseOperator):
    """小倒角结构"""
    bl_idname = "lowpoly.suggest_small_bevels"
    bl_label = "小倒角结构"
    bl_description = "检测较小的倒角结构"

    def execute(self, context):
        self.report({'INFO'}, _do_suggest_small_bevels(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_small_bevels(bpy.types.Operator, LowPolyBaseOperator):
    """选择小倒角结构"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_small_bevels"
    bl_label = "选择小倒角结构"
    bl_description = "选择已检测出的小倒角结构"

    def execute(self, context):
        return self._execute_sub_element_select(context, optimize_results, 'small_bevels', 'FACE', '小倒角结构')


class LOWPOLY_OT_suggest_downward_faces(bpy.types.Operator, LowPolyBaseOperator):
    """朝下水平面"""
    bl_idname = "lowpoly.suggest_downward_faces"
    bl_label = "朝下水平面"
    bl_description = "检测水平朝下的面（可能浪费面数）"

    def execute(self, context):
        self.report({'INFO'}, _do_suggest_downward_faces(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_downward_faces(bpy.types.Operator, LowPolyBaseOperator):
    """选择朝下水平面"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_downward_faces"
    bl_label = "选择朝下水平面"
    bl_description = "选择已检测出的朝下水平面"

    def execute(self, context):
        return self._execute_sub_element_select(context, optimize_results, 'downward_faces', 'FACE', '朝下水平面')


# 优化操作符类列表
classes = [
    LOWPOLY_OT_suggest_dense_vertices,
    LOWPOLY_OT_select_dense_vertices,
    LOWPOLY_OT_suggest_high_poly_objects,
    LOWPOLY_OT_select_high_poly_objects,
    LOWPOLY_OT_suggest_small_bevels,
    LOWPOLY_OT_select_small_bevels,
    LOWPOLY_OT_suggest_downward_faces,
    LOWPOLY_OT_select_downward_faces,
]


def register():
    """注册优化操作符"""
    for cls in classes:
        install_error_guard(cls)
        bpy.utils.register_class(cls)


def unregister():
    """注销优化操作符（幂等：未注册的类会被安全跳过）"""
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
        uninstall_error_guard(cls)
