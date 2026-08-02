"""
低模质量检查插件 (Lowpoly Check)
作者: StarAsh042
功能: 检查低多边形模型质量，覆盖网格拓扑、顶点质量、面质量、场景优化四大维度
"""

bl_info = {
    "name": "低模质量检查 (Lowpoly Check)",
    "author": "StarAsh042",
    "version": (0, 1, 0),
    "blender": (3, 4, 0),
    "location": "View3D > Sidebar > Lowpoly Tools",
    "description": "检查低多边形模型质量，覆盖网格拓扑、顶点质量、面质量、场景优化四大维度",
    "category": "Mesh",
}

import bpy


def register():
    """
    注册插件。

    当前阶段仅建立可被 Blender 识别的入口，子模块将随功能开发逐步接入。
    """
    if getattr(register, "_lowpoly_registered", False):
        # Blender 在 reload 场景下可能重复调用，这里直接忽略
        return

    register._lowpoly_registered = True


def unregister():
    """注销插件（幂等，可安全重复调用）"""
    register._lowpoly_registered = False


if __name__ == "__main__":
    register()
