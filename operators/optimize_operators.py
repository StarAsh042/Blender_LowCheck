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


# 优化操作符类列表
classes = [
    LOWPOLY_OT_suggest_dense_vertices,
    LOWPOLY_OT_select_dense_vertices,
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
