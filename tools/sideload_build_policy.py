#!/usr/bin/env python3
"""约束 LiveContainer 构建的配置、系统权限与打包结构。

策略只作用于显式容器构建，保留应用组、钥匙串及普通媒体访问能力。
这里只验收构建输入和产物，不验证 LiveContainer 宿主或真实设备运行状态。
"""

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping


FORBIDDEN_ENTITLEMENTS = frozenset({
    "aps-environment",
    "com.apple.developer.aps-environment",
    "com.apple.developer.siri",
    "com.apple.developer.associated-domains",
    "com.apple.developer.usernotifications.communication",
    "com.apple.developer.usernotifications.filtering",
    "com.apple.developer.pushkit.unrestricted-voip",
    "com.apple.developer.carplay-messaging",
    "com.apple.developer.in-app-payments",
    "com.apple.developer.applesignin",
    "com.apple.developer.background-tasks.continued-processing.gpu",
})
FORBIDDEN_PREFIXES = ("com.apple.developer.icloud-", "com.apple.developer.ubiquity-")


class SideloadPolicyError(ValueError):
    """对外错误只包含能力名称，不输出完整配置、凭据或权限字典。"""


def validate_container_configuration(configuration: Mapping[str, object]) -> None:
    """侧载入口必须明确选择容器模式，并在编译前关闭 Siri 和 iCloud。"""
    if not isinstance(configuration, dict) or configuration.get("is_container_build") is not True:
        raise SideloadPolicyError("LiveContainer builds must set is_container_build to true.")
    for key in ("enable_siri", "enable_icloud"):
        if configuration.get(key) is not False:
            raise SideloadPolicyError(f"LiveContainer builds must set {key} to false.")


def validate_container_entitlements(entitlements: Mapping[str, object]) -> None:
    """拒绝任何受禁权限声明，包括值为 false 的声明；不改变允许的字典内容。"""
    if not isinstance(entitlements, dict):
        raise SideloadPolicyError("Signed entitlements must be a dictionary.")
    for key in entitlements:
        if not isinstance(key, str):
            raise SideloadPolicyError("Signed entitlement names must be strings.")
        if key in FORBIDDEN_ENTITLEMENTS or key.startswith(FORBIDDEN_PREFIXES):
            raise SideloadPolicyError(f"Unsupported entitlement in LiveContainer build: {key}")


def validate_container_archive_members(names: Iterable[str]) -> None:
    """检查 IPA 内的扩展和 Watch 包，拒绝空目录及非标准位置的 appex。"""
    for name in names:
        parts = PurePosixPath(name.replace("\\", "/")).parts
        if any(part in ("PlugIns", "Watch") or part.endswith(".appex") for part in parts):
            raise SideloadPolicyError("LiveContainer IPA must not contain app extensions or Watch apps.")


def check_configuration_file(path: Path) -> None:
    """读取指定 JSON 并验证；错误不回显 JSON 内容或其中的 API 凭据。"""
    try:
        configuration = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise SideloadPolicyError("Could not read a valid LiveContainer build configuration.") from None
    validate_container_configuration(configuration)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path, help="Path to the LiveContainer build configuration JSON.")
    arguments = parser.parse_args()
    try:
        check_configuration_file(arguments.configuration)
    except SideloadPolicyError as error:
        raise SystemExit(str(error)) from None
    print("LiveContainer build configuration policy passed.")


if __name__ == "__main__":
    main()
