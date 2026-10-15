"""
工具函数模块
提供各种辅助函数和检测算法
"""

import bpy
import bmesh
import traceback
from contextlib import contextmanager
import array
import hashlib
import importlib.util
import os
import shutil
import tempfile
from mathutils import Vector, geometry
from math import radians, cos
from mathutils.kdtree import KDTree


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

    def _release(self, key):
        """释放并移除一个缓存条目，同时归还其占用的顶点预算"""
        entry = self._cache.pop(key, None)
        if entry is None:
            return
        _obj, bm, vertex_count = entry
        try:
            bm.free()
        except Exception:  # pragma: no cover - 释放失败不应影响流程
            pass
        self._cached_verts -= vertex_count

    def get(self, obj):
        """
        获取物体的 BMesh 副本（优先从缓存取）。

        .. note::
           缓存键是对象名。Blender 中对象名唯一，但对象被删除后名字会被
           新对象复用，因此命中时**必须用 ``is`` 校验对象身份**——仅比对
           名字可能返回另一个物体的 BMesh。这里刻意不使用
           ``as_pointer()``：内存地址在对象删除后同样会被复用，不能作为
           稳定标识。

        Args:
            obj: 网格对象

        Returns:
            tuple: (BMesh, owned) —— owned 为 True 表示由会话持有，
                   调用方不得释放；为 False 时调用方需自行释放。
        """
        key = obj.name
        entry = self._cache.get(key)
        if entry is not None:
            cached_obj, cached_bm, _count = entry
            if cached_obj is obj:
                return cached_bm, True
            # 名字被新对象复用：丢弃陈旧条目后重建，绝不返回错误数据
            self._release(key)

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


# ---------------------------------------------------------------------------
# Rust 内核（可选）
# ---------------------------------------------------------------------------
#: Rust 内核模块；未构建扩展时为 None，此时全部算法走纯 Python 回退路径。
_KERNEL = None


#: 内核副本的缓存目录名（位于 Blender 用户 scripts 目录下，**与插件目录分离**）
_KERNEL_CACHE_DIRNAME = "lowcheck_kernel_cache"


def _kernel_cache_dir(create=True):
    """
    返回内核副本的缓存目录——**必须在插件目录之外**。

    为什么需要它：Windows 上**已加载的 .pyd 无法删除**（``os.unlink`` 报
    ``WinError 5 拒绝访问``），而 CPython **从不卸载扩展模块**——即使把它
    从 ``sys.modules`` 移除也无效（已实测：导入前可删、导入后不可删、
    移除引用后仍不可删）。

    而 Blender 卸载插件时会 ``shutil.rmtree`` 整个插件目录。因此只要扩展是
    从插件目录里加载的，用户就会**永远卸载不掉本插件**（报 PermissionError）。

    解法：把扩展复制到插件目录之外再从副本加载。插件目录里的原件从未被
    加载，于是可以被正常删除。

    Args:
        create: 目录不存在时是否创建。**清理缓存时必须传 ``False``**，
            否则会「为了删除而先把目录建出来」。

    Returns:
        str: 缓存目录路径（创建失败时退化为系统临时目录）
    """
    try:
        return bpy.utils.user_resource(
            'SCRIPTS', path=_KERNEL_CACHE_DIRNAME, create=create)
    except Exception:  # noqa: BLE001 - 拿不到用户目录时退化为临时目录
        fallback = os.path.join(tempfile.gettempdir(), _KERNEL_CACHE_DIRNAME)
        if create:
            os.makedirs(fallback, exist_ok=True)
        return fallback


def _same_file_content(first, second):
    """
    判断两个文件内容是否一致（先比大小，再比 SHA256）。

    .. important::
       **不能用 mtime 判断。** ZIP 内的扩展模块时间戳是**构建时间**，而缓存
       副本的 mtime 是首次复制时的当前时间——于是升级插件后，新内核的 mtime
       反而**早于**缓存，``源 > 缓存`` 恒为 False，永远复用旧内核。实测：
       内容已变更但缓存哈希不变。

    Args:
        first: 文件路径
        second: 文件路径

    Returns:
        bool: 内容一致返回 True；任一文件不可读时返回 False
    """
    try:
        if os.path.getsize(first) != os.path.getsize(second):
            return False
        with open(first, 'rb') as fa, open(second, 'rb') as fb:
            return (hashlib.sha256(fa.read()).digest()
                    == hashlib.sha256(fb.read()).digest())
    except OSError:
        return False


def _ensure_kernel_copy(source_path):
    """
    把扩展模块复制到插件目录之外，返回可加载的副本路径。

    仅在副本缺失、或**内容与源文件不一致**时才复制（判据见
    :func:`_same_file_content`），避免每次启动都做无谓的磁盘 IO。

    Args:
        source_path: 插件目录内的扩展模块路径

    Returns:
        str | None: 副本路径；复制失败时返回 None（调用方退化为原地加载）
    """
    target = os.path.join(_kernel_cache_dir(), os.path.basename(source_path))
    try:
        if not os.path.isfile(target) or not _same_file_content(source_path, target):
            shutil.copy2(source_path, target)
        return target
    except OSError as exc:
        log_exception(f"复制内核到缓存目录失败（{target}）", exc)
        return None


def cleanup_kernel_cache():
    """
    尽力清理内核缓存目录（插件注销时调用）。

    .. note::
       内核**已被加载**时，缓存里的扩展文件正被进程锁定，Windows 会拒绝
       删除（``WinError 5``）——这是操作系统的硬限制，不是可以绕过的 bug。
       因此本函数是「尽力而为」：能删的删掉、删不掉的留下，**不抛异常**。

       实际效果：用户若从未跑过检测（内核未加载），缓存可被完全清除；
       若已跑过，则留下一个约 250KB 的 ``.pyd``，需重启 Blender 后手动删除。
    """
    cache_dir = _kernel_cache_dir(create=False)
    if not cache_dir or not os.path.isdir(cache_dir):
        return

    try:
        names = os.listdir(cache_dir)
    except OSError:
        return

    leftover = []
    for name in names:
        path = os.path.join(cache_dir, name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.unlink(path)
        except OSError:
            leftover.append(name)

    if not leftover:
        try:
            os.rmdir(cache_dir)
        except OSError:
            pass


def _load_kernel():
    """
    尝试加载 Rust 内核扩展模块 ``lowcheck_core``。

    扩展模块与插件同级（由 ``tools/build_rust.py`` 产出）。这里按**文件路径**
    直接加载，避免修改 ``sys.path`` 而影响宿主环境。

    .. important::
       加载的是复制到插件目录**之外**的副本，而不是插件目录里的原件——
       否则该文件会被进程锁定，导致插件永远无法被卸载（见
       :func:`_kernel_cache_dir` 的说明）。副本复制失败时退化为原地加载，
       功能不受影响，只是重新出现「卸载前需重启 Blender」的限制。

    Returns:
        模块对象；未找到或加载失败时返回 None
    """
    global _KERNEL
    if _KERNEL is not None:
        return _KERNEL

    here = os.path.dirname(os.path.abspath(__file__))
    for suffix in (".pyd", ".so", ".dylib"):
        source = os.path.join(here, "lowcheck_core" + suffix)
        if not os.path.isfile(source):
            continue
        path = _ensure_kernel_copy(source) or source
        try:
            spec = importlib.util.spec_from_file_location("lowcheck_core", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 - 内核不可用时必须能回退
            log_exception(f"加载 Rust 内核失败（{path}）", exc)
            continue
        _KERNEL = module
        return _KERNEL
    return None


def kernel_available():
    """返回 Rust 内核是否可用。"""
    return _load_kernel() is not None


def kernel_inputs(obj=None, bm=None):
    """
    构造 Rust 内核所需的扁平输入 ``(points, edges, boundary)``。

    优先用 ``foreach_get`` 批量取数，实测比 Python 循环构造 list 快 1.9 倍
    （**含**交给 PyO3 转换后的总耗时：115.63 ms → 60.84 ms；单看摊平环节是
    3.8 倍，但 ``array.array`` 转 ``Vec`` 比 list 贵 4.5 ms，净收益为 1.9 倍）。
    任何环节失败都静默回退到 :func:`_vertex_kernel_inputs`，不影响正确性。

    .. important::
       批量取数依赖一个隐含契约：**``obj.data`` 的顶点顺序必须与 ``bm.verts``
       一致**。当前 :func:`_build_bmesh` 用 ``bm.from_mesh(mesh)``（不应用
       modifier）保证这一点。若将来改用 ``bmesh.from_object``，此处会**静默
       错位**——检测结果全部偏移而不会报错。该契约由
       ``tests/test_kernel_inputs.py`` 的守卫测试守住。

    Args:
        obj: 网格对象。提供时优先走 ``obj.data`` 批量取数；为 None 则直接回退。
        bm: BMesh 对象（必需）。

    Returns:
        tuple: (points, edges, boundary)，语义与 :func:`_vertex_kernel_inputs` 相同
    """
    if bm is None:
        raise ValueError("kernel_inputs 需要 bm 参数")

    mesh = getattr(obj, "data", None)
    if mesh is not None:
        try:
            n_verts = len(mesh.vertices)
            n_edges = len(mesh.edges)
            points = array.array('d', bytes(8 * n_verts * 3))
            mesh.vertices.foreach_get('co', points)
            edges = array.array('i', bytes(4 * n_edges * 2))
            mesh.edges.foreach_get('vertices', edges)
            # 长度校验：foreach_get 在个别 Blender 版本上行为可能不同，
            # 长度不符说明取数不完整，必须回退而不是带着错数据继续。
            if len(points) == n_verts * 3 and len(edges) == n_edges * 2:
                boundary = [bool(vert.is_boundary) for vert in bm.verts]
                return points, edges, boundary
        except Exception as exc:  # noqa: BLE001 - 批量取数失败必须能回退
            log_exception("foreach_get 批量取数失败，回退到 Python 摊平", exc)

    return _vertex_kernel_inputs(bm)


def _vertex_kernel_inputs(bm):
    """
    把 BMesh 摊平为内核所需的扁平数组。

    Args:
        bm: BMesh 对象

    Returns:
        tuple: (points, edges, boundary) —— 点按 ``x, y, z`` 依次排列，
               边按 ``起点索引, 终点索引`` 依次排列
    """
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.verts.index_update()
    bm.edges.index_update()

    points = []
    for vert in bm.verts:
        points.extend((vert.co.x, vert.co.y, vert.co.z))

    edges = []
    for edge in bm.edges:
        edges.extend((edge.verts[0].index, edge.verts[1].index))

    boundary = [bool(vert.is_boundary) for vert in bm.verts]
    return points, edges, boundary


def get_faces_sharing_all_edges(bm, threshold=0.0001):
    """
    检测重叠面（位置重合的面）

    原理: 先用 KDTree + 并查集把「彼此距离小于 ``threshold``」的顶点聚成
          同一个**位置簇**，再以「面的顶点簇编号集合」作为键；键相同的面
          即顶点位置完全重合。

    说明: 旧实现把顶点坐标量化到 threshold 网格后取整做键，当两个重合点
          恰好落在相邻网格边界两侧时会得到不同的键而被漏检（与未焊接点
          检测曾出现的量化边界漏检同源）。位置簇方案不存在该问题，复杂度
          仍为 O(V log V)。

    Args:
        bm: BMesh对象
        threshold: 顶点位置比较的阈值（<= 0 时直接返回空结果）

    Returns:
        list: 重叠面的索引列表
    """
    if len(bm.faces) == 0 or threshold <= 0.0:
        return []

    verts = list(bm.verts)
    if not verts:
        return []

    index_of = {vert: i for i, vert in enumerate(verts)}

    # ── 并查集（路径压缩） ────────────────────────────────────────
    parent = list(range(len(verts)))

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a, b):
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    kd = KDTree(len(verts))
    for i, vert in enumerate(verts):
        kd.insert(vert.co, i)
    kd.balance()

    for i, vert in enumerate(verts):
        for _co, j, _dist in kd.find_range(vert.co, threshold):
            if j != i:
                union(i, j)

    # ── 以「顶点位置簇编号集合」为键分组 ──────────────────────────
    face_keys = {}
    for face in bm.faces:
        key = tuple(sorted({find(index_of[vert]) for vert in face.verts}))
        face_keys.setdefault(key, []).append(face.index)

    overlapping_faces = []
    for face_indices in face_keys.values():
        if len(face_indices) > 1:
            overlapping_faces.extend(face_indices)

    return overlapping_faces


def _edge_loop_direction(face, edge):
    """
    返回面沿着共享边遍历时经过的顶点顺序。

    Args:
        face: BMesh 面
        edge: 与该面相邻的边

    Returns:
        tuple | None: (起点, 终点)，若该面不含此边则返回 None
    """
    verts = face.verts
    count = len(verts)
    start, end = edge.verts
    for i in range(count):
        a = verts[i]
        b = verts[(i + 1) % count]
        if (a is start and b is end) or (a is end and b is start):
            return a, b
    return None


def _faces_winding_consistent(face_a, face_b, edge):
    """
    判断两个共边面的绕序是否一致。

    流形网格中，同一条边被两个面沿相反方向遍历；若两面沿相同方向
    遍历该边，说明其中一个面的法线被翻转了。

    Args:
        face_a: 面 A
        face_b: 面 B
        edge: A、B 的共享边

    Returns:
        bool: 绕序是否一致（无法判断时返回 True，避免误报）
    """
    dir_a = _edge_loop_direction(face_a, edge)
    dir_b = _edge_loop_direction(face_b, edge)
    if dir_a is None or dir_b is None:
        return True
    return dir_a[0] is dir_b[1] and dir_a[1] is dir_b[0]


def _signed_volume(faces, flip_set):
    """
    计算闭合面片集合的有向体积。

    使用散度定理的离散形式：对每个面做扇形三角化，
    V = Σ (v0 · (v1 × v2)) / 6。朝向一致且向外的网格结果为正值。

    Args:
        faces: 面列表
        flip_set: 需要视为反向的面集合

    Returns:
        float: 有向体积
    """
    volume = 0.0
    for face in faces:
        verts = face.verts
        count = len(verts)
        if count < 3:
            continue
        origin = verts[0].co
        sign = -1.0 if face in flip_set else 1.0
        for i in range(1, count - 1):
            volume += sign * origin.cross(verts[i].co).dot(verts[i + 1].co)
    return volume / 6.0


def get_wrong_normal_faces(bm):
    """
    检测法线方向错误（翻转）的面

    原理:
      1. **绕序一致性**：流形网格中，同一条边必须被其两个面沿相反方向
         遍历。以面为单位做广度优先遍历，即可把一个连通分量的所有面
         分成「与起点一致 / 与起点相反」两组，后者即被翻转的面。
         该判据是纯粹拓扑的，不依赖法线朝向的统计假设。
      2. **闭合体的全局朝向**：若连通分量闭合（每条边恰好被 2 个面共用），
         用有向体积判断整体朝向；体积为负说明整体朝内，
         此时应该报告「多数派」那一组。
      3. 非闭合分量无法定义内外，退化为「面积较大的一组视为正确」。

    相比旧实现（面积加权法线投票），本算法：
      * 能稳定检出「单个/少数面被翻转」这类最常见的问题
      * 不会被对称结构（如立方体、平面）的法线抵消所干扰
      * 对凹陷结构不会误报

    Args:
        bm: BMesh对象

    Returns:
        list: 法线翻转的面索引列表（升序）
    """
    if len(bm.faces) == 0:
        return []

    wrong_faces = set()
    visited = set()

    for seed in bm.faces:
        if seed in visited:
            continue

        # ── 广度优先遍历，标记每个面相对起点的翻转奇偶性 ──
        parity = {seed: False}
        component = [seed]
        stack = [seed]
        visited.add(seed)

        while stack:
            face = stack.pop()
            for edge in face.edges:
                # 非流形边（被 3 个及以上面共用）上「绕序一致」本身没有
                # 明确含义，跳过以免产生误报（这类边另有专门检测项）
                if len(edge.link_faces) != 2:
                    continue
                for neighbor in edge.link_faces:
                    if neighbor is face or neighbor in visited:
                        continue
                    same = _faces_winding_consistent(face, neighbor, edge)
                    parity[neighbor] = parity[face] if same else (not parity[face])
                    visited.add(neighbor)
                    component.append(neighbor)
                    stack.append(neighbor)

        group_a = [f for f in component if not parity[f]]
        group_b = [f for f in component if parity[f]]

        component_edges = {edge for face in component for edge in face.edges}
        is_closed = all(len(edge.link_faces) == 2 for edge in component_edges)

        if not group_b:
            # 整个分量绕序自洽：只有闭合体才可能「整体朝内」
            if is_closed:
                volume = _signed_volume(component, set())
                if volume < -EPSILON:
                    wrong_faces.update(face.index for face in component)
            continue

        wrong_group = None
        if is_closed:
            # 假设 group_a 朝外，计算整体有向体积
            volume = _signed_volume(component, set(group_b))
            if volume < -EPSILON:
                # 体积为负 → group_a 才是朝内的错误组
                wrong_group = group_a
            elif volume > EPSILON:
                wrong_group = group_b
            else:
                # 体积接近 0（退化/零厚度），退回面积比较
                is_closed = False

        if wrong_group is None and not is_closed:
            area_a = sum(face.calc_area() for face in group_a)
            area_b = sum(face.calc_area() for face in group_b)
            if area_b < area_a:
                wrong_group = group_b
            elif area_a < area_b:
                wrong_group = group_a
            elif len(group_b) < len(group_a):
                wrong_group = group_b
            elif len(group_a) < len(group_b):
                wrong_group = group_a
            # 完全对称（面积与面数都相同）时结果无意义，宁可不报
        if wrong_group is None:
            continue

        wrong_faces.update(face.index for face in wrong_group)

    return sorted(wrong_faces)


def get_non_manifold_edges(bm):
    """
    检测非流形边

    原理: 被 3 个及以上面共用的边是非流形边，会导致烘焙错误和导出异常。

    Args:
        bm: BMesh 对象

    Returns:
        list: 非流形边的索引列表
    """
    if len(bm.edges) == 0:
        return []

    non_manifold = []
    for edge in bm.edges:
        if len(edge.link_faces) >= 3:
            non_manifold.append(edge.index)
    return non_manifold


def get_loose_geometry(bm):
    """
    检测孤立几何体（悬浮顶点和悬浮边）

    原理: 不属于任何面的顶点和边是建模残留垃圾，
          影响导出文件大小和引擎导入效率。

    Args:
        bm: BMesh 对象

    Returns:
        tuple: (loose_vert_indices, loose_edge_indices)
    """
    loose_verts = []
    loose_edges = []

    for vert in bm.verts:
        if not vert.link_faces:
            loose_verts.append(vert.index)

    for edge in bm.edges:
        if not edge.link_faces:
            loose_edges.append(edge.index)

    return loose_verts, loose_edges


def _unwelded_vertices_py(bm, threshold=0.001):
    """
    检测未焊接的顶点（空间位置重合但没有被边连接）

    原理: 使用 KDTree 做半径查询找出距离小于阈值的顶点对，
          若这些顶点之间不存在边，则说明是「未焊接」的重合点。

    说明: 旧实现采用「量化坐标分桶」，当两个点恰好落在相邻格子
          边界两侧时会漏检；KDTree 方案不存在该问题，复杂度
          O(n log n)，同时省去了重复的 O(n²) 组内两两比较。

    Args:
        bm: BMesh对象
        threshold: 距离阈值（必须大于 0，否则直接返回空结果）

    Returns:
        list: 未焊接顶点的索引列表（升序、去重）
    """
    if len(bm.verts) == 0 or threshold <= 0.0:
        return []

    verts = bm.verts
    kd = KDTree(len(verts))
    for i, vert in enumerate(verts):
        kd.insert(vert.co, i)
    kd.balance()

    unwelded = set()
    for i, vert in enumerate(verts):
        neighbors = None
        for _co, j, _dist in kd.find_range(vert.co, threshold):
            if j == i:
                continue
            if neighbors is None:
                neighbors = _vert_neighbors(vert)
            other = verts[j]
            if other in neighbors:
                continue
            unwelded.add(vert.index)
            unwelded.add(other.index)

    return sorted(unwelded)


def get_unwelded_vertices(bm, threshold=0.001, obj=None):
    """
    检测未焊接的顶点（空间位置重合但没有被边连接）。

    优先调用 Rust 内核；内核不可用或调用失败时回退到
    :func:`_unwelded_vertices_py`。

    Args:
        bm: BMesh对象
        threshold: 距离阈值（必须大于 0，否则直接返回空结果）
        obj: 网格对象。提供时摊平走 ``foreach_get`` 批量取数（见
            :func:`kernel_inputs`）；为 None 则回退到 Python 循环摊平。

    Returns:
        list: 未焊接顶点的索引列表（升序、去重）
    """
    if len(bm.verts) == 0 or threshold <= 0.0:
        return []

    kernel = _load_kernel()
    if kernel is not None:
        try:
            points, edges, _boundary = kernel_inputs(obj, bm)
            return list(kernel.unwelded_vertices(points, edges, threshold))
        except Exception as exc:  # noqa: BLE001 - 内核异常不应中断检测
            log_exception("Rust 内核未焊接点检测失败，回退到纯 Python 实现", exc)

    return _unwelded_vertices_py(bm, threshold)


def _collinear_vertices_py(bm, threshold=0.01):
    """
    检测共线顶点（三点共线）

    原理: 度数恰为 2 的内部顶点，若其两条相邻边几乎共线（方向相反），
          则该顶点是直线上的多余点。

    判据: 两条**单位**边向量的点积绝对值 ``|cos θ|`` 表示方向的对齐程度：
          完全共线时 ``|cos θ| = 1``；偏离直线 α 弧度时 ``|cos θ| = cos(α)``。
          因此「偏离不超过 ``threshold`` 弧度」等价于
          ``|cos θ| >= cos(threshold)``。

    .. note::
       旧实现写作 ``|cos θ| > 1 - threshold``。由于 ``cos(α) ≈ 1 - α²/2``
       只在 α→0 时成立，该**线性近似**远比声明宽松：``threshold = 0.01``
       时实际等价于 8.11°，而文档承诺的是 0.01 rad = 0.573°，灵敏度相差
       约 14 倍；``threshold`` 接近 1.57 时 ``1 - threshold`` 降到 0.43，
       判据恒真，所有度数为 2 的顶点都会被误报为共线。

    Args:
        bm: BMesh对象
        threshold: 允许偏离直线的最大角度（弧度），越小越严格

    Returns:
        list: 共线顶点的索引列表
    """
    if len(bm.verts) == 0:
        return []

    cos_threshold = cos(max(threshold, 0.0))
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
        if abs(vec1.dot(vec2)) >= cos_threshold:
            collinear_verts.append(vert.index)

    return collinear_verts


def get_collinear_vertices(bm, threshold=0.01, obj=None):
    """
    检测共线顶点（三点共线）。

    优先调用 Rust 内核；内核不可用或调用失败时回退到
    :func:`_collinear_vertices_py`。

    Args:
        bm: BMesh对象
        threshold: 允许偏离直线的最大角度（弧度），越小越严格
        obj: 网格对象。提供时摊平走 ``foreach_get`` 批量取数（见
            :func:`kernel_inputs`）；为 None 则回退到 Python 循环摊平。

    Returns:
        list: 共线顶点的索引列表
    """
    if len(bm.verts) == 0:
        return []

    kernel = _load_kernel()
    if kernel is not None:
        try:
            points, edges, boundary = kernel_inputs(obj, bm)
            return list(kernel.collinear_vertices(points, edges, boundary, threshold))
        except Exception as exc:  # noqa: BLE001 - 内核异常不应中断检测
            log_exception("Rust 内核共线检测失败，回退到纯 Python 实现", exc)

    return _collinear_vertices_py(bm, threshold)


def _vert_neighbors(vert):
    """
    返回与顶点通过边直接相连的邻居顶点集合。

    Args:
        vert: BMesh 顶点

    Returns:
        set: 邻居顶点集合
    """
    return {edge.other_vert(vert) for edge in vert.link_edges}


def _dense_vertices_py(bm, distance_threshold=0.1, count_threshold=5):
    """
    检测密集顶点

    原理: 使用KDTree加速空间搜索，查找局部顶点密度过高的区域

    Args:
        bm: BMesh对象
        distance_threshold: 搜索半径
        count_threshold: 顶点数量阈值

    Returns:
        list: 密集顶点的索引列表
    """
    if len(bm.verts) == 0:
        return []

    dense_verts = []

    # 构建KDTree用于快速空间查询
    kd = KDTree(len(bm.verts))

    for i, vert in enumerate(bm.verts):
        kd.insert(vert.co, i)
    kd.balance()

    # 查找每个顶点附近的邻居
    for i, vert in enumerate(bm.verts):
        nearby = kd.find_range(vert.co, distance_threshold)
        # 附近顶点数量超过阈值（包括自己）
        if len(nearby) >= count_threshold + 1:
            dense_verts.append(vert.index)

    return dense_verts


def get_dense_vertices(bm, distance_threshold=0.1, count_threshold=5, obj=None):
    """
    检测密集顶点。

    优先调用 Rust 内核；内核不可用或调用失败时回退到
    :func:`_dense_vertices_py`。

    Args:
        bm: BMesh对象
        distance_threshold: 搜索半径
        count_threshold: 顶点数量阈值
        obj: 网格对象。提供时摊平走 ``foreach_get`` 批量取数（见
            :func:`kernel_inputs`）；为 None 则回退到 Python 循环摊平。

    Returns:
        list: 密集顶点的索引列表
    """
    if len(bm.verts) == 0:
        return []

    kernel = _load_kernel()
    if kernel is not None:
        try:
            points, _edges, _boundary = kernel_inputs(obj, bm)
            return list(kernel.dense_vertices(points, distance_threshold, count_threshold))
        except Exception as exc:  # noqa: BLE001 - 内核异常不应中断检测
            log_exception("Rust 内核密集顶点检测失败，回退到纯 Python 实现", exc)

    return _dense_vertices_py(bm, distance_threshold, count_threshold)


def get_zero_length_edges(bm, threshold=0.0001):
    """
    检测零长度边

    Args:
        bm: BMesh对象
        threshold: 长度阈值

    Returns:
        list: 零长度边的索引列表
    """
    if len(bm.edges) == 0:
        return []

    zero_edges = []
    for edge in bm.edges:
        if edge.calc_length() < threshold:
            zero_edges.append(edge.index)
    return zero_edges


def get_zero_area_faces(bm, threshold=0.0001):
    """
    检测零面积面

    Args:
        bm: BMesh对象
        threshold: 面积阈值

    Returns:
        list: 零面积面的索引列表
    """
    if len(bm.faces) == 0:
        return []

    zero_faces = []
    for face in bm.faces:
        if face.calc_area() < threshold:
            zero_faces.append(face.index)
    return zero_faces


def calculate_face_planarity(face):
    """
    计算四边形的平面度（用于检测扭曲四边面）

    原理: 计算每个顶点到最佳拟合平面的距离，
         距离越大说明四边面越扭曲（不共面）

    Args:
        face: BMesh面对象

    Returns:
        float: 最大偏离距离，0表示完全共面
    """
    if len(face.verts) != 4:
        return 0.0

    verts = [v.co for v in face.verts]

    # 计算面的法线（使用前三点）
    normal = geometry.normal(verts[0], verts[1], verts[2])

    # 前三点共线时回退到另一组三点
    if normal.length_squared < EPSILON:
        normal = geometry.normal(verts[0], verts[2], verts[3])

    # 如果所有点共线则退化，视为共面
    if normal.length_squared < EPSILON:
        return 0.0

    normal.normalize()

    # 计算所有顶点到平面的最大距离
    # 使用第一个顶点作为平面上的参考点
    reference_point = verts[0]

    max_distance = 0.0
    for vert in verts:
        # 计算顶点到平面的距离
        distance = abs((vert - reference_point).dot(normal))
        max_distance = max(max_distance, distance)

    return max_distance


def _is_valid_vector(vec):
    """检查向量是否为有效非零向量（用于避免 angle() 调用崩溃）"""
    return vec.length_squared >= ZERO_THRESHOLD * ZERO_THRESHOLD


def is_face_concave(face):
    """
    检查四边形是否为内凹（凹四边形）

    原理: 内凹四边面有一个内角 >= 180°(π)，等价于
          一个顶点在其余三点构成的三角形内部。

    边界情况:
      - 非四边形 → 直接返回 False
      - 存在退化边（相邻顶点重合）→ 返回 False（退化面无法判断凹凸性）

    尺度无关性: 判定过程中所有容差比较都使用**无量纲**量
    （单位边向量的方向余弦、``|sin θ|``），因此同一形状在不同缩放下的
    结论一致。唯一的例外是「退化边」判据 —— 它沿用与「退化边检查」相同的
    **绝对**长度阈值 ``ZERO_THRESHOLD``（0.0001），因此边长小于该值的面
    会被视为退化面并直接返回 False。

    .. note::
       四条边向量与其长度**预先算好**再进判定循环。

       原实现在循环内现算 ``edge1`` / ``edge2``，而第 ``i`` 轮的 ``edge2``
       恰是第 ``i+1`` 轮的 ``edge1``——8 次向量减法与 8 次开方里各有一半是
       重复计算。摊平后减到 4 次减法 + 4 次开方，**判定逻辑与判据完全不变**。

       另外原实现在循环内还逐边调 ``_is_valid_vector`` 复核零长度——那与下方
       的退化边判据是同一条件（``length_squared >= ZERO_THRESHOLD ** 2``），
       既已提前排除，循环内再复核永不会触发，故一并移除。

    Args:
        face: BMesh面对象

    Returns:
        bool: 如果是内凹四边形返回 True
    """
    if len(face.verts) != 4:
        return False

    verts = [v.co for v in face.verts]

    # 摊平四条边向量与长度，避免循环内重复计算（见上方 note）
    edges = [verts[(i + 1) % 4] - verts[i] for i in range(4)]
    lengths = [edge.length for edge in edges]

    # 边界验证：检查是否有相邻顶点重合（退化边）
    for length in lengths:
        if length * length < ZERO_THRESHOLD * ZERO_THRESHOLD:
            # 退化四边形，无法判断凹凸性
            return False

    # 使用叉积符号法判断凹四边形
    # 对凸四边形，依次取三条边形成的两个叉积方向应一致；
    # 若某组叉积相反，则该四边形为凹四边形。
    prev_sign = 0
    for i in range(4):
        edge1 = edges[i]
        edge2 = edges[(i + 1) % 4]
        len1 = lengths[i]
        len2 = lengths[(i + 1) % 4]

        cross = edge1.cross(edge2)

        # 退化角判据必须**无量纲**：``|cross| / (|e1| * |e2|)`` 等于两边的
        # ``|sin θ|``，与模型尺度无关。若直接拿叉积的模（量纲为长度²）与
        # 固定容差比较，小尺寸面会因叉积天然很小而被误判为「共线角」跳过，
        # 大尺寸面则相反 —— 这正是本函数此前的问题。
        sin_angle = cross.length / (len1 * len2)
        if sin_angle < CONCAVITY_TOLERANCE:
            # 两条边几乎共线，该角的转向无法可靠判断，跳过
            continue

        cross.normalize()
        dot_with_normal = cross.dot(face.normal)

        if abs(dot_with_normal) < CONCAVITY_TOLERANCE:
            # 叉积几乎垂直于面法线（该角处几何退化），跳过
            continue

        sign = 1 if dot_with_normal > 0 else -1

        if prev_sign == 0:
            prev_sign = sign
        elif sign != prev_sign:
            # 叉积方向反转 → 存在大于 180° 的内角 → 凹四边形
            return True

    return False


def get_small_bevels(bm, width_threshold=0.01):
    """
    检测小倒角结构（返回倒角面）

    原理: 倒角面通常是四边形，有两条边较短（倒角宽度），
          连接两个主面。只要最短边小于阈值即认为是小倒角。

    Args:
        bm: BMesh对象
        width_threshold: 倒角宽度阈值

    Returns:
        list: 倒角面的索引列表
    """
    if len(bm.faces) == 0:
        return []

    bevel_faces = []

    for face in bm.faces:
        # 倒角面通常是四边形
        if len(face.verts) != 4:
            continue

        # 找到与这个面相邻的所有面
        adjacent_faces = set()
        for edge in face.edges:
            for linked_face in edge.link_faces:
                if linked_face != face:
                    adjacent_faces.add(linked_face)

        # 倒角面应该连接至少两个面
        if len(adjacent_faces) < 2:
            continue

        # 检查面的边长，找出最短边（倒角宽度）
        edge_lengths = [(edge.calc_length(), edge) for edge in face.edges]
        edge_lengths.sort(key=lambda x: x[0])  # 只按长度排序

        # 只要最短边小于阈值，就认为是小倒角（不限制角度）
        if edge_lengths[0][0] < width_threshold:
            bevel_faces.append(face.index)

    return bevel_faces


def _face_area(face, matrix_world=None):
    """
    计算面的面积。

    Args:
        face: BMesh 面
        matrix_world: 物体的世界变换矩阵。传入后返回**世界空间**面积
            （把顶点变换到世界空间再累加）；为 ``None`` 时返回局部空间面积。

    Returns:
        float: 面积
    """
    if matrix_world is None:
        return face.calc_area()

    coords = [matrix_world @ vert.co for vert in face.verts]
    if len(coords) < 3:
        return 0.0

    # 扇形三角化：以首顶点为基点，累加相邻两边叉积得到向量面积
    origin = coords[0]
    total = Vector((0.0, 0.0, 0.0))
    for i in range(1, len(coords) - 1):
        total += (coords[i] - origin).cross(coords[i + 1] - origin)
    return total.length * 0.5


def get_downward_faces(bm, area_threshold=0.0, angle_threshold=5.0, matrix_world=None):
    """
    检测朝下的水平面

    原理: 面的法线在**世界空间**朝下（与世界 Z 轴负方向点积接近 1）表示朝下。

    .. note::
       BMesh 由 ``obj.data`` 构建，其 ``face.normal`` 与 ``face.calc_area()``
       都是**局部空间**的量。物体一旦被旋转或缩放，两者都与世界中的实际
       朝向、可见尺寸脱钩，判定会同时产生两类错误：漏检（世界空间朝下却
       报不出）与误报（世界空间不朝下却报出）。实测：单位立方体绕 X 轴
       旋转 90° 后，旧实现报出的是世界法线为 ``(0, 1, 0)`` 的侧面，而真正
       朝下的面（世界法线 ``(0, 0, -1)``）被漏掉。

    Args:
        bm: BMesh对象
        area_threshold: 最小面积阈值（**世界空间**面积），0表示全部检测
        angle_threshold: 角度阈值（度），面法线与竖直向下方向的夹角小于此值视为朝下水平面
        matrix_world: 物体的世界变换矩阵。传入后按世界空间判定；为 ``None``
            时退化为局部空间（仅适用于物体无旋转、无缩放的场合）。

    Returns:
        list: 朝下面索引列表
    """
    if len(bm.faces) == 0:
        return []

    downward_faces = []
    down = Vector((0, 0, -1))

    # 将角度阈值转换为余弦值阈值
    cos_threshold = cos(radians(angle_threshold))

    # 法线必须用「逆转置矩阵」变换：只有它在非均匀缩放下仍能给出正确的
    # 法线方向（直接用 3x3 部分会让法线随缩放发生偏斜）。
    normal_matrix = None
    if matrix_world is not None:
        normal_matrix = matrix_world.to_3x3().inverted_safe().transposed()

    for face in bm.faces:
        normal = face.normal
        if normal_matrix is not None:
            normal = (normal_matrix @ normal).normalized()
        # 法线与朝下方向的点积接近1，表示朝下（不使用abs，避免检测到朝上的面）
        dot_product = normal.dot(down)
        if dot_product > cos_threshold:  # 严格朝下
            if area_threshold == 0 or _face_area(face, matrix_world) >= area_threshold:
                downward_faces.append(face.index)

    return downward_faces


def _world_aabb(obj):
    """
    计算物体的世界空间轴对齐包围盒（AABB）。

    Args:
        obj: 网格对象

    Returns:
        tuple: (最小角, 最大角) 两个 Vector
    """
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    min_corner = Vector((
        min(c.x for c in corners),
        min(c.y for c in corners),
        min(c.z for c in corners),
    ))
    max_corner = Vector((
        max(c.x for c in corners),
        max(c.y for c in corners),
        max(c.z for c in corners),
    ))
    return min_corner, max_corner


def _boxes_overlap(min1, max1, min2, max2, overlap_threshold, volume1, volume2):
    """
    判断两个 AABB 是否「足够重叠」。

    重叠比例定义为 ``相交体积 / 较小包围盒体积``。

    Args:
        min1, max1: 包围盒 1 的最小/最大角
        min2, max2: 包围盒 2 的最小/最大角
        overlap_threshold: 最小重叠比例（<= 0 表示只要有接触就算重叠）
        volume1, volume2: 两个包围盒的体积

    Returns:
        bool: 是否判定为重叠（潜在穿插）
    """
    # 三轴 AABB 相交测试（任一分隔轴即可提前否定）
    if (min1.x > max2.x or max1.x < min2.x
            or min1.y > max2.y or max1.y < min2.y
            or min1.z > max2.z or max1.z < min2.z):
        return False

    if overlap_threshold <= 0:
        # 阈值为 0：只要有接触就算穿插
        return True

    overlap_size = Vector((
        min(max1.x, max2.x) - max(min1.x, min2.x),
        min(max1.y, max2.y) - max(min1.y, min2.y),
        min(max1.z, max2.z) - max(min1.z, min2.z),
    ))
    if overlap_size.x <= 0 or overlap_size.y <= 0 or overlap_size.z <= 0:
        return False

    min_volume = min(volume1, volume2)
    if min_volume <= 0:
        return False

    overlap_volume = overlap_size.x * overlap_size.y * overlap_size.z
    return overlap_volume / min_volume >= overlap_threshold


def get_intersecting_objects(context, overlap_threshold=0.0):
    """
    检测穿插物体（基于世界空间包围盒）

    原理: 两个物体的 AABB 相交、且重叠体积占较小包围盒的比例达标时，
          认为它们可能穿插。

    .. note::
       包围盒检测是**保守**判据——它只能说明「可能穿插」，不能证明实际
       网格相交。这是刻意的性能取舍（逐三角求交代价极高）。把
       ``intersect_overlap_threshold`` 调大可以过滤掉「仅边界相切」的误报。

    性能: 旧实现对**每一对**物体都重新计算两遍 8 个角的
    ``matrix_world @ corner``（n 个物体共 O(n²) 次矩阵乘法），且用
    ``list(set(...))`` 去重导致返回顺序不确定。现在：

      * 每个物体的 AABB 只计算一次（O(n)）；
      * 按最小 x 升序做**扫描剪枝**，内层一旦发现 ``min.x`` 已超过当前
        ``max.x`` 即提前终止（x 轴不可能再重叠）；
      * 按场景顺序去重输出，结果**确定可复现**。

    Args:
        context: Blender上下文对象
        overlap_threshold: 最小重叠比例阈值（0-1，0表示只要有接触就算穿插）

    Returns:
        list: 穿插物体列表（按场景顺序去重）
    """
    # 空网格（无顶点）的包围盒退化为原点处的零体积盒，会产生大量误报，直接排除
    objects = [
        obj for obj in get_target_mesh_objects(context)
        if len(obj.data.vertices) > 0
    ]
    if len(objects) < 2:
        return []

    # 物体刚被移动/缩放时，matrix_world 尚未随依赖图刷新，直接读取会得到
    # **过期的变换**，从而算出错误的包围盒（后台模式与脚本调用尤其明显）。
    # 这里主动刷新一次——相对后续的包围盒两两比较，代价可忽略。
    view_layer = getattr(context, "view_layer", None)
    if view_layer is not None:
        try:
            view_layer.update()
        except Exception:  # noqa: BLE001 - 刷新失败不应阻断检测
            pass

    boxes = []
    for obj in objects:
        min_corner, max_corner = _world_aabb(obj)
        size = max_corner - min_corner
        boxes.append((min_corner, max_corner, size.x * size.y * size.z))

    # 宽相位：按最小 x 升序，内层可提前终止
    order = sorted(range(len(boxes)), key=lambda index: boxes[index][0].x)

    hit = [False] * len(boxes)
    for pos in range(len(order)):
        i = order[pos]
        min1, max1, volume1 = boxes[i]
        for next_pos in range(pos + 1, len(order)):
            j = order[next_pos]
            min2, max2, volume2 = boxes[j]
            if min2.x > max1.x:
                # 已按 min.x 升序，后面的物体在 x 轴上不可能再重叠
                break
            if hit[i] and hit[j]:
                continue
            if _boxes_overlap(min1, max1, min2, max2, overlap_threshold, volume1, volume2):
                hit[i] = True
                hit[j] = True

    return [obj for index, obj in enumerate(objects) if hit[index]]


def get_non_uniform_scale_objects(context):
    """
    检测非均匀缩放的物体

    原理: 非均匀缩放（scale.x/y/z 不相等）会导致法线变换错误、
          UV 拉伸异常和碰撞体变形，影响下游管线。

    Args:
        context: Blender 上下文对象

    Returns:
        list: 非均匀缩放的物体列表
    """
    non_uniform = []
    for obj in get_target_mesh_objects(context):
        scale = obj.scale
        if abs(scale.x - scale.y) > EPSILON or abs(scale.y - scale.z) > EPSILON or abs(scale.x - scale.z) > EPSILON:
            non_uniform.append(obj)
    return non_uniform


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


def _clear_mesh_selection(mesh):
    """
    清除网格上顶点 / 边 / 面的**全部**选择标志。

    .. note::
       必须清空全部三种元素，不能只清目标类型。Blender 在进入编辑模式时
       会按当前选择模式做选择传播（flush）：残留的顶点或边只要处于选中
       状态，就会把与之相连的面一并"传染"为选中。只清目标类型时，上一次
       操作遗留的顶点/边选择会把结果放大——例如只想选中 1 个面，进入编辑
       模式后却变成整个网格全选（实测：面 1→6、边 0→12、点 0→8）。
    """
    for collection_name in _ELEMENT_COLLECTIONS.values():
        collection = getattr(mesh, collection_name, None)
        if collection is None:
            continue
        for element in collection:
            element.select = False


def _apply_mesh_selection(obj, element_type, indices):
    """
    直接在网格数据上写入选择标志。

    相比旧的 ``bm.to_mesh(obj.data)`` 往返写法，本方式：
      * 不重建网格数据（更安全，不会丢失自定义数据层）
      * 无需构建 BMesh（多物体批量选择时速度提升明显）

    .. note::
       写入前会清空**全部**元素类型的选择（见 :func:`_clear_mesh_selection`），
       只保留本次写入的目标元素。目标元素的下级元素（面的边与顶点）无需
       手工同步——Blender 在进入编辑模式时会按当前选择模式自动传播。

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

    _clear_mesh_selection(mesh)
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
