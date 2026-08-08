"""
工具函数模块
提供各种辅助函数和检测算法
"""

import bpy
import bmesh
import traceback
from contextlib import contextmanager


# ---------------------------------------------------------------------------
# 浮点常量（避免魔法数字）
# ---------------------------------------------------------------------------
EPSILON = 1e-6
ZERO_THRESHOLD = 0.0001
DEGENERATE_ANGLE_TOLERANCE = 0.001
CONCAVITY_TOLERANCE = 0.001

#: 批量检测会话中允许缓存的顶点总数上限，避免大场景下内存膨胀
MAX_CACHED_VERTEX_COUNT = 2_000_000

#: 单个物体顶点数超过该值时不再进入批量缓存（避免一次性占用过多内存）
MAX_SINGLE_OBJECT_VERTEX_COUNT = 250_000


# ---------------------------------------------------------------------------
# 通用健壮性工具
# ---------------------------------------------------------------------------


def is_object_alive(obj):
    """
    判断 bpy 结构对象是否仍然有效（未被删除）。

    Blender 中已删除对象的 Python 包装体在访问属性时会抛出
    ``ReferenceError``；检测结果会长期保存物体引用，若用户删除了
    物体后再次点击「选择」，直接使用这些引用会导致操作符崩溃。

    Args:
        obj: 任意 bpy 结构对象（通常是 Object）

    Returns:
        bool: 对象是否仍然有效
    """
    try:
        obj.name
    except (ReferenceError, RuntimeError, AttributeError):
        return False
    return True


def log_exception(message, exc=None):
    """
    将异常以统一格式输出到控制台，便于用户排查问题。

    Args:
        message: 描述信息
        exc: 异常对象（可选，缺省时打印当前异常堆栈）
    """
    prefix = f"[LowpolyCheck] {message}"
    if exc is None:
        print(f"{prefix}: {traceback.format_exc()}")
    else:
        print(f"{prefix}: {type(exc).__name__}: {exc}")
        print(traceback.format_exc())


def _scan_target_mesh_objects(context, only_selected):
    """
    扫描场景，返回本次检测需要处理的网格对象（不做缓存）。

    Args:
        context: Blender 上下文对象
        only_selected: 是否只保留被选中的物体

    Returns:
        list: 网格对象列表
    """
    # 优先使用「视图中可见的对象」；后台模式等上下文缺失时回退到场景对象
    try:
        candidates = list(context.visible_objects)
    except (AttributeError, RuntimeError):
        scene = getattr(context, "scene", None)
        candidates = [obj for obj in scene.objects] if scene else []

    objects = []
    for obj in candidates:
        if obj.type != 'MESH' or obj.data is None:
            continue
        if only_selected:
            try:
                if not obj.select_get():
                    continue
            except (RuntimeError, AttributeError):
                continue
        objects.append(obj)
    return objects


def get_target_mesh_objects(context):
    """
    获取本次检测需要处理的网格对象。

    默认返回视图中所有可见的网格对象；当用户在面板中勾选
    「仅处理选中物体」（``scene.lowpoly.only_selected``）时，
    只返回被选中的可见网格对象。

    若在 ``detection_session()`` 内调用，结果会被会话缓存复用——一次
    「运行全部检查」有十余个检测项，否则每个检测项都要重新遍历一遍
    场景（可见物体列表）。

    Args:
        context: Blender 上下文对象

    Returns:
        list: 待检测的网格对象列表
    """
    props = getattr(getattr(context, "scene", None), "lowpoly", None)
    only_selected = bool(getattr(props, "only_selected", False))

    session = _CURRENT_SESSION
    if session is not None:
        return session.objects(context, only_selected)
    return _scan_target_mesh_objects(context, only_selected)


# 向后兼容别名（旧版本代码/第三方脚本可能仍在引用该名称）
get_visible_mesh_objects = get_target_mesh_objects


# ---------------------------------------------------------------------------
# BMesh 批量会话（性能优化核心）
# ---------------------------------------------------------------------------


def _build_bmesh(mesh):
    """
    由网格数据构建并初始化 BMesh。

    Args:
        mesh: bpy.types.Mesh

    Returns:
        BMesh: 已建立查询表与索引的 BMesh
    """
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    return bm


class BMeshSession:
    """
    批量检测会话。

    一次「运行全部检查」会依次执行十余项检测，旧实现为每一项检测
    的每一个物体都重新构建一次 BMesh——这是最主要的性能瓶颈。
    本会话在同一物体的多次检测之间复用同一个 BMesh 副本，并顺带缓存
    「本次检测的目标物体列表」，避免十余个检测项各自重复遍历场景。

    会话为只读语义：检测算法不会修改网格数据，因此复用是安全的。
    """

    __slots__ = (
        "_cache", "_cached_verts",
        "_objects", "_objects_ctx", "_objects_only_selected",
    )

    def __init__(self):
        self._cache = {}
        self._cached_verts = 0
        self._objects = None
        self._objects_ctx = None
        self._objects_only_selected = None

    def get(self, obj):
        """
        获取物体的 BMesh 副本（优先从缓存取）。

        Args:
            obj: 网格对象

        Returns:
            tuple: (BMesh, owned) —— owned 为 True 表示由会话持有，
                   调用方不得释放；为 False 时调用方需自行释放。
        """
        key = obj.name
        entry = self._cache.get(key)
        if entry is not None:
            return entry[1], True

        vertex_count = len(obj.data.vertices)
        over_budget = (
            vertex_count > MAX_SINGLE_OBJECT_VERTEX_COUNT
            or self._cached_verts + vertex_count > MAX_CACHED_VERTEX_COUNT
        )
        if over_budget:
            return _build_bmesh(obj.data), False

        bm = _build_bmesh(obj.data)
        self._cache[key] = (obj, bm, vertex_count)
        self._cached_verts += vertex_count
        return bm, True

    def objects(self, context, only_selected):
        """
        缓存并返回本次会话的目标物体列表。

        仅在 ``context`` 与 ``only_selected`` 都没变时复用；任一变化即
        重新扫描，避免把过期结果传给检测项。

        Args:
            context: Blender 上下文对象
            only_selected: 是否只处理选中物体

        Returns:
            list: 待检测的网格对象列表
        """
        if (
            self._objects is not None
            and self._objects_ctx is context
            and self._objects_only_selected == only_selected
        ):
            return self._objects

        objects = _scan_target_mesh_objects(context, only_selected)
        self._objects = objects
        self._objects_ctx = context
        self._objects_only_selected = only_selected
        return objects

    def close(self):
        """释放会话内缓存的全部 BMesh。"""
        for entry in self._cache.values():
            try:
                entry[1].free()
            except Exception:  # pragma: no cover - 释放失败不应影响流程
                pass
        self._cache.clear()
        self._cached_verts = 0
        self._objects = None
        self._objects_ctx = None
        self._objects_only_selected = None


#: 当前激活的批量检测会话（None 表示未开启）
_CURRENT_SESSION = None


@contextmanager
def detection_session():
    """
    开启一次批量检测会话。

    在 ``with`` 块内通过 ``bmesh_from_object()`` 获取同一物体的 BMesh 时
    会被复用；离开 ``with`` 块后统一释放，异常安全。

    Examples:
        >>> with detection_session():
        ...     for obj in objects:
        ...         with bmesh_from_object(obj) as bm:
        ...             faces = [f.index for f in bm.faces if len(f.verts) > 4]
    """
    global _CURRENT_SESSION
    previous = _CURRENT_SESSION
    session = BMeshSession()
    _CURRENT_SESSION = session
    try:
        yield session
    finally:
        _CURRENT_SESSION = previous
        session.close()


@contextmanager
def bmesh_from_object(obj):
    """
    上下文管理器：安全创建并确保释放 BMesh 副本。

    若当前处于 ``detection_session()`` 上下文中，则复用会话缓存的
    BMesh（由会话统一释放），大幅减少重复构建开销。

    Args:
        obj: Blender 网格对象

    Yields:
        BMesh: 已构建查询表的 BMesh 对象
    """
    session = _CURRENT_SESSION
    if session is not None and is_object_alive(obj) and obj.data is not None:
        bm, owned = session.get(obj)
        if owned:
            yield bm
            return
        try:
            yield bm
        finally:
            bm.free()
        return

    bm = _build_bmesh(obj.data)
    try:
        yield bm
    finally:
        bm.free()


def create_bmesh_copy(obj):
    """
    从物体创建 BMesh 副本

    .. deprecated::
        请使用 ``bmesh_from_object(obj)`` 上下文管理器，它能保证
        异常发生时 BMesh 也会被释放。

    Args:
        obj: Blender 网格对象

    Returns:
        BMesh: BMesh对象
    """
    return _build_bmesh(obj.data)


def get_collinear_vertices(bm, threshold=0.01):
    """
    检测共线顶点（三点共线）

    原理: 度数恰为 2 的内部顶点，若其两条相邻边几乎共线（方向相反），
          则该顶点是直线上的多余点。

    判据: 两条**单位**边向量的点积绝对值 ``|cos θ|`` 表示方向的对齐程度：
          完全共线时 ``|cos θ| = 1``，偏离直线时随之减小。与
          ``1 - threshold`` 比较，认为偏离不超过阈值弧度即为共线。

    Args:
        bm: BMesh对象
        threshold: 允许偏离直线的最大角度（弧度），越小越严格

    Returns:
        list: 共线顶点的索引列表
    """
    if len(bm.verts) == 0:
        return []

    collinear_verts = []

    for vert in bm.verts:
        # 跳过边界顶点和度数不为2的顶点
        if vert.is_boundary or len(vert.link_edges) != 2:
            continue

        # 获取两条边的向量
        edges = list(vert.link_edges)
        vec1 = edges[0].other_vert(vert).co - vert.co
        vec2 = edges[1].other_vert(vert).co - vert.co

        # 零长度边无法判断方向
        if vec1.length < ZERO_THRESHOLD or vec2.length < ZERO_THRESHOLD:
            continue

        vec1.normalize()
        vec2.normalize()

        # 方向相反即共线：|cos θ| 越接近 1，越接近一条直线
        if abs(vec1.dot(vec2)) > 1.0 - threshold:
            collinear_verts.append(vert.index)

    return collinear_verts


def _vert_neighbors(vert):
    """
    返回与顶点通过边直接相连的邻居顶点集合。

    Args:
        vert: BMesh 顶点

    Returns:
        set: 邻居顶点集合
    """
    return {edge.other_vert(vert) for edge in vert.link_edges}


# ---------------------------------------------------------------------------
# 元素选择与视图操作
# ---------------------------------------------------------------------------


_ELEMENT_COLLECTIONS = {
    'VERT': 'vertices',
    'EDGE': 'edges',
    'FACE': 'polygons',
}


_SELECT_MODE_FLAGS = {
    'VERT': (True, False, False),
    'EDGE': (False, True, False),
    'FACE': (False, False, True),
}


def can_use_view_ops(context):
    """
    判断当前上下文是否允许安全调用依赖窗口的 bpy.ops。

    后台模式（``blender --background``）下 ``context.window`` 为 None，
    此时调用 ``bpy.ops.object.mode_set`` 等会直接抛出 RuntimeError。

    Args:
        context: Blender 上下文对象

    Returns:
        bool: 是否具备窗口上下文
    """
    return getattr(context, "window", None) is not None


def ensure_object_mode(context):
    """
    安全地切换到物体模式（失败时不抛异常）。

    Args:
        context: Blender 上下文对象

    Returns:
        bool: 当前是否处于物体模式
    """
    if getattr(context, "mode", None) == 'OBJECT':
        return True
    if not can_use_view_ops(context):
        return False
    try:
        bpy.ops.object.mode_set(mode='OBJECT')
    except (RuntimeError, TypeError, AttributeError):
        return False
    return getattr(context, "mode", None) == 'OBJECT'


def deselect_all_objects(context):
    """
    取消选择所有物体并切换到物体模式（异常安全）

    Args:
        context: Blender上下文对象
    """
    ensure_object_mode(context)
    if not can_use_view_ops(context):
        return
    try:
        bpy.ops.object.select_all(action='DESELECT')
    except (RuntimeError, TypeError):
        pass


def _clear_mesh_selection(mesh, element_type):
    """清除网格上指定类型元素的全部选择标志"""
    collection = getattr(mesh, _ELEMENT_COLLECTIONS[element_type], None)
    if collection is None:
        return
    for element in collection:
        element.select = False


def _apply_mesh_selection(obj, element_type, indices):
    """
    直接在网格数据上写入选择标志。

    相比旧的 ``bm.to_mesh(obj.data)`` 往返写法，本方式：
      * 不重建网格数据（更安全，不会丢失自定义数据层）
      * 无需构建 BMesh（多物体批量选择时速度提升明显）

    Args:
        obj: 网格对象
        element_type: 元素类型 ('VERT' / 'EDGE' / 'FACE')
        indices: 元素索引序列（越界索引会被忽略）

    Returns:
        int: 实际写入的选择标志数量
    """
    mesh = getattr(obj, "data", None)
    if mesh is None or element_type not in _ELEMENT_COLLECTIONS:
        return 0

    _clear_mesh_selection(mesh, element_type)
    collection = getattr(mesh, _ELEMENT_COLLECTIONS[element_type])
    total = len(collection)

    selected = 0
    for idx in indices:
        if 0 <= idx < total:
            collection[idx].select = True
            selected += 1

    mesh.update()
    return selected


def _set_mesh_select_mode(context, element_type):
    """切换编辑模式下的选择模式（VERT / EDGE / FACE）"""
    flags = _SELECT_MODE_FLAGS.get(element_type)
    if flags is None:
        return
    tool_settings = getattr(context, "tool_settings", None)
    if tool_settings is not None:
        try:
            tool_settings.mesh_select_mode = flags
        except (AttributeError, TypeError):
            pass
    try:
        bpy.ops.mesh.select_mode(type=element_type)
    except (RuntimeError, TypeError):
        pass


def _select_objects_only(context, objects):
    """在物体模式下只选中给定物体，并将最后一个设为活动物体"""
    if not can_use_view_ops(context):
        return
    try:
        bpy.ops.object.select_all(action='DESELECT')
    except (RuntimeError, TypeError):
        pass

    for obj in objects:
        try:
            obj.select_set(True)
        except (RuntimeError, TypeError):
            pass

    try:
        context.view_layer.objects.active = objects[-1]
    except (RuntimeError, TypeError, AttributeError):
        pass


def apply_selection(context, element_data_dict, element_type, enter_edit_mode=True):
    """
    对多个物体应用元素选择（Blender 3.4 推荐做法）。

    流程:
      1. 过滤已被删除的物体（避免 ReferenceError 导致崩溃）
      2. 在物体模式下直接写入网格选择标志（无 BMesh 往返）
      3. 选中全部目标物体并进入编辑模式；Blender 2.8+ 支持多物体
         同时编辑，因此用户可以在编辑模式下直接看到所有物体的选中结果

    Args:
        context: Blender 上下文对象
        element_data_dict: 字典 {obj: [元素索引, ...]}
        element_type: 元素类型 ('VERT' / 'EDGE' / 'FACE')
        enter_edit_mode: 是否尝试进入编辑模式（后台模式会自动跳过）

    Returns:
        tuple: (有效物体数, 实际选中元素总数, 跳过的失效物体数)
    """
    alive_items = [
        (obj, indices)
        for obj, indices in element_data_dict.items()
        if is_object_alive(obj)
    ]
    skipped = len(element_data_dict) - len(alive_items)
    if not alive_items:
        return 0, 0, skipped

    ensure_object_mode(context)

    total_selected = 0
    objects = []
    for obj, indices in alive_items:
        total_selected += _apply_mesh_selection(obj, element_type, indices)
        objects.append(obj)

    _select_objects_only(context, objects)

    if not enter_edit_mode or not can_use_view_ops(context):
        return len(objects), total_selected, skipped

    try:
        context.view_layer.objects.active = objects[-1]
        if getattr(context, "mode", None) != 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='EDIT')
        _set_mesh_select_mode(context, element_type)
    except (RuntimeError, TypeError, AttributeError) as exc:
        # 进入编辑模式失败（例如物体被隐藏）不影响已写入的选择状态
        log_exception("进入编辑模式失败，选择状态已写入物体模式数据", exc)

    return len(objects), total_selected, skipped


def select_elements_in_edit_mode(obj, element_type, element_indices):
    """
    选择单个物体的网格元素（保留旧接口，内部转调 apply_selection）

    Args:
        obj: 网格对象
        element_type: 元素类型 ('VERT', 'EDGE', 'FACE')
        element_indices: 元素索引列表
    """
    if obj is None or not element_indices:
        return
    apply_selection(bpy.context, {obj: list(element_indices)}, element_type)


def select_elements_multi_object(element_data_dict, element_type):
    """
    选择多个物体上的网格元素（保留旧接口，内部转调 apply_selection）。

    .. note::
       旧实现会逐个物体执行 ``bm.to_mesh(obj.data)``，代价高且会
       重建网格数据；新实现直接写入网格选择标志，并利用 Blender 2.8+
       的多物体编辑能力一次性展示全部结果。

    Args:
        element_data_dict: 字典 {obj: [element_indices, ...], ...}
        element_type: 元素类型 ('VERT', 'EDGE', 'FACE')

    Returns:
        tuple: (有效物体数, 实际选中元素总数, 跳过的失效物体数)
    """
    if not element_data_dict:
        return 0, 0, 0
    return apply_selection(bpy.context, element_data_dict, element_type)
