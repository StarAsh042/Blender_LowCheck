"""
属性组模块
定义插件的属性组和配置参数
"""

import bpy


class LowPolyProperties(bpy.types.PropertyGroup):
    """
    低模质量检查属性组
    存储检测计数、运行选项与阈值参数
    """

    # ── 运行选项 ────────────────────────────────────────────────
    only_selected: bpy.props.BoolProperty(
        name="仅处理选中物体",
        description="勾选后只检测当前被选中的可见网格物体，适合在大场景中做局部检查",
        default=False
    )


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
