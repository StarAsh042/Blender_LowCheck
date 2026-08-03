"""
UI面板模块
定义插件的用户界面
"""

import bpy


class LOWPOLY_PT_quality_panel(bpy.types.Panel):
    """
    低模质量检查面板
    按模型制作流程分为：网格拓扑 / 顶点质量 / 面质量 / 场景优化
    """
    bl_label = "低模质量检查"
    bl_idname = "LOWPOLY_PT_quality_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Lowpoly Tools"

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'EDIT_MESH'}

    def draw(self, context):
        layout = self.layout
        props = getattr(context.scene, "lowpoly", None)
        if props is None:
            layout.label(text="插件未正确加载，请重新启用", icon='ERROR')
            return

        box = layout.box()
        box.label(text="检测范围", icon='RESTRICT_SELECT_OFF')
        box.prop(props, "only_selected", toggle=True)


# ── 注册/注销 ──────────────────────────────────────────────────────────

classes = [
    LOWPOLY_PT_quality_panel,
]


def register():
    """注册UI面板（*必须在属性组之后注册*）"""
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    """注销UI面板（幂等）"""
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
