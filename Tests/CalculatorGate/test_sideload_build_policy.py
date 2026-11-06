"""执行真实配置转换、Bazel 打包表达式和侧载策略，验证容器能力边界。"""

import ast
import importlib.util
import json
import os
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("sideload_build_policy", ROOT / "tools/sideload_build_policy.py")
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


def production_configuration_namespace():
    """只载入生产配置类和解析函数，避开不参与策略测试的 macOS 签名导入。"""
    path = ROOT / "build-system/Make/BuildConfiguration.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in ("BuildConfiguration", "build_configuration_from_json")]
    namespace = {"json": json, "os": os, "sys": sys}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def fake_configuration(container):
    """凭据为测试专用占位值；不把真实配置字典放入断言或异常消息。"""
    return {
        "bundle_id": "example.test", "api_id": "123456", "api_hash": "0" * 32,
        "team_id": "TESTTEAM", "app_center_id": "0", "is_internal_build": "false",
        "is_appstore_build": "true", "appstore_id": "123", "app_specific_url_scheme": "test",
        "premium_iap_product_id": "example.premium", "enable_siri": not container,
        "enable_icloud": not container, "is_container_build": container,
    }


class ConfigurationPolicyTests(unittest.TestCase):
    def test_container_profile_requires_explicit_boolean_capabilities(self):
        configuration = fake_configuration(True)
        POLICY.validate_container_configuration(configuration)
        for key in ("is_container_build", "enable_siri", "enable_icloud"):
            for value in (None, 0, 1, "false", "true", not configuration[key]):
                with self.subTest(key=key, value=value), self.assertRaises(POLICY.SideloadPolicyError):
                    POLICY.validate_container_configuration({**configuration, key: value})
            missing = dict(configuration)
            del missing[key]
            with self.assertRaises(POLICY.SideloadPolicyError):
                POLICY.validate_container_configuration(missing)

    def test_production_parser_requires_new_contract_and_rejects_conflicts(self):
        parse = production_configuration_namespace()["build_configuration_from_json"]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "configuration.json"
            missing = fake_configuration(False)
            del missing["is_container_build"]
            invalid = [missing]
            invalid.extend({**fake_configuration(False), "is_container_build": value} for value in (0, 1, "false", None))
            invalid.extend({**fake_configuration(True), key: True} for key in ("enable_siri", "enable_icloud"))
            for configuration in invalid:
                path.write_text(json.dumps(configuration), encoding="utf-8")
                with self.assertRaises(ValueError):
                    parse(str(path))

    def test_standard_and_container_profiles_generate_real_bazel_variables(self):
        namespace = production_configuration_namespace()
        with tempfile.TemporaryDirectory() as temporary:
            for container in (False, True):
                configuration = namespace["BuildConfiguration"](**fake_configuration(container))
                path = Path(temporary) / "variables.bzl"
                configuration.write_to_variables_file("/test/bazel", False, "development", str(path))
                variables = {}
                exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), variables)
                self.assertIs(variables["telegram_is_container_build"], container)
                self.assertIs(variables["telegram_enable_watch"], not container)
                self.assertIs(variables["telegram_enable_siri"], not container)
                self.assertIs(variables["telegram_enable_icloud"], not container)

    def test_checked_in_profiles_declare_the_correct_environment(self):
        for name in ("calculator-configuration.json", "appstore-configuration.json", "appcenter-configuration.json", "template_minimal_development_configuration.json"):
            configuration = json.loads((ROOT / "build-system" / name).read_text(encoding="utf-8"))
            container = name == "calculator-configuration.json"
            self.assertIs(configuration.get("is_container_build"), container, name)
            if container:
                POLICY.validate_container_configuration(configuration)


class ArtifactPolicyTests(unittest.TestCase):
    def test_allowed_app_groups_keychain_and_debug_scope_are_unchanged(self):
        entitlements = {
            "application-identifier": "TEST.example.test",
            "com.apple.security.application-groups": ["group.example.test"],
            "keychain-access-groups": ["TEST.example.test"],
            "get-task-allow": True,
        }
        original = plistlib.dumps(entitlements)
        POLICY.validate_container_entitlements(entitlements)
        self.assertEqual(plistlib.dumps(entitlements), original)

    def test_system_entitlements_are_rejected_even_when_false(self):
        names = set(POLICY.FORBIDDEN_ENTITLEMENTS) | {"com.apple.developer.icloud-services", "com.apple.developer.ubiquity-kvstore-identifier"}
        for name in names:
            for value in (True, False, [], "development"):
                with self.subTest(name=name, value=value), self.assertRaises(POLICY.SideloadPolicyError):
                    POLICY.validate_container_entitlements({name: value})

    def test_ipa_rejects_extensions_and_watch_including_empty_directories(self):
        for member in ("Payload/Test.app/PlugIns/", "Payload/Test.app/PlugIns/Widget.appex/Info.plist", "Payload/Test.app/Watch/", "Payload/Test.app/Watch/Watch.app/Info.plist", "Payload/Test.app/Other/Hidden.appex/Info.plist", "Payload\\Test.app\\PlugIns\\"):
            with self.subTest(member=member), self.assertRaises(POLICY.SideloadPolicyError):
                POLICY.validate_container_archive_members(["Payload/Test.app/Info.plist", member])
        POLICY.validate_container_archive_members(["Payload/Test.app/Info.plist", "Payload/Test.app/Frameworks/Core.framework/Core", "Payload/Test.app/Resources/watch.png"])


class BazelContainerContractTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / "Telegram/BUILD"
        self.tree = ast.parse(self.path.read_text(encoding="utf-8"))

    def entitlement_fragments(self, container):
        # 执行生产 BUILD 中的权限赋值表达式；测试不复制其条件或权限拼接实现。
        names = {
            "official_apple_pay_merchants", "official_bundle_ids", "store_bundle_ids", "apple_pay_merchants",
            "apple_pay_merchants_fragment", "official_unrestricted_voip_fragment", "unrestricted_voip_fragment",
            "official_carplay_fragment", "carplay_fragment", "icloud_fragment", "associated_domains_fragment",
            "siri_fragment", "aps_fragment", "app_groups_fragment", "official_communication_notifications_fragment",
            "communication_notifications_fragment", "official_notification_filtering_fragment", "notification_filtering_fragment",
            "store_signin_fragment", "signin_fragment", "official_background_gpu_fragment", "background_gpu_fragment",
        }
        nodes = [node for node in self.tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)]
        variables = {
            "telegram_bundle_id": "ph.telegra.Telegraph", "telegram_team_id": "TESTTEAM",
            "telegram_is_container_build": container, "telegram_enable_siri": True,
            "telegram_enable_icloud": True, "telegram_aps_environment": "development",
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(self.path), "exec"), variables)
        fragments = [variables[name] for name in ("aps_fragment", "app_groups_fragment", "siri_fragment", "associated_domains_fragment", "icloud_fragment", "apple_pay_merchants_fragment", "unrestricted_voip_fragment", "carplay_fragment", "communication_notifications_fragment", "notification_filtering_fragment", "signin_fragment", "background_gpu_fragment")]
        return plistlib.loads(("<plist version='1.0'><dict>" + "".join(fragments) + "</dict></plist>").encode())

    def test_real_entitlements_keep_standard_build_and_strip_container_services(self):
        standard = self.entitlement_fragments(False)
        self.assertTrue(standard["com.apple.developer.siri"])
        self.assertEqual(standard["aps-environment"], "development")
        self.assertIn("com.apple.developer.icloud-services", standard)
        container = self.entitlement_fragments(True)
        POLICY.validate_container_entitlements(container)
        self.assertEqual(container["com.apple.security.application-groups"], standard["com.apple.security.application-groups"])
        self.assertEqual(container["application-identifier"], standard["application-identifier"])

    def test_container_cannot_reenable_extensions_or_watch_through_select_flags(self):
        application = next(node.value for node in self.tree.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "ios_application" and any(keyword.arg == "name" and isinstance(keyword.value, ast.Constant) and keyword.value.value == "Telegram" for keyword in node.value.keywords))
        arguments = {keyword.arg: keyword.value for keyword in application.keywords}
        for container in (False, True):
            namespace = {
                "telegram_is_container_build": container, "notificationServiceExtensionVersion": "",
                "select": lambda options: options.get(":embedWatchAppSetting", options["//conditions:default"]),
            }
            extensions = eval(compile(ast.Expression(arguments["extensions"]), str(self.path), "eval"), namespace)
            watch = eval(compile(ast.Expression(arguments["watch_application"]), str(self.path), "eval"), namespace)
            if container:
                self.assertEqual(extensions, [])
                self.assertIsNone(watch)
            else:
                self.assertIn(":IntentsExtension", extensions)
                self.assertEqual(watch, ":TelegramWatchApp")


if __name__ == "__main__":
    unittest.main()
