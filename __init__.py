"""
低模质量检查插件 (Lowpoly Check)
作者: StarAsh042
功能: 检查低多边形模型质量，覆盖网格拓扑、顶点质量、面质量、场景优化四大维度

版本策略: 自 1.0.0 起遵循语义化版本（主版本 = 不兼容变更，
次版本 = 兼容新增，修订 = 兼容修复）。
"""


bl_info = {
    #: ``bl_info`` 由 Blender 直接从模块源码读取，用于「编辑 > 首选项 > 插件」
    #: 列表与安装界面，**不经过** bpy.app.translations 的查表机制（插件未启用
    #: 时字典尚未注册）。因此这里必须使用英文——与 Blender 官方惯例一致。
    "name": "Lowpoly Check",
    "author": "StarAsh042",
    "version": (1, 0, 0),
    "blender": (3, 4, 0),
    "location": "View3D > Sidebar > Lowpoly Tools",
    "description": "Check low-poly model quality: mesh topology, vertex quality, "
                   "face quality and scene optimization",
    "category": "Mesh",
}


import bpy

from . import i18n
from . import registry
from . import utils
from . import properties
from . import operators
from . import ui
from .operators import check_operators, optimize_operators


def reload_modules():
    """
    重新加载所有子模块并重新注册（仅用于开发调试）。

    .. important::
       必须遵循「先注销 → 再 reload → 再注册」的顺序。
       ``importlib.reload`` 会在**同一模块命名空间中重新执行源码**，
       从而重新创建全部类对象；而 ``bpy.types`` 中注册的仍然是旧类。
       若只 reload 不注销，会留下三类问题：

       * 旧类成为「已注册但模块中已无引用」的**孤儿**，之后停用无法清理；
       * 再次启用时因 ``bl_idname`` 冲突而注册失败；
       * ``operators.base._GUARD_ORIGINALS`` 被重建为空字典，异常守卫
         「原始 execute」的映射随之丢失。

    Returns:
        list[str]: 已重新加载的模块名称
    """
    import importlib

    from .operators import base as op_base
    from .operators import check_operators as op_check
    from .operators import optimize_operators as op_optimize
    from .operators import reset_operators as op_reset

    # 1) 先用「当前」的类对象干净注销（此时尚未 reload）
    unregister()

    # 2) 按依赖顺序重新加载：i18n 与 registry 无依赖故最先；
    #    check_operators 依赖 optimize_operators，故排在它之后。
    order = [
        i18n,
        registry,
        utils,
        properties,
        op_base,
        op_reset,
        op_optimize,
        op_check,
        operators,
        ui,
    ]
    for module in order:
        importlib.reload(module)

    # 3) 注册 reload 后产生的新类
    register()

    return [module.__name__ for module in order]


@bpy.app.handlers.persistent
def _lowpoly_clear_results_on_load(_dummy):
    """加载新文件或新建文件时清空旧的检查/优化结果，避免悬空的物体引用"""
    check_operators.check_results.clear()
    optimize_operators.optimize_results.clear()


def _unregister_all():
    """
    按依赖倒序注销各子模块，单个模块失败不影响其余模块。

    翻译表排在**最后**注销——它必须活得比面板 / 操作符 / 属性更久，
    否则注销过程中若触发一次重绘，界面文本将失去译文。
    """
    for unregister_fn in (ui.unregister, operators.unregister, properties.unregister,
                          i18n.unregister):
        try:
            unregister_fn()
        except Exception as exc:  # noqa: BLE001 - 注销必须尽可能完整执行
            utils.log_exception(f"注销 {unregister_fn.__module__} 失败", exc)


def register():
    """
    注册插件。

    流程: 属性组 → 操作符 → UI 面板 → 文件加载回调。
    若中途失败则回滚已注册的部分并抛出异常，避免残留半注册状态。
    """
    if getattr(register, "_lowpoly_registered", False):
        # Blender 在 reload 场景下可能重复调用，这里直接忽略
        return

    try:
        # 翻译表必须最先注册：面板 / 操作符 / 属性注册后可能立刻被绘制，
        # 字典尚未就绪时会先闪一次英文（A1 依赖拓扑序）。
        i18n.register()
        properties.register()
        operators.register()
        ui.register()
    except Exception:
        _unregister_all()
        raise

    if _lowpoly_clear_results_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_lowpoly_clear_results_on_load)

    register._lowpoly_registered = True


def unregister():
    """注销插件（幂等，可安全重复调用）"""
    if _lowpoly_clear_results_on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_lowpoly_clear_results_on_load)

    _unregister_all()
    # 尽力清理内核缓存目录。内核已被加载时扩展文件正被进程锁定、删不掉，
    # 属预期（Windows 硬限制），cleanup_kernel_cache 内部会吞掉这类错误。
    utils.cleanup_kernel_cache()
    register._lowpoly_registered = False


if __name__ == "__main__":
    register()
