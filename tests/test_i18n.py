"""
多语言（i18n）支持测试

核心是**翻译完整度**：遍历已注册的 RNA 属性与操作符类，确认每一个用户可见的
源字符串都能在 :data:`i18n.ZH_CN` 中查到。这样新增检测项时若忘了写译文，
测试会直接失败，而不是等用户在界面上发现中英混杂。

.. note::
   本模块自行注册属性组与翻译表（``setUpClass``），不依赖插件整体是否已启用——
   运行器的测试模块执行顺序不保证，依赖外部状态会让测试变得脆弱。

运行方式:
    blender --background --factory-startup --python-exit-code 1 --python tests/run_tests.py
"""

import os
import sys
import unittest

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_DIR = os.path.dirname(PLUGIN_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import bpy  # noqa: E402

from Blender_LowCheck import i18n  # noqa: E402
from Blender_LowCheck import properties  # noqa: E402
from Blender_LowCheck import registry  # noqa: E402
from Blender_LowCheck import ui  # noqa: E402


def _missing(entries, label):
    """返回 entries 中未登记的源串清单"""
    return [f"{label} = {text!r}" for text in entries if text and text not in i18n.ZH_CN]


def _own_properties():
    """
    仅返回**本插件声明**的属性。

    ``bl_rna.properties`` 还包含 Blender 内置项（如 ``name``、``rna_type``），
    它们不属于本插件、也无需翻译，必须按 ``__annotations__`` 过滤掉。

    .. note::
       必须通过 ``properties.LowPolyProperties`` **动态**取类，不能在模块顶层
       ``from ... import LowPolyProperties`` 缓存引用——``importlib.reload``
       会在同一模块对象里重新执行源码并生成**新的类对象**，而缓存下来的旧类
       已被注销、``bl_rna`` 为空，会让本测试静默空转。
    """
    cls = properties.LowPolyProperties
    declared = set(cls.__annotations__)
    return [
        prop for prop in cls.bl_rna.properties
        if prop.identifier in declared
    ]


class TestTranslationCoverage(unittest.TestCase):
    """每个用户可见的源字符串都必须有 zh_CN 译文。"""

    @classmethod
    def setUpClass(cls):
        # 属性组的 bl_rna 只有在注册后才存在
        properties.register()
        i18n.register()

    def test_own_properties_are_found(self):
        """自检：过滤后应当拿到本插件的全部属性，避免过滤器写错导致测试空转"""
        self.assertGreaterEqual(len(_own_properties()), 30)

    def test_all_property_names_translated(self):
        names = [prop.name for prop in _own_properties()]
        self.assertEqual(_missing(names, "name"), [],
                         "以下属性名缺少 zh_CN 译文")

    def test_all_property_descriptions_translated(self):
        descs = [prop.description for prop in _own_properties()]
        self.assertEqual(_missing(descs, "description"), [],
                         "以下属性描述缺少 zh_CN 译文")

    def test_all_registry_labels_translated(self):
        """检测项标题与分组标题（面板上直接显示的文字）"""
        labels = [spec.label for spec in registry.CHECKS]
        labels += [label for _key, label, _icon in registry.GROUPS]
        self.assertEqual(_missing(labels, "label"), [],
                         "以下检测项 / 分组标题缺少 zh_CN 译文")

    def test_all_count_templates_translated(self):
        """面板上的数量文案模板（如 '数量: {ngon_count}'）"""
        templates = [spec.count_template for spec in registry.CHECKS]
        self.assertEqual(_missing(templates, "count_template"), [],
                         "以下数量文案模板缺少 zh_CN 译文")

    def test_panel_label_and_category_translated(self):
        """
        面板标题与**侧边栏标签**。

        ``bl_category`` 决定 N 面板上的选项卡名，用户第一眼就会看到，
        最容易在新增语言时被漏掉。
        """
        panel = ui.LOWPOLY_PT_quality_panel
        for attr in ("bl_label", "bl_category"):
            text = getattr(panel, attr, None)
            self.assertIsNotNone(text, f"面板缺少 {attr}")
            self.assertIn(text, i18n.ZH_CN, f"面板 {attr} = {text!r} 缺少 zh_CN 译文")

    def test_bl_info_is_ascii(self):
        """
        ``bl_info`` 必须是纯英文。

        Blender 直接从模块源码读取 ``bl_info`` 用于「编辑 > 首选项 > 插件」
        列表与安装界面，**不经过** bpy.app.translations 查表（插件未启用时
        字典尚未注册）。因此这里写什么语言，用户就看到什么语言——只能是英文。
        """
        import Blender_LowCheck

        for key in ("name", "description", "location", "category"):
            text = Blender_LowCheck.bl_info.get(key, "")
            self.assertTrue(
                text.isascii(),
                f"bl_info[{key!r}] 含非 ASCII 字符，安装界面将显示中文：{text!r}",
            )

    def test_no_empty_translations(self):
        """译文不得为空串——空译文在界面上会显示成空白，比漏翻更难排查"""
        empty = [src for src, dst in i18n.ZH_CN.items() if not dst.strip()]
        self.assertEqual(empty, [], "以下条目译文为空")


class TestTranslationMechanism(unittest.TestCase):
    """翻译机制本身：注册生效、查表命中、未登记回退、英文原样。"""

    @classmethod
    def setUpClass(cls):
        i18n.register()

    @classmethod
    def tearDownClass(cls):
        i18n.unregister()

    def _with_locale(self, locale):
        """临时切换语言并在结束后还原"""
        view = bpy.context.preferences.view
        previous = view.language
        view.language = locale
        self.addCleanup(setattr, view, "language", previous)
        return bpy.app.translations.locale

    def test_zh_cn_lookup_returns_chinese(self):
        self._with_locale("zh_CN")
        self.assertEqual(
            bpy.app.translations.pgettext_iface("N-gon Faces"), "N-gon面数")
        self.assertEqual(
            bpy.app.translations.pgettext_iface("Only Selected Objects"), "仅处理选中物体")

    def test_english_locale_returns_source(self):
        """en_US 被 Blender 当作源语言短路，必须原样返回英文"""
        self._with_locale("en_US")
        self.assertEqual(
            bpy.app.translations.pgettext_iface("N-gon Faces"), "N-gon Faces")

    def test_unregistered_string_returns_source(self):
        """未登记的字符串必须原样返回，不得抛异常"""
        self._with_locale("zh_CN")
        probe = "__lowpoly_no_such_string__"
        self.assertEqual(bpy.app.translations.pgettext_iface(probe), probe)

    def test_translate_helper_matches_pgettext(self):
        self._with_locale("zh_CN")
        self.assertEqual(i18n.translate("N-gon Faces"),
                         bpy.app.translations.pgettext_iface("N-gon Faces"))

    def test_register_is_idempotent(self):
        """重复注册不得报 already registered（开发期 reload 与反复启停都会触发）"""
        i18n.register()
        i18n.register()
        self._with_locale("zh_CN")
        self.assertEqual(
            bpy.app.translations.pgettext_iface("N-gon Faces"), "N-gon面数")

    def test_unregister_is_idempotent(self):
        """未注册时注销不得抛异常"""
        i18n.unregister()
        i18n.unregister()
        i18n.register()  # 供后续用例使用


if __name__ == "__main__":
    unittest.main(verbosity=2)
