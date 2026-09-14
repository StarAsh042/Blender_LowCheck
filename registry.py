"""
检测项注册表（单一数据源）

本模块把「一个检测项」的全部元信息集中到一处声明，用于统一驱动：

* 侧边栏面板的分组、行标题、图标、按钮与阈值滑杆（``ui.py``）
* 「运行全部检查 / 运行全部优化检查」的执行清单与顺序（``operators/*``）
* 结果汇总的计数属性集合（``ui._count_problems``）
* 「清除结果」需要复位的计数属性（``operators/base.py``）

这样「新增一个检测项」只需在 :data:`CHECKS` 中登记一行（外加检测函数
与两个操作符类），而不必再去 6~7 个地方手工同步。

.. note::
   本模块**只存放元数据**，不导入 ``operators`` 或 ``bpy``，以避免
   与操作符模块形成循环导入。检测函数与操作符类仍各自定义在
   ``operators/check_operators.py`` 与 ``operators/optimize_operators.py``
   中，由它们按 :data:`CHECKS` 的顺序装配流水线。
"""

from collections import namedtuple

#: 面板分组：``(分组键, 分组标题, 分组图标)``，顺序即面板显示顺序。
GROUPS = (
    ("topology", "网格拓扑", "MESH_DATA"),
    ("vertex", "顶点质量", "VERTEXSEL"),
    ("face", "面质量", "FACESEL"),
    ("scene", "场景优化", "SCENE_DATA"),
)

#: 检测项声明。
#:
#: * ``key``            —— 结果键 / 检测函数标识（全局唯一）
#: * ``owner``          —— ``'check'`` / ``'optimize'``，决定计数属性归属哪个模块
#: * ``group``          —— 所属分组（:data:`GROUPS` 的键）
#: * ``label``          —— 面板行标题
#: * ``icon``           —— 面板图标
#: * ``element``        —— 检测结果的元素类型 ``VERT`` / ``EDGE`` / ``FACE`` / ``OBJECT``
#: * ``count_props``    —— 该检测项更新的计数属性（面板显示 + 清除结果）
#: * ``count_template`` —— 面板数量文案模板，``{属性名}`` 会被实际值替换
#: * ``check_op``       —— 「检查」按钮的操作符 idname
#: * ``select_op``      —— 「选择」按钮的操作符 idname
#: * ``thresholds``     —— 面板上暴露的阈值参数名（可重置）
CheckSpec = namedtuple("CheckSpec", (
    "key",
    "owner",
    "group",
    "label",
    "icon",
    "element",
    "count_props",
    "count_template",
    "check_op",
    "select_op",
    "thresholds",
))

#: 全部检测项（顺序即面板与「运行全部检查」的执行顺序）。
CHECKS = (
    # ── 网格拓扑 ────────────────────────────────────────────────
    CheckSpec(
        "ngon_faces", "check", "topology", "N-gon面检查", "MESH_DATA", "FACE",
        ("ngon_count",), "数量: {ngon_count}",
        "lowpoly.check_ngon_faces", "lowpoly.select_ngon_faces", (),
    ),
    CheckSpec(
        "overlapping_faces", "check", "topology", "重叠面检查", "FACESEL", "FACE",
        ("overlapping_face_count",), "数量: {overlapping_face_count}",
        "lowpoly.check_overlapping_faces", "lowpoly.select_overlapping_faces", (),
    ),
    CheckSpec(
        "wrong_normals", "check", "topology", "错误法线检查（朝内）", "NORMALS_FACE", "FACE",
        ("wrong_normal_count",), "数量: {wrong_normal_count}",
        "lowpoly.check_wrong_normals", "lowpoly.select_wrong_normals", (),
    ),
    CheckSpec(
        "non_manifold_edges", "check", "topology", "非流形边检查", "EDGESEL", "EDGE",
        ("non_manifold_edge_count",), "数量: {non_manifold_edge_count}",
        "lowpoly.check_non_manifold_edges", "lowpoly.select_non_manifold_edges", (),
    ),
    CheckSpec(
        "loose_geometry", "check", "topology", "孤立几何体检查", "OUTLINER_OB_MESH", "VERT",
        ("loose_vert_count", "loose_edge_count"),
        "悬浮顶点: {loose_vert_count} 悬浮边: {loose_edge_count}",
        "lowpoly.check_loose_geometry", "lowpoly.select_loose_geometry", (),
    ),

    # ── 顶点质量 ────────────────────────────────────────────────
    CheckSpec(
        "unwelded_vertices", "check", "vertex", "未焊接点检查", "VERTEXSEL", "VERT",
        ("unwelded_vert_count",), "数量: {unwelded_vert_count}",
        "lowpoly.check_unwelded_vertices", "lowpoly.select_unwelded_vertices",
        ("unwelded_threshold",),
    ),
    CheckSpec(
        "collinear_vertices", "check", "vertex", "共线顶点检查", "VERTEXSEL", "VERT",
        ("collinear_vert_count",), "数量: {collinear_vert_count}",
        "lowpoly.check_collinear_vertices", "lowpoly.select_collinear_vertices",
        ("collinear_threshold",),
    ),
    CheckSpec(
        "dense_vertices", "optimize", "vertex", "密集顶点检测", "VERTEXSEL", "VERT",
        ("dense_vert_count",), "数量: {dense_vert_count}",
        "lowpoly.suggest_dense_vertices", "lowpoly.select_dense_vertices",
        ("dense_distance_threshold", "dense_count_threshold"),
    ),

    # ── 面质量 ──────────────────────────────────────────────────
    CheckSpec(
        "degenerate_geometry", "check", "face", "退化几何体检查", "MESH_DATA", "EDGE",
        ("degenerate_edge_count", "degenerate_face_count"),
        "退化边: {degenerate_edge_count} 退化面: {degenerate_face_count}",
        "lowpoly.check_degenerate_geometry", "lowpoly.select_degenerate_geometry",
        ("degenerate_edge_threshold", "degenerate_face_threshold"),
    ),
    CheckSpec(
        "distorted_quads", "check", "face", "非平面四边面检查", "MESH_DATA", "FACE",
        ("distorted_quad_count",), "数量: {distorted_quad_count}",
        "lowpoly.check_distorted_quads", "lowpoly.select_distorted_quads",
        ("distortion_threshold",),
    ),
    CheckSpec(
        "concave_quads", "check", "face", "内凹四边面检查", "MESH_DATA", "FACE",
        ("concave_quad_count",), "数量: {concave_quad_count}",
        "lowpoly.check_concave_quads", "lowpoly.select_concave_quads", (),
    ),

    # ── 场景优化 ────────────────────────────────────────────────
    CheckSpec(
        "high_poly_objects", "optimize", "scene", "高面数物体检测", "MESH_DATA", "OBJECT",
        ("high_poly_count",), "数量: {high_poly_count}",
        "lowpoly.suggest_high_poly_objects", "lowpoly.select_high_poly_objects",
        ("polycount_threshold",),
    ),
    CheckSpec(
        "small_bevels", "optimize", "scene", "小倒角结构检测", "FACESEL", "FACE",
        ("small_bevel_count",), "数量: {small_bevel_count}",
        "lowpoly.suggest_small_bevels", "lowpoly.select_small_bevels",
        ("bevel_width_threshold",),
    ),
    CheckSpec(
        "downward_faces", "optimize", "scene", "朝下水平面检测", "FACESEL", "FACE",
        ("downward_face_count",), "数量: {downward_face_count}",
        "lowpoly.suggest_downward_faces", "lowpoly.select_downward_faces",
        ("downward_area_threshold", "downward_angle_threshold"),
    ),
    CheckSpec(
        "intersecting_objects", "optimize", "scene", "穿插物体检测", "OBJECT_DATA", "OBJECT",
        ("intersecting_object_count",), "数量: {intersecting_object_count}",
        "lowpoly.suggest_intersecting_objects", "lowpoly.select_intersecting_objects",
        ("intersect_overlap_threshold",),
    ),
    CheckSpec(
        "non_uniform_scale", "optimize", "scene", "非均匀缩放物体检测", "OBJECT_DATA", "OBJECT",
        ("non_uniform_scale_count",), "数量: {non_uniform_scale_count}",
        "lowpoly.suggest_non_uniform_scale", "lowpoly.select_non_uniform_scale", (),
    ),
)

#: 不属于任何单项检测的全局操作符（由面板顶部按钮直接调用）。
GLOBAL_OPS = (
    "lowpoly.run_all_checks",
    "lowpoly.clear_results",
    "lowpoly.reset_param",
    "lowpoly.reset_all_params",
    "lowpoly.run_all_optimization_checks",
)

#: 检测项键 → 声明，便于按 key 查找。
BY_KEY = {spec.key: spec for spec in CHECKS}


def checks_in_group(group_key):
    """
    返回指定分组下的检测项（保持 :data:`CHECKS` 中的声明顺序）。

    Args:
        group_key: 分组键（:data:`GROUPS` 中的第一项）

    Returns:
        tuple[CheckSpec, ...]: 该分组内的检测项
    """
    return tuple(spec for spec in CHECKS if spec.group == group_key)


def count_properties(owner=None):
    """
    汇总检测项更新的计数属性。

    Args:
        owner: 可选，``'check'`` / ``'optimize'``；为 ``None`` 时返回全部

    Returns:
        tuple[str, ...]: 计数属性名（去重、保持声明顺序）
    """
    names = []
    for spec in CHECKS:
        if owner is not None and spec.owner != owner:
            continue
        for name in spec.count_props:
            if name not in names:
                names.append(name)
    return tuple(names)


def threshold_parameters():
    """
    汇总面板上暴露的全部阈值参数名（去重、保持声明顺序）。

    Returns:
        tuple[str, ...]: 阈值参数名
    """
    names = []
    for spec in CHECKS:
        for name in spec.thresholds:
            if name not in names:
                names.append(name)
    return tuple(names)


def all_operator_ids():
    """
    返回注册表引用的全部操作符 idname（含全局操作符）。

    Returns:
        tuple[str, ...]: 操作符 idname
    """
    ids = []
    for spec in CHECKS:
        for name in (spec.check_op, spec.select_op):
            if name not in ids:
                ids.append(name)
    for name in GLOBAL_OPS:
        if name not in ids:
            ids.append(name)
    return tuple(ids)
