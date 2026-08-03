"""
基础操作符模块
定义基础操作符类和通用方法
"""

import bpy


class LowPolyBaseOperator:
    """
    基础操作符类
    提供通用方法和属性

    所有子类默认标记为 REGISTER（支持重做面板）。
    修改场景状态的选择类操作符应在子类中追加 UNDO。

    注意: 这是一个抽象基类,不应该被实例化或注册
    """

    bl_options = {'REGISTER'}


# 注意: LowPolyBaseOperator是抽象基类,不需要注册
classes = []


def register():
    """注册基础操作符"""
    # 基础类不注册,只提供方法供子类使用
    pass


def unregister():
    """注销基础操作符"""
    pass
