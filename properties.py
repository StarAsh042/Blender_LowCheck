"""
属性组模块
定义插件的属性组和配置参数
"""

import bpy


class LowPolyProperties(bpy.types.PropertyGroup):
    """
    低模质量检查属性组
    合并原有的错误检查和优化建议属性，存储所有检测计数和阈值
    """

    # ── 网格拓扑：计数 ──────────────────────────────────────────
    ngon_count: bpy.props.IntProperty(
        name="N-gon面数",
        default=0,
        description="检测到的N-gon面数量"
    )

    # ── 顶点质量：计数 ──────────────────────────────────────────
    collinear_vert_count: bpy.props.IntProperty(
        name="共线顶点数",
        default=0,
        description="检测到的共线顶点数量"
    )

    # ── 运行选项 ────────────────────────────────────────────────
    only_selected: bpy.props.BoolProperty(
        name="仅处理选中物体",
        description="勾选后只检测当前被选中的可见网格物体，适合在大场景中做局部检查",
        default=False
    )

    # ── 阈值设置 ────────────────────────────────────────────────
    # 顶点质量阈值
    collinear_threshold: bpy.props.FloatProperty(
        name="共线阈值",
        description="三点共线的角度阈值（弧度），越小越严格（默认 0.01）",
        default=0.01,
        min=0.0,
        max=1.57,
        precision=4,
        step=0.01
    )


def register():
    """
    注册属性组。

    先注销可能残留的旧定义，保证在开发中反复 reload
    （例如通过 Blender 的「重新加载脚本」）时不会报
    「already registered」。
    """
    unregister()
    bpy.utils.register_class(LowPolyProperties)
    bpy.types.Scene.lowpoly = bpy.props.PointerProperty(type=LowPolyProperties)


def unregister():
    """注销属性组（幂等：未注册时调用不会抛异常）"""
    if hasattr(bpy.types.Scene, "lowpoly"):
        try:
            del bpy.types.Scene.lowpoly
        except (AttributeError, TypeError):
            pass

    try:
        bpy.utils.unregister_class(LowPolyProperties)
    except (RuntimeError, ValueError):
        pass
