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
    run_pipeline,
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


# 该模块负责更新的计数属性（用于「清除结果」）
COUNT_PROPERTIES = (
    "dense_vert_count",
    "high_poly_count",
    "small_bevel_count",
    "downward_face_count",
    "intersecting_object_count",
    "non_uniform_scale_count",
)


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


def _do_suggest_intersecting_objects(context):
    """执行穿插物体检测，返回报告消息"""
    props = context.scene.lowpoly
    intersecting_objects = utils.get_intersecting_objects(
        context, props.intersect_overlap_threshold
    )

    props.intersecting_object_count = len(intersecting_objects)
    store_object_result(optimize_results, 'intersecting_objects', intersecting_objects)
    return _format_message("穿插物体", len(intersecting_objects))


def _do_suggest_non_uniform_scale(context):
    """执行非均匀缩放物体检测，返回报告消息"""
    props = context.scene.lowpoly
    non_uniform = utils.get_non_uniform_scale_objects(context)

    props.non_uniform_scale_count = len(non_uniform)
    store_object_result(optimize_results, 'non_uniform_scale', non_uniform)
    return _format_message("非均匀缩放物体", len(non_uniform))


#: 「运行全部优化检查」的执行清单（顺序与面板分组一致）
_OPTIMIZE_PIPELINE = (
    ("密集顶点检测", _do_suggest_dense_vertices),
    ("高面数物体检测", _do_suggest_high_poly_objects),
    ("小倒角结构检测", _do_suggest_small_bevels),
    ("朝下水平面检测", _do_suggest_downward_faces),
    ("穿插物体检测", _do_suggest_intersecting_objects),
    ("非均匀缩放物体检测", _do_suggest_non_uniform_scale),
)


def get_optimize_pipeline():
    """
    返回「运行全部优化检查」的执行清单。

    Returns:
        list[tuple[str, callable]]: (中文标签, 检测函数)
    """
    return list(_OPTIMIZE_PIPELINE)


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


class LOWPOLY_OT_suggest_intersecting_objects(bpy.types.Operator, LowPolyBaseOperator):
    """穿插物体"""
    bl_idname = "lowpoly.suggest_intersecting_objects"
    bl_label = "穿插物体"
    bl_description = "检测互相穿插的物体"

    def execute(self, context):
        self.report({'INFO'}, _do_suggest_intersecting_objects(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_intersecting_objects(bpy.types.Operator, LowPolyBaseOperator):
    """选择穿插物体"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_intersecting_objects"
    bl_label = "选择穿插物体"
    bl_description = "选择已检测出的穿插物体"

    def execute(self, context):
        return self._execute_sub_element_select(context, optimize_results, 'intersecting_objects', 'OBJECT', '穿插物体')


class LOWPOLY_OT_suggest_non_uniform_scale(bpy.types.Operator, LowPolyBaseOperator):
    """非均匀缩放物体"""
    bl_idname = "lowpoly.suggest_non_uniform_scale"
    bl_label = "非均匀缩放物体"
    bl_description = "检测缩放值不统一的物体"

    def execute(self, context):
        self.report({'INFO'}, _do_suggest_non_uniform_scale(context))
        return {'FINISHED'}


class LOWPOLY_OT_select_non_uniform_scale(bpy.types.Operator, LowPolyBaseOperator):
    """选择非均匀缩放物体"""
    bl_options = {'REGISTER', 'UNDO'}
    bl_idname = "lowpoly.select_non_uniform_scale"
    bl_label = "选择非均匀缩放物体"
    bl_description = "选择已检测出的非均匀缩放物体"

    def execute(self, context):
        return self._execute_sub_element_select(context, optimize_results, 'non_uniform_scale', 'OBJECT', '非均匀缩放物体')


class LOWPOLY_OT_run_all_optimization_checks(bpy.types.Operator, LowPolyBaseOperator):
    """运行全部优化检查"""
    bl_idname = "lowpoly.run_all_optimization_checks"
    bl_label = "运行全部优化检查"
    bl_description = "运行所有优化检查并更新计数"

    def execute(self, context):
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

        failed = run_pipeline(context, get_optimize_pipeline(), report=self.report)
        if not failed:
            self.report({'INFO'}, f"所有优化检查已完成（共 {len(objects)} 个物体）")
        return {'FINISHED'}


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
    LOWPOLY_OT_suggest_intersecting_objects,
    LOWPOLY_OT_select_intersecting_objects,
    LOWPOLY_OT_suggest_non_uniform_scale,
    LOWPOLY_OT_select_non_uniform_scale,
    LOWPOLY_OT_run_all_optimization_checks,
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
