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
    overlapping_face_count: bpy.props.IntProperty(
        name="重叠面数",
        default=0,
        description="检测到的重叠面数量"
    )
    wrong_normal_count: bpy.props.IntProperty(
        name="错误法线面数",
        default=0,
        description="检测到的法线朝内的面数量"
    )
    non_manifold_edge_count: bpy.props.IntProperty(
        name="非流形边数",
        default=0,
        description="检测到的非流形边数量（被3个及以上面共用）"
    )
    loose_vert_count: bpy.props.IntProperty(
        name="孤立顶点数",
        default=0,
        description="不属于任何面的悬浮顶点数量"
    )
    loose_edge_count: bpy.props.IntProperty(
        name="孤立边数",
        default=0,
        description="不属于任何面的悬浮边数量"
    )

    # ── 顶点质量：计数 ──────────────────────────────────────────
    unwelded_vert_count: bpy.props.IntProperty(
        name="未焊接点数",
        default=0,
        description="检测到的未焊接点数量"
    )
    collinear_vert_count: bpy.props.IntProperty(
        name="共线顶点数",
        default=0,
        description="检测到的共线顶点数量"
    )
    dense_vert_count: bpy.props.IntProperty(
        name="密集顶点数",
        default=0,
        description="检测到的密集顶点数量"
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
    unwelded_threshold: bpy.props.FloatProperty(
        name="未焊接阈值",
        description="判断顶点未焊接的距离阈值，两点距离小于该值且无边相连即视为未焊接（默认 0.001）",
        default=0.001,
        min=0.0,
        precision=6,
        step=0.1
    )
    dense_distance_threshold: bpy.props.FloatProperty(
        name="密集距离阈值",
        description="判断顶点密集的搜索半径（默认 0.1）",
        default=0.1,
        min=0.0,
        precision=4,
        step=0.1
    )
    dense_count_threshold: bpy.props.IntProperty(
        name="密集数量阈值",
        description="半径内顶点数量达到该值即视为密集（默认 5）",
        default=5,
        min=2,
        max=100
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
