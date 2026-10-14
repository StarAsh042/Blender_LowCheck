"""
属性组模块
定义插件的属性组和配置参数

.. note::
   属性的 ``name`` / ``description`` 使用**英文源串**，由 :mod:`i18n` 提供
   中文翻译；``identifier``（属性名本身）一律不变，因此旧 ``.blend`` 文件
   中的阈值与计数读写不受影响。
"""

import bpy


class LowPolyProperties(bpy.types.PropertyGroup):
    """
    低模质量检查属性组
    合并原有的错误检查和优化建议属性，存储所有检测计数和阈值
    """

    # ── 网格拓扑：计数 ──────────────────────────────────────────
    ngon_count: bpy.props.IntProperty(
        name="N-gon Faces",
        default=0,
        description="Number of detected N-gon faces"
    )
    overlapping_face_count: bpy.props.IntProperty(
        name="Overlapping Faces",
        default=0,
        description="Number of detected overlapping faces"
    )
    wrong_normal_count: bpy.props.IntProperty(
        name="Wrong-normal Faces",
        default=0,
        description="Number of faces whose normals point inward"
    )
    non_manifold_edge_count: bpy.props.IntProperty(
        name="Non-manifold Edges",
        default=0,
        description="Number of detected non-manifold edges (shared by 3 or more faces)"
    )
    loose_vert_count: bpy.props.IntProperty(
        name="Loose Vertices",
        default=0,
        description="Number of vertices not used by any face"
    )
    loose_edge_count: bpy.props.IntProperty(
        name="Loose Edges",
        default=0,
        description="Number of edges not used by any face"
    )

    # ── 顶点质量：计数 ──────────────────────────────────────────
    unwelded_vert_count: bpy.props.IntProperty(
        name="Unwelded Vertices",
        default=0,
        description="Number of detected unwelded vertices"
    )
    collinear_vert_count: bpy.props.IntProperty(
        name="Collinear Vertices",
        default=0,
        description="Number of detected collinear vertices"
    )
    dense_vert_count: bpy.props.IntProperty(
        name="Dense Vertices",
        default=0,
        description="Number of detected dense vertices"
    )

    # ── 面质量：计数 ────────────────────────────────────────────
    degenerate_edge_count: bpy.props.IntProperty(
        name="Degenerate Edges",
        default=0,
        description="Number of detected zero-length edges"
    )
    degenerate_face_count: bpy.props.IntProperty(
        name="Degenerate Faces",
        default=0,
        description="Number of detected zero-area faces"
    )
    distorted_quad_count: bpy.props.IntProperty(
        name="Distorted Quads",
        default=0,
        description="Number of detected distorted quads (non-planar quads)"
    )
    concave_quad_count: bpy.props.IntProperty(
        name="Concave Quads",
        default=0,
        description="Number of detected concave quads"
    )

    # ── 场景优化：计数 ──────────────────────────────────────────
    high_poly_count: bpy.props.IntProperty(
        name="High-poly Objects",
        default=0,
        description="Number of detected high-poly objects"
    )
    small_bevel_count: bpy.props.IntProperty(
        name="Small Bevels",
        default=0,
        description="Number of detected small bevels"
    )
    downward_face_count: bpy.props.IntProperty(
        name="Downward Faces",
        default=0,
        description="Number of detected downward-facing faces"
    )
    intersecting_object_count: bpy.props.IntProperty(
        name="Intersecting Objects",
        default=0,
        description="Number of detected intersecting objects"
    )
    non_uniform_scale_count: bpy.props.IntProperty(
        name="Non-uniformly Scaled Objects",
        default=0,
        description="Number of objects with non-uniform scale"
    )

    # ── 运行选项 ────────────────────────────────────────────────
    only_selected: bpy.props.BoolProperty(
        name="Only Selected Objects",
        description="Detect only the currently selected visible mesh objects; "
                    "useful for local checks in large scenes",
        default=False
    )

    # ── 阈值设置 ────────────────────────────────────────────────
    # 面质量阈值
    distortion_threshold: bpy.props.FloatProperty(
        name="Planarity Threshold",
        description="Distance threshold for quad non-planarity; above this a quad "
                    "counts as distorted (default 0.01)",
        default=0.01,
        min=0.0,
        precision=6,
        step=0.1
    )
    degenerate_edge_threshold: bpy.props.FloatProperty(
        name="Degenerate Edge Threshold",
        description="Edge length threshold; shorter edges count as degenerate "
                    "(default 0.0001)",
        default=0.0001,
        min=0.0,
        precision=8,
        step=0.01
    )
    degenerate_face_threshold: bpy.props.FloatProperty(
        name="Degenerate Face Threshold",
        description="Face area threshold; smaller faces count as degenerate "
                    "(default 0.0001)",
        default=0.0001,
        min=0.0,
        precision=8,
        step=0.01
    )

    # 顶点质量阈值
    collinear_threshold: bpy.props.FloatProperty(
        name="Collinear Threshold",
        description="Angle threshold in radians for collinear vertices; "
                    "smaller is stricter (default 0.01)",
        default=0.01,
        min=0.0,
        max=1.57,
        precision=4,
        step=0.01
    )
    unwelded_threshold: bpy.props.FloatProperty(
        name="Unwelded Threshold",
        description="Distance threshold for unwelded vertices; vertices closer than "
                    "this and not joined by an edge are reported (default 0.001)",
        default=0.001,
        min=0.0,
        precision=6,
        step=0.1
    )
    dense_distance_threshold: bpy.props.FloatProperty(
        name="Dense Distance Threshold",
        description="Search radius for dense vertices (default 0.1)",
        default=0.1,
        min=0.0,
        precision=4,
        step=0.1
    )
    dense_count_threshold: bpy.props.IntProperty(
        name="Dense Count Threshold",
        description="Vertex count within the radius that counts as dense (default 5)",
        default=5,
        min=2,
        max=100
    )

    # 场景优化阈值
    polycount_threshold: bpy.props.IntProperty(
        name="Polygon Count Threshold",
        description="Objects with more polygons than this count as high-poly (default 50)",
        default=50,
        min=0,
        max=100000
    )
    bevel_width_threshold: bpy.props.FloatProperty(
        name="Bevel Width Threshold",
        description="Width threshold for small bevels; faces whose shortest edge is "
                    "below this are reported (default 0.1)",
        default=0.1,
        min=0.0,
        precision=4,
        step=0.1
    )
    downward_area_threshold: bpy.props.FloatProperty(
        name="Downward Area Threshold",
        description="Minimum world-space area for downward faces; 0 checks all (default 0)",
        default=0.0,
        min=0.0,
        precision=4,
        step=0.1
    )
    downward_angle_threshold: bpy.props.FloatProperty(
        name="Downward Angle Threshold",
        description="Angle threshold in degrees between the face normal and straight "
                    "down (default 5)",
        default=5.0,
        min=0.0,
        max=90.0,
        precision=1,
        step=1
    )
    intersect_overlap_threshold: bpy.props.FloatProperty(
        name="Intersection Overlap Threshold",
        description="Minimum bounding-box overlap ratio (0-1) required to report an "
                    "intersection (default 0)",
        default=0.0,
        min=0.0,
        max=1.0,
        precision=2,
        step=0.1
    )


#: 阈值参数的命名约定：所有阈值属性名以该后缀结尾，所有计数属性名以
#: ``_count`` 结尾，二者互斥。该约定使默认值可以**自动派生**，避免
#: 手工维护的默认值表与属性声明发生漂移（改了 ``default`` 却忘了同步字典）。
THRESHOLD_SUFFIX = "_threshold"
COUNT_SUFFIX = "_count"

#: 阈值参数默认值 ``{参数名: 默认值}``，由 :func:`register` 依据属性声明
#: 自动填充，供重置操作符与一致性测试使用。
ALL_DEFAULTS = {}


def _populate_defaults():
    """
    从已注册的属性组中读出全部阈值参数的默认值。

    .. note::
       必须在 ``register_class`` 之后调用——``bl_rna`` 只有在类注册后
       才存在。

    Returns:
        dict: ``{参数名: 默认值}``（即 ``ALL_DEFAULTS`` 本身）
    """
    ALL_DEFAULTS.clear()
    for prop in LowPolyProperties.bl_rna.properties:
        if prop.identifier.endswith(THRESHOLD_SUFFIX):
            ALL_DEFAULTS[prop.identifier] = prop.default
    return ALL_DEFAULTS


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
    _populate_defaults()


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
