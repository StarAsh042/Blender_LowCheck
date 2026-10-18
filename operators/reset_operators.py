"""
重置参数操作符模块
包含参数重置相关的操作符
"""

import bpy

from .base import LowPolyBaseOperator, install_error_guard, uninstall_error_guard
from ..properties import ALL_DEFAULTS


class LOWPOLY_OT_reset_param(bpy.types.Operator, LowPolyBaseOperator):
    """重置单个参数"""
    bl_idname = "lowpoly.reset_param"
    bl_label = "Reset Parameter"
    bl_description = "Reset the specified parameter to its default"
    bl_options = {'REGISTER', 'UNDO'}

    param_name: bpy.props.StringProperty(
        name="参数名称",
        description="要重置的参数名称",
        default="",
    )

    @classmethod
    def description(cls, context, properties):
        """在悬浮提示中显示该参数的默认值，便于用户理解「重置」的结果"""
        name = getattr(properties, "param_name", "") if properties else ""
        default = ALL_DEFAULTS.get(name)
        if default is None:
            return "重置该参数为默认值"
        return f"重置为默认值：{default}"

    def execute(self, context):
        props = context.scene.lowpoly

        if self.param_name not in ALL_DEFAULTS:
            self.report({'WARNING'}, f"未找到参数: {self.param_name}")
            return {'CANCELLED'}

        setattr(props, self.param_name, ALL_DEFAULTS[self.param_name])
        self.report({'INFO'}, f"已重置 {self.param_name}")
        return {'FINISHED'}


class LOWPOLY_OT_reset_all_params(bpy.types.Operator, LowPolyBaseOperator):
    """重置所有参数"""
    bl_idname = "lowpoly.reset_all_params"
    bl_label = "Reset All Parameters"
    bl_description = "Reset all check and optimization parameters to defaults"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.lowpoly

        for param_name, default_value in ALL_DEFAULTS.items():
            if not hasattr(props, param_name):
                continue
            try:
                setattr(props, param_name, default_value)
            except (AttributeError, TypeError):
                continue

        self.report({'INFO'}, "所有参数已重置为默认值")
        return {'FINISHED'}


# 重置操作符类列表
classes = [
    LOWPOLY_OT_reset_param,
    LOWPOLY_OT_reset_all_params,
]


def register():
    """注册重置操作符"""
    for cls in classes:
        install_error_guard(cls)
        bpy.utils.register_class(cls)


def unregister():
    """注销重置操作符（幂等：未注册的类会被安全跳过）"""
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
        uninstall_error_guard(cls)
