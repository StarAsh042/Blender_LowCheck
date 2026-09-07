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

    # ── 面质量：计数 ──────────────────────────────────────────
    degenerate_edge_count: bpy.props.IntProperty(
        name="退化边数",
        default=0,
        description="检测到的零长度边数量"
    )
    degenerate_face_count: bpy.props.IntProperty(
        name="退化面数",
        default=0,
        description="检测到的零面积面数量"
    )
    distorted_quad_count: bpy.props.IntProperty(
        name="扭曲四边面数",
        default=0,
        description="检测到的扭曲四边面数量（不共面的四边面）"
    )
    concave_quad_count: bpy.props.IntProperty(
        name="内凹四边面数",
        default=0,
        description="检测到的内凹四边面数量"
    )

    # ── 场景优化：计数 ──────────────────────────────────────────
    high_poly_count: bpy.props.IntProperty(
        name="高面数物体数",
        default=0,
        description="检测到的高面数物体数量"
    )
    small_bevel_count: bpy.props.IntProperty(
        name="小倒角数",
        default=0,
        description="检测到的小倒角数量"
    )
    downward_face_count: bpy.props.IntProperty(
        name="朝下面数",
        default=0,
        description="检测到的朝下面数量"
    )

    # ── 运行选项 ────────────────────────────────────────────────
    only_selected: bpy.props.BoolProperty(
        name="仅处理选中物体",
        description="勾选后只检测当前被选中的可见网格物体，适合在大场景中做局部检查",
        default=False
    )

    # ── 阈值设置 ────────────────────────────────────────────────
    # 面质量阈值
    distortion_threshold: bpy.props.FloatProperty(
        name="非平面阈值",
        description="四边面不共面的距离阈值，超过该值视为扭曲四边面（默认 0.01）",
        default=0.01,
        min=0.0,
        precision=6,
        step=0.1
    )
    degenerate_edge_threshold: bpy.props.FloatProperty(
        name="退化边阈值",
        description="判断零长度边的阈值，边长小于该值视为退化边（默认 0.0001）",
        default=0.0001,
        min=0.0,
        precision=8,
        step=0.01
    )
    degenerate_face_threshold: bpy.props.FloatProperty(
        name="退化面阈值",
        description="判断零面积面的阈值，面积小于该值视为退化面（默认 0.0001）",
        default=0.0001,
        min=0.0,
        precision=8,
        step=0.01
    )
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
    # 场景优化阈值
    polycount_threshold: bpy.props.IntProperty(
        name="面数阈值",
        description="物体面数超过该值即视为高面数物体（默认 50）",
        default=50,
        min=0,
        max=100000
    )
    bevel_width_threshold: bpy.props.FloatProperty(
        name="倒角宽度阈值",
        description="小倒角的宽度阈值，最短边小于该值即视为小倒角（默认 0.1）",
        default=0.1,
        min=0.0,
        precision=4,
        step=0.1
    )
    downward_area_threshold: bpy.props.FloatProperty(
        name="朝下面积阈值",
        description="检测朝下面的最小面积阈值，0 表示全部检测（默认 0）",
        default=0.0,
        min=0.0,
        precision=4,
        step=0.1
    )
    downward_angle_threshold: bpy.props.FloatProperty(
        name="朝下角度阈值",
        description="面法线与竖直向下方向的夹角阈值（度），小于此值视为朝下水平面（默认 5）",
        default=5.0,
        min=0.0,
        max=90.0,
        precision=1,
        step=1
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
