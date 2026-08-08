"""
基础操作符模块
定义基础操作符类和通用方法
"""

import bpy

from .. import utils


def store_result(store, key, data, element_type):
    """
    写入子元素检测结果；结果为空时移除旧键。

    旧实现在「本次检测无问题」时不会写入结果，上一轮结果仍留在字典里，
    「选择」按钮因而会选中已经过期的索引。

    Args:
        store: check_results / optimize_results
        key: 结果键名
        data: 结果数据（字典 {obj: [索引...]}）
        element_type: 元素类型 ('VERT' / 'EDGE' / 'FACE')
    """
    if data:
        store[key] = {'data': data, 'element_type': element_type}
    else:
        store.pop(key, None)


class LowPolyBaseOperator:
    """
    基础操作符类
    提供通用方法和属性

    所有子类默认标记为 REGISTER（支持重做面板）。
    修改场景状态的选择类操作符应在子类中追加 UNDO。

    注意: 这是一个抽象基类,不应该被实例化或注册
    """

    def ensure_object_mode(self, context):
        """
        确保处于物体模式（失败时不抛异常）

        Args:
            context: Blender上下文对象

        Returns:
            bool: 是否处于物体模式
        """
        return utils.ensure_object_mode(context)

    def deselect_all(self, context):
        """
        取消选择所有物体

        Args:
            context: Blender上下文对象
        """
        utils.deselect_all_objects(context)

    def select_elements_in_edit_mode(self, obj, element_type, element_indices):
        """
        在编辑模式下选择元素

        Args:
            obj: 网格对象
            element_type: 元素类型 ('VERT', 'EDGE', 'FACE')
            element_indices: 元素索引列表
        """
        utils.select_elements_in_edit_mode(obj, element_type, element_indices)

    def select_elements_multi_object(self, element_data_dict, element_type):
        """
        在多个物体的编辑模式下选择元素

        Args:
            element_data_dict: 字典 {obj: [element_indices, ...], ...}
            element_type: 元素类型 ('VERT', 'EDGE', 'FACE')

        Returns:
            tuple: (有效物体数, 实际选中元素总数, 跳过的失效物体数)
        """
        return utils.select_elements_multi_object(element_data_dict, element_type)

    def execute_safe(self, context, fn):
        """
        异常安全的 execute 包装器。

        捕获执行过程中所有未预期异常，记录并报告，
        防止操作符中途崩溃导致数据不一致。

        记录到 results dict 的键（成功时）便在此被更新。

        Args:
            context: Blender 上下文
            fn: 实际执行函数 callable(context) → set

        Returns:
            set: Blender 操作符状态
        """
        try:
            return fn(context)
        except Exception as exc:  # noqa: BLE001 - 操作符边界必须兜底
            utils.log_exception("操作符执行失败", exc)
            self.report({'ERROR'}, f"执行出错: {type(exc).__name__}: {exc}")
            return {'CANCELLED'}

    def _execute_sub_element_select(self, context, results_dict, result_key, element_type, label):
        """
        子元素（顶点/边/面/物体）选择操作的通用实现。

        Args:
            context: Blender 上下文
            results_dict: 存储结果的字典（check_results / optimize_results）
            result_key: 结果键名
            element_type: 元素类型 ('VERT' / 'EDGE' / 'FACE' / 'OBJECT')
            label: 中文标签，用于报告消息

        Returns:
            set: Blender 操作符状态
        """
        result = results_dict.get(result_key)
        if not result:
            self.report({'WARNING'}, "请先运行对应的检测")
            return {'CANCELLED'}

        actual_type = result.get('element_type', element_type)
        if actual_type == 'OBJECT':
            data = result.get('objects') or []
        else:
            data = result.get('data') or {}

        if not data:
            self.report({'WARNING'}, f"没有要选择的{label}")
            return {'CANCELLED'}

        self.deselect_all(context)

        if actual_type == 'OBJECT':
            # 过滤已被删除的物体，避免 ReferenceError 造成崩溃
            objects = [obj for obj in data if utils.is_object_alive(obj)]
            skipped = len(data) - len(objects)
            if not objects:
                self.report({'WARNING'}, f"{label}所在的物体已被删除，请重新检测")
                return {'CANCELLED'}

            for obj in objects:
                try:
                    obj.select_set(True)
                except (RuntimeError, TypeError):
                    pass
            try:
                context.view_layer.objects.active = objects[0]
            except (RuntimeError, TypeError, AttributeError):
                pass
            selected_total = len(objects)
        else:
            alive = {
                obj: indices
                for obj, indices in data.items()
                if utils.is_object_alive(obj)
            }
            skipped = len(data) - len(alive)
            if not alive:
                self.report({'WARNING'}, f"{label}所在的物体已被删除，请重新检测")
                return {'CANCELLED'}

            _, selected_total, _ = utils.apply_selection(context, alive, actual_type)

        if selected_total == 0:
            self.report({'WARNING'}, f"没有可在视图中选中的{label}（索引可能已失效，建议重新检测）")
            return {'CANCELLED'}

        if actual_type == 'OBJECT':
            message = f"已选择 {selected_total} 个物体（{label}）"
        else:
            message = f"已选中 {selected_total} 个{label}"
        if skipped:
            message += f"，跳过 {skipped} 个已删除物体"
        self.report({'INFO'}, message)
        return {'FINISHED'}


#: 记录被守卫包装前的原始 execute，key 为操作符类
#: （包装是「就地覆盖类属性」，因此必须显式保存原函数才能还原；
#:   直接 del 会把类体内定义的 execute 一并删掉，导致插件在
#:   停用后重新启用时操作符失效）
_GUARD_ORIGINALS = {}


def install_error_guard(cls):
    """
    为操作符类安装统一的异常守卫。

    将类自身的 ``execute`` 包一层 try/except，避免任何单项检测的
    意外异常导致 Blender 弹出错误或插件状态不一致。必须在
    ``bpy.utils.register_class`` 之前调用。

    .. note::
       包装函数必须严格保持 ``(self, context)`` 两个参数——Blender 会
       检查操作符方法的参数个数，任何多余的（哪怕是带默认值的）参数都会
       导致 ``register_class`` 抛出 ValueError。

    Args:
        cls: bpy.types.Operator 子类

    Returns:
        type: 已安装守卫的类（就地修改）
    """
    if cls in _GUARD_ORIGINALS:
        return cls  # 已安装，保持幂等

    original = cls.__dict__.get('execute')
    if original is None:
        return cls

    cls_name = cls.__name__

    def _guard(original_fn):
        def execute(self, context):
            try:
                return original_fn(self, context)
            except Exception as exc:  # noqa: BLE001 - 操作符边界必须兜底
                utils.log_exception(f"{cls_name} 执行失败", exc)
                self.report({'ERROR'}, f"执行出错: {type(exc).__name__}: {exc}")
                return {'CANCELLED'}
        return execute

    # 不做 functools.wraps（避免 __wrapped__ 干扰 Blender 对方法的参数检查），
    # 只保留文档字符串供开发者查看。
    guarded = _guard(original)
    guarded.__doc__ = original.__doc__
    guarded._lowpoly_guarded = True

    _GUARD_ORIGINALS[cls] = original
    cls.execute = guarded
    return cls


def uninstall_error_guard(cls):
    """
    移除操作符类的异常守卫，**还原**（而非删除）原始的 execute。

    Args:
        cls: bpy.types.Operator 子类
    """
    original = _GUARD_ORIGINALS.pop(cls, None)
    if original is not None:
        cls.execute = original


# 注意: LowPolyBaseOperator是抽象基类,不需要注册
classes = []


def register():
    """注册基础操作符"""
    # 基础类不注册,只提供方法供子类使用
    pass


def unregister():
    """注销基础操作符"""
    pass
