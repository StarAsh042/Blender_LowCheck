"""
工具函数模块
提供各种辅助函数和检测算法
"""

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
