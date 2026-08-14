"""
UI面板模块
定义插件的用户界面 — 单面板四分组结构
"""

import bpy

def _draw_op_row(layout, check_op, select_op, count_text):
    """绘制 检查 / 选择 按钮 + 数量标签"""
    row = layout.row(align=True)
    row.operator(check_op, text="检查")
    row.operator(select_op, text="选择")
    row.label(text=count_text)


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

        layout.separator()
        layout.label(text="网格拓扑", icon='MESH_DATA')

        box = layout.box()
        box.label(text="N-gon面检查", icon='MESH_DATA')
        _draw_op_row(box, "LOWPOLY_OT_check_ngon_faces", "LOWPOLY_OT_select_ngon_faces", f"数量: {props.ngon_count}")

        box = layout.box()
        box.label(text="错误法线检查（朝内）", icon='NORMALS_FACE')
        _draw_op_row(box, "LOWPOLY_OT_check_wrong_normals", "LOWPOLY_OT_select_wrong_normals", f"数量: {props.wrong_normal_count}")

        box = layout.box()
        box.label(text="非流形边检查", icon='EDGESEL')
        _draw_op_row(box, "LOWPOLY_OT_check_non_manifold_edges", "LOWPOLY_OT_select_non_manifold_edges", f"数量: {props.non_manifold_edge_count}")

        layout.separator()
        layout.label(text="顶点质量", icon='VERTEXSEL')

        box = layout.box()
        box.label(text="共线顶点检查", icon='VERTEXSEL')
        _draw_op_row(box, "LOWPOLY_OT_check_collinear_vertices", "LOWPOLY_OT_select_collinear_vertices", f"数量: {props.collinear_vert_count}")
        row = box.row(align=True)
        row.prop(props, "collinear_threshold")



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
