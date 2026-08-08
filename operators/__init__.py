"""
操作符模块
包含所有检查和优化相关的操作符
"""

from . import base
from . import check_operators

#: 注册顺序（先注册的操作符可能被后面的模块引用）
_MODULES = (base, check_operators)


def register():
    """注册所有操作符"""
    for module in _MODULES:
        module.register()


def unregister():
    """注销所有操作符（单个模块失败不影响其余模块）"""
    for module in reversed(_MODULES):
        try:
            module.unregister()
        except Exception as exc:  # noqa: BLE001 - 注销必须尽可能完成
            print(f"[LowpolyCheck] 注销 {module.__name__} 时出错: {exc}")
