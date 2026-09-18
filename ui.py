"""
UI面板模块
定义插件的用户界面 — 单面板四分组结构

面板内容完全由 :mod:`registry` 驱动：分组、行标题、图标、检查/选择按钮、
阈值滑杆与数量文案都来自单一数据源。新增检测项只需在 ``registry.CHECKS``
中登记，无需改动本文件——这消除了「改了检测项却漏改面板」这类低级错误。
"""

import bpy

from . import registry


# ── 辅助函数 ─────────────────────────────────────────────────────────

def _draw_op_row(layout, check_op, select_op, count_text):
    """绘制 检查 / 选择 按钮 + 数量标签"""
    row = layout.row(align=True)
    row.operator(check_op, text="检查")
    row.operator(select_op, text="选择")
    row.label(text=count_text)


def _draw_threshold_row(layout, props, prop_name):
    """
    绘制阈值滑杆 + 重置按钮。

    阈值本身的默认值与含义写在属性 description 中（悬浮可见），
    重置按钮的悬浮提示会显示该参数的具体默认值。
    """
    row = layout.row(align=True)
    row.prop(props, prop_name)
    reset_op = row.operator("lowpoly.reset_param", text="", icon='LOOP_BACK')
    reset_op.param_name = prop_name


def _format_count(spec, props):
    """按检测项声明的模板渲染数量文案"""
    values = {name: getattr(props, name, 0) for name in spec.count_props}
    return spec.count_template.format(**values)


def _count_problems(props):
    """统计面板显示的问题总数（计数属性来自 registry，避免清单漂移）"""
    return sum(getattr(props, name, 0) for name in registry.count_properties())


# ── 主面板 ────────────────────────────────────────────────────────────

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

        self._draw_header(layout, props)
        self._draw_summary(layout, props)

        for group_key, group_label, group_icon in registry.GROUPS:
            specs = registry.checks_in_group(group_key)
            if not specs:
                continue

            layout.separator()
            layout.label(text=group_label, icon=group_icon)

            for spec in specs:
                box = layout.box()
                box.label(text=spec.label, icon=spec.icon)
                _draw_op_row(
                    box, spec.check_op, spec.select_op, _format_count(spec, props)
                )
                for threshold in spec.thresholds:
                    _draw_threshold_row(box, props, threshold)

    # ── 子区块 ──────────────────────────────────────────────────────

    @staticmethod
    def _draw_header(layout, props):
        """顶部：运行范围 + 全局操作按钮"""
        box = layout.box()
        box.label(text="检测范围", icon='RESTRICT_SELECT_OFF')
        box.prop(props, "only_selected", toggle=True)

        col = box.column(align=True)
        col.operator("lowpoly.run_all_checks", text="运行全部检查", icon='FILE_REFRESH')
        row = col.row(align=True)
        row.operator("lowpoly.clear_results", text="清除结果", icon='X')
        row.operator("lowpoly.reset_all_params", text="重置所有参数", icon='LOOP_BACK')

    @staticmethod
    def _draw_summary(layout, props):
        """结果汇总：让用户一眼看到整体质量状况"""
        total = _count_problems(props)
        box = layout.box()

        row = box.row()
        row.alignment = 'LEFT'
        if total > 0:
            row.label(text=f"问题总数: {total}", icon='ERROR')
        else:
            row.label(text="暂无检测结果", icon='INFO')

        hint = box.column(align=True)
        hint.scale_y = 0.85
        if props.only_selected:
            hint.label(text="提示: 当前仅检测选中物体", icon='RESTRICT_SELECT_ON')
        hint.label(text="提示: 未发现的项会清空其历史结果", icon='QUESTION')


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
