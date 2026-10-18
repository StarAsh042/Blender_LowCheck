"""
界面多语言（i18n）支持

本模块把用户可见的**英文源字符串**翻译为其他语言。

.. important::
   字符串的**源语言必须是英文**。Blender 把 ``en_US`` 当作「源语言」直接
   短路，不会查表——实测：只注册 ``en_US`` 字典、``locale=en_US`` 时，
   查询源串仍原样返回；而只注册 ``de_DE`` 字典、``locale=de_DE`` 时能正常
   命中。因此「英文源串 + ``zh_CN`` 字典」是唯一可行的组合，``en_US`` 键
   在 ``translations_dict`` 中属于死代码（对 ``ja_JP``/``fr_FR`` 也不兜底）。

.. important::
   :func:`register` 必须在属性组 / 操作符 / UI **之前**调用，否则首帧绘制
   时字典尚未就绪，界面会先闪一次英文；:func:`unregister` 则必须在它们
   **之后**调用。

运行时报文（``self.report(...)``）**不会**被 Blender 自动翻译，需显式调用
:func:`translate`。
"""

import bpy

#: 翻译表在 Blender 内的注册键。
TRANSLATION_DOMAIN = "Blender_LowCheck.i18n"

#: 简体中文翻译表：``{英文源串: 中文译文}``。
#:
#: 键必须与代码中的源字符串**逐字符一致**（Blender 做精确匹配）。
#: ``tests/test_i18n.py`` 会遍历已注册的操作符与属性，验证此处无遗漏。
ZH_CN = {
    # ── 属性组 · 网格拓扑计数 ──────────────────────────────────
    "N-gon Faces": "N-gon面数",
    "Number of detected N-gon faces": "检测到的N-gon面数量",
    "Overlapping Faces": "重叠面数",
    "Number of detected overlapping faces": "检测到的重叠面数量",
    "Wrong-normal Faces": "错误法线面数",
    "Number of faces whose normals point inward": "检测到的法线朝内的面数量",
    "Non-manifold Edges": "非流形边数",
    "Number of detected non-manifold edges (shared by 3 or more faces)":
        "检测到的非流形边数量（被3个及以上面共用）",
    "Loose Vertices": "孤立顶点数",
    "Number of vertices not used by any face": "不属于任何面的悬浮顶点数量",
    "Loose Edges": "孤立边数",
    "Number of edges not used by any face": "不属于任何面的悬浮边数量",

    # ── 属性组 · 顶点质量计数 ──────────────────────────────────
    "Unwelded Vertices": "未焊接点数",
    "Number of detected unwelded vertices": "检测到的未焊接点数量",
    "Collinear Vertices": "共线顶点数",
    "Number of detected collinear vertices": "检测到的共线顶点数量",
    "Dense Vertices": "密集顶点数",
    "Number of detected dense vertices": "检测到的密集顶点数量",

    # ── 属性组 · 面质量计数 ────────────────────────────────────
    "Degenerate Edges": "退化边数",
    "Number of detected zero-length edges": "检测到的零长度边数量",
    "Degenerate Faces": "退化面数",
    "Number of detected zero-area faces": "检测到的零面积面数量",
    "Distorted Quads": "扭曲四边面数",
    "Number of detected distorted quads (non-planar quads)":
        "检测到的扭曲四边面数量（不共面的四边面）",
    "Concave Quads": "内凹四边面数",
    "Number of detected concave quads": "检测到的内凹四边面数量",

    # ── 属性组 · 场景优化计数 ──────────────────────────────────
    "High-poly Objects": "高面数物体数",
    "Number of detected high-poly objects": "检测到的高面数物体数量",
    "Small Bevels": "小倒角数",
    "Number of detected small bevels": "检测到的小倒角数量",
    "Downward Faces": "朝下面数",
    "Number of detected downward-facing faces": "检测到的朝下面数量",
    "Intersecting Objects": "穿插物体数",
    "Number of detected intersecting objects": "检测到的穿插物体数量",
    "Non-uniformly Scaled Objects": "非均匀缩放物体数",
    "Number of objects with non-uniform scale": "缩放值不统一的物体数量",

    # ── 属性组 · 运行选项 ──────────────────────────────────────
    "Only Selected Objects": "仅处理选中物体",
    "Detect only the currently selected visible mesh objects; "
    "useful for local checks in large scenes":
        "勾选后只检测当前被选中的可见网格物体，适合在大场景中做局部检查",

    # ── 属性组 · 面质量阈值 ────────────────────────────────────
    "Planarity Threshold": "非平面阈值",
    "Distance threshold for quad non-planarity; above this a quad counts as distorted "
    "(default 0.01)":
        "四边面不共面的距离阈值，超过该值视为扭曲四边面（默认 0.01）",
    "Degenerate Edge Threshold": "退化边阈值",
    "Edge length threshold; shorter edges count as degenerate (default 0.0001)":
        "判断零长度边的阈值，边长小于该值视为退化边（默认 0.0001）",
    "Degenerate Face Threshold": "退化面阈值",
    "Face area threshold; smaller faces count as degenerate (default 0.0001)":
        "判断零面积面的阈值，面积小于该值视为退化面（默认 0.0001）",

    # ── 属性组 · 顶点质量阈值 ──────────────────────────────────
    "Collinear Threshold": "共线阈值",
    "Angle threshold in radians for collinear vertices; smaller is stricter (default 0.01)":
        "三点共线的角度阈值（弧度），越小越严格（默认 0.01）",
    "Unwelded Threshold": "未焊接阈值",
    "Distance threshold for unwelded vertices; vertices closer than this and not "
    "joined by an edge are reported (default 0.001)":
        "判断顶点未焊接的距离阈值，两点距离小于该值且无边相连即视为未焊接（默认 0.001）",
    "Dense Distance Threshold": "密集距离阈值",
    "Search radius for dense vertices (default 0.1)":
        "判断顶点密集的搜索半径（默认 0.1）",
    "Dense Count Threshold": "密集数量阈值",
    "Vertex count within the radius that counts as dense (default 5)":
        "半径内顶点数量达到该值即视为密集（默认 5）",

    # ── 属性组 · 场景优化阈值 ──────────────────────────────────
    "Polygon Count Threshold": "面数阈值",
    "Objects with more polygons than this count as high-poly (default 50)":
        "物体面数超过该值即视为高面数物体（默认 50）",
    "Bevel Width Threshold": "倒角宽度阈值",
    "Width threshold for small bevels; faces whose shortest edge is below this are "
    "reported (default 0.1)":
        "小倒角的宽度阈值，最短边小于该值即视为小倒角（默认 0.1）",
    "Downward Area Threshold": "朝下面积阈值",
    "Minimum world-space area for downward faces; 0 checks all (default 0)":
        "检测朝下面的最小面积阈值，0 表示全部检测（默认 0）",
    "Downward Angle Threshold": "朝下角度阈值",
    "Angle threshold in degrees between the face normal and straight down (default 5)":
        "面法线与竖直向下方向的夹角阈值（度），小于此值视为朝下水平面（默认 5）",
    "Intersection Overlap Threshold": "穿插重叠阈值",
    "Minimum bounding-box overlap ratio (0-1) required to report an intersection "
    "(default 0)":
        "最小重叠比例阈值（0-1），包围盒重叠比例超过此值才认为是穿插（默认 0）",

    # ── 检测项注册表：分组标题 / 检测项标题 / 计数文案模板 ──────
    "Mesh Topology": "网格拓扑",
    "Vertex Quality": "顶点质量",
    "Face Quality": "面质量",
    "Scene Optimization": "场景优化",
    "N-gon Faces Check": "N-gon面检查",
    "Overlapping Faces Check": "重叠面检查",
    "Wrong Normals Check (Inward)": "错误法线检查（朝内）",
    "Non-manifold Edges Check": "非流形边检查",
    "Loose Geometry Check": "孤立几何体检查",
    "Unwelded Vertices Check": "未焊接点检查",
    "Collinear Vertices Check": "共线顶点检查",
    "Dense Vertices Check": "密集顶点检测",
    "Degenerate Geometry Check": "退化几何体检查",
    "Distorted Quads Check": "非平面四边面检查",
    "Concave Quads Check": "内凹四边面检查",
    "High-poly Objects Check": "高面数物体检测",
    "Small Bevels Check": "小倒角结构检测",
    "Downward Faces Check": "朝下水平面检测",
    "Intersecting Objects Check": "穿插物体检测",
    "Non-uniformly Scaled Objects Check": "非均匀缩放物体检测",
    "Count: {ngon_count}": "数量: {ngon_count}",
    "Count: {overlapping_face_count}": "数量: {overlapping_face_count}",
    "Count: {wrong_normal_count}": "数量: {wrong_normal_count}",
    "Count: {non_manifold_edge_count}": "数量: {non_manifold_edge_count}",
    "Loose Vertices: {loose_vert_count}  Loose Edges: {loose_edge_count}": "悬浮顶点: {loose_vert_count} 悬浮边: {loose_edge_count}",
    "Count: {unwelded_vert_count}": "数量: {unwelded_vert_count}",
    "Count: {collinear_vert_count}": "数量: {collinear_vert_count}",
    "Count: {dense_vert_count}": "数量: {dense_vert_count}",
    "Degenerate Edges: {degenerate_edge_count}  Degenerate Faces: {degenerate_face_count}": "退化边: {degenerate_edge_count} 退化面: {degenerate_face_count}",
    "Count: {distorted_quad_count}": "数量: {distorted_quad_count}",
    "Count: {concave_quad_count}": "数量: {concave_quad_count}",
    "Count: {high_poly_count}": "数量: {high_poly_count}",
    "Count: {small_bevel_count}": "数量: {small_bevel_count}",
    "Count: {downward_face_count}": "数量: {downward_face_count}",
    "Count: {intersecting_object_count}": "数量: {intersecting_object_count}",
    "Count: {non_uniform_scale_count}": "数量: {non_uniform_scale_count}",

    # ── UI 面板：侧边栏标签 / 标题 / 按钮 / 提示文案 ────────────
    "Lowpoly Tools": "低模工具",
    "Lowpoly Check": "低模质量检查",
    "Check": "检查",
    "Select": "选择",
    "Add-on failed to load, please re-enable it": "插件未正确加载，请重新启用",
    "Detection Scope": "检测范围",
    "Run All Checks": "运行全部检查",
    "Clear Results": "清除结果",
    "Reset All Parameters": "重置所有参数",
    "Total problems: {total}": "问题总数: {total}",
    "No results yet": "暂无检测结果",
    "Note: only selected objects are checked": "提示: 当前仅检测选中物体",
    "Note: items not found clear their previous results": "提示: 未发现的项会清空其历史结果",

    # ── 操作符 · 按钮标签与提示（phase 3）─────────────────────
    "Suggest Dense Vertices": "密集顶点",
    "Suggest High-poly Objects": "高面数物体",
    "Suggest Small Bevels": "小倒角结构",
    "Suggest Downward Faces": "朝下水平面",
    "Suggest Intersecting Objects": "穿插物体",
    "Suggest Non-uniform Scale": "非均匀缩放物体",
    "what.ngon_faces": "N-gon面",
    "what.overlapping_faces": "重叠面",
    "what.wrong_normals": "法线错误的面",
    "what.non_manifold_edges": "非流形边",
    "what.unwelded_vertices": "未焊接点",
    "what.collinear_vertices": "共线顶点",
    "what.distorted_quads": "非平面四边面",
    "what.concave_quads": "内凹四边面",
    "what.dense_vertices": "密集顶点",
    "what.high_poly_objects": "高面数物体",
    "what.small_bevels": "小倒角结构",
    "what.downward_faces": "朝下水平面",
    "what.intersecting_objects": "穿插物体",
    "what.non_uniform_scale": "非均匀缩放物体",
    "Found {count} {what}": "找到 {count} 个{what}",
    "No {what} found": "未找到{what}",
    "Done, but these checks failed: {names}": "完成，但以下检查项失败: {names}",
    "All checks completed": "全部检查已完成",
    "All checks completed ({count} objects)": "全部检查已完成（共 {count} 个物体）",
    "All optimization checks completed ({count} objects)": "所有优化检查已完成（共 {count} 个物体）",
    "Execution error: {type}: {msg}": "执行出错: {type}: {msg}",
    "Please run the corresponding check first": "请先运行对应的检测",
    "No {what} to select": "没有要选择的{what}",
    "The objects containing {what} have been deleted, please re-run the check":
        "{what}所在的物体已被删除，请重新检测",
    "No {what} can be selected in the view (indices may be stale, re-run the check)":
        "没有可在视图中选中的{what}（索引可能已失效，建议重新检测）",
    "Selected {count} objects ({what})": "已选择 {count} 个物体（{what}）",
    "Selected {count} {what}": "已选中 {count} 个{what}",
    ", skipped {count} deleted objects": "，跳过 {count} 个已删除物体",
    "All check results cleared": "已清除所有检测结果",
    'No mesh objects to check (check visibility or the "only selected objects" option)':
        "没有可检测的网格物体（请检查可见性或「仅处理选中物体」选项）",
    "{count} loose vertices": "{count} 个悬浮顶点",
    "{count} loose edges": "{count} 条悬浮边",
    "Found {parts}": "找到 {parts}",
    "No loose geometry found": "未找到孤立几何体",
    "{count} degenerate edges": "{count} 条退化边",
    "{count} degenerate faces": "{count} 个退化面",
    "No degenerate geometry found": "未找到退化几何体",
    "Check N-gon Faces": "检查N-gon面",
    "Detect faces with more than 4 edges": "检查多于4边的面",
    "Select N-gon Faces": "选择N-gon面",
    "Select the N-gon faces found by the check": "选择已检查出的N-gon面",
    "Check Overlapping Faces": "检查重叠面",
    "Detect faces that share all their edges": "检查共用所有边的重叠面",
    "Select Overlapping Faces": "选择重叠面",
    "Select the overlapping faces found by the check": "选择已检查出的重叠面",
    "Check Wrong Normals": "检查错误法线",
    "Detect faces whose normal points against the majority": "检测法线朝向与大多数面相反的面",
    "Select Wrong-normal Faces": "选择错误法线面",
    "Select the inward-facing faces found by the check": "选择已检测出的法线朝内的面",
    "Check Non-manifold Edges": "检查非流形边",
    "Detect edges shared by 3 or more faces": "检测被3个及以上面共用的非流形边",
    "Select Non-manifold Edges": "选择非流形边",
    "Select the non-manifold edges found by the check": "选择已检测出的非流形边",
    "Check Loose Geometry": "检查孤立几何体",
    "Detect loose vertices and edges (not used by any face)": "检测悬浮顶点和悬浮边（不属于任何面的几何体）",
    "Select Loose Geometry": "选择孤立几何体",
    "Select the loose vertices found by the check": "选择已检测出的悬浮顶点",
    "Check Unwelded Vertices": "检查未焊接点",
    "Detect vertices at the same position that are not welded": "检查相同位置下未焊接的点",
    "Select Unwelded Vertices": "选择未焊接点",
    "Select the unwelded vertices found by the check": "选择已检查出的未焊接点",
    "Check Collinear Vertices": "检查共线顶点",
    "Detect wasted points on a straight line (3 collinear points)": "检查直线上的废点（三点共线）",
    "Select Collinear Vertices": "选择共线顶点",
    "Select the collinear vertices found by the check": "选择已检查出的共线顶点",
    "Check Degenerate Geometry": "检查退化几何体",
    "Detect zero-length edges and zero-area faces": "检测零长度边和零面积面",
    "Select Degenerate Geometry": "选择退化几何体",
    "Select degenerate edges; falls back to degenerate faces":
        "选择已检测出的退化边；若没有退化边则选择退化面",
    "Check Distorted Quads": "检查非平面四边面",
    "Detect non-planar quad faces (distorted quads)": "检查不共面的四边面（扭曲四边面）",
    "Select Distorted Quads": "选择非平面四边面",
    "Select the distorted quads found by the check": "选择已检查出的非平面四边面",
    "Check Concave Quads": "检查内凹四边面",
    "Detect concave quad faces": "检查内凹的四边面",
    "Select Concave Quads": "选择内凹四边面",
    "Select the concave quads found by the check": "选择已检查出的内凹四边面",
    "Run all mesh quality and scene optimization checks and update counts":
        "运行全部网格质量和场景优化检查并更新计数",
    "Clear all check results and counts (does not modify the model)":
        "清空所有检测结果与计数（不修改模型）",
    "Detect structures with overly dense vertices": "检测顶点过于密集的结构",
    "Select Dense Vertices": "选择密集顶点",
    "Select the dense vertices found by the check": "选择已检测出的密集顶点",
    "Detect objects with a high face count": "检测面数较高的物体",
    "Select High-poly Objects": "选择高面数物体",
    "Select the high-poly objects found by the check": "选择已检测出的高面数物体",
    "Detect small bevel structures": "检测较小的倒角结构",
    "Select Small Bevels": "选择小倒角结构",
    "Select the small bevels found by the check": "选择已检测出的小倒角结构",
    "Detect horizontal downward-facing faces (may waste faces)": "检测水平朝下的面（可能浪费面数）",
    "Select Downward Faces": "选择朝下水平面",
    "Select the downward faces found by the check": "选择已检测出的朝下水平面",
    "Detect objects that intersect each other": "检测互相穿插的物体",
    "Select Intersecting Objects": "选择穿插物体",
    "Select the intersecting objects found by the check": "选择已检测出的穿插物体",
    "Non-uniform Scale": "非均匀缩放物体",
    "Detect objects with non-uniform scaling": "检测缩放值不统一的物体",
    "Select Non-uniform Scale": "选择非均匀缩放物体",
    "Select the non-uniform scale objects found by the check": "选择已检测出的非均匀缩放物体",
    "Run All Optimization Checks": "运行全部优化检查",
    "Run all optimization checks and update counts": "运行所有优化检查并更新计数",
    "Reset Parameter": "重置参数",
    "Reset the specified parameter to its default": "重置指定参数为默认值",
    "Reset all check and optimization parameters to defaults": "重置所有检查/优化参数为默认值",

}

#: 交给 Blender 的翻译表。``"*"`` 是 Blender 的默认上下文（界面文本）。
TRANSLATIONS = {"zh_CN": {("*", source): target for source, target in ZH_CN.items()}}


def translate(text):
    """
    翻译运行时报文。

    ``self.report(...)`` 的输出不会被 Blender 自动翻译，必须显式调用本函数。

    Args:
        text: 英文源串（可含 ``{name}`` 占位符）

    Returns:
        str: 当前语言下的译文；未登记或语言为英文时原样返回
    """
    return bpy.app.translations.pgettext_iface(text)


def register():
    """
    注册翻译表。

    先注销可能残留的旧注册，保证反复启用/停用与开发期 reload 时不报
    ``translation ... already registered``。
    """
    unregister()
    bpy.app.translations.register(TRANSLATION_DOMAIN, TRANSLATIONS)


def unregister():
    """注销翻译表（幂等：未注册时调用不抛异常）"""
    try:
        bpy.app.translations.unregister(TRANSLATION_DOMAIN)
    except Exception:  # noqa: BLE001 - 未注册时注销不应阻断停用流程
        pass
