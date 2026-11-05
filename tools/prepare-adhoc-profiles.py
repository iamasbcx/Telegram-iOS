#!/usr/bin/env python3
"""为本地 ad-hoc 构建生成短期自签名 profile；不取得 Apple 授权，也不操作 Keychain。

源资料固定来自仓库的公开 fake-codesigning。输出仅允许放入 build-input 的子目录，
目标必须不存在或为空；临时私钥由 TemporaryDirectory 负责在成功和异常路径中清理。
"""

import argparse
import copy
import os
import plistlib
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


class ProfilePreparationError(RuntimeError):
    """面向调用方的明确失败；错误文本不得携带密钥或命令输出。"""


def run_openssl(executable: Path, arguments: list[str], purpose: str) -> bytes:
    """只通过参数数组启动指定程序；原始 stdout/stderr 仅留在内存，不写入错误日志。"""
    try:
        result = subprocess.run(
            [str(executable), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProfilePreparationError(f"Unable to run OpenSSL for {purpose}.") from error
    if result.returncode != 0:
        raise ProfilePreparationError(
            f"OpenSSL failed during {purpose} (exit {result.returncode}). "
            "OpenSSL 3 with its legacy provider is required to read the bundled PKCS#12."
        )
    return result.stdout


def validate_openssl(executable: Path) -> Path:
    """拒绝 PATH 自动查找、LibreSSL 和其他主版本，避免不同机器静默走不同实现。"""
    if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ProfilePreparationError("--openssl must be an absolute path to an executable file.")
    executable = executable.resolve(strict=True)
    version = run_openssl(executable, ["version"], "version detection").decode("ascii", errors="replace")
    if re.match(r"^OpenSSL 3\.\d+\.\d+(?:\s|$)", version) is None:
        raise ProfilePreparationError("Unsupported crypto implementation; OpenSSL 3.x is required.")
    return executable


def validate_output(project_root: Path, requested: Path) -> Path:
    """按解析后的真实路径检查边界；不允许使用 build-input 本身或覆盖非空目录。"""
    root = project_root.resolve(strict=True)
    allowed = root / "build-input"
    if allowed.resolve() != allowed:
        raise ProfilePreparationError("build-input must not redirect through a symbolic link or junction.")
    candidate = requested if requested.is_absolute() else root / requested
    candidate = candidate.resolve()
    if candidate == allowed or not candidate.is_relative_to(allowed):
        raise ProfilePreparationError("--output must be a child directory inside this project's build-input.")
    if candidate.exists() and (not candidate.is_dir() or any(candidate.iterdir())):
        raise ProfilePreparationError("Refusing to overwrite a non-empty output directory or a file.")
    return candidate


def read_certificate_dates(executable: Path, certificate: Path) -> tuple[datetime, datetime]:
    data = run_openssl(executable, ["x509", "-in", str(certificate), "-noout", "-dates"], "certificate validity inspection")
    try:
        fields = dict(line.split("=", 1) for line in data.decode("ascii").splitlines())
        return tuple(
            datetime.strptime(fields[name], "%b %d %H:%M:%S %Y GMT").replace(tzinfo=timezone.utc)
            for name in ("notBefore", "notAfter")
        )
    except (ValueError, KeyError, UnicodeError) as error:
        raise ProfilePreparationError("OpenSSL returned an unsupported certificate validity format.") from error


def validity_window(now: datetime, not_before: datetime, not_after: datetime) -> tuple[datetime, datetime]:
    """profile 最多有效 30 天，且始终在源证书有效期内；失效证书不能继续续期。"""
    if any(value.tzinfo is None for value in (now, not_before, not_after)):
        raise ProfilePreparationError("Certificate validity checks require timezone-aware UTC dates.")
    created = now.astimezone(timezone.utc).replace(microsecond=0)
    if created < not_before or created >= not_after:
        raise ProfilePreparationError("The bundled signing certificate is expired or not yet valid.")
    return created, min(created + timedelta(days=30), not_after)


def renew_profile(profile: object, certificate_der: bytes, created: datetime, expires: datetime) -> dict:
    """保留标识、entitlements 和 app groups，只更新证书、日期及对应的有效天数。"""
    if not isinstance(profile, dict) or not isinstance(profile.get("UUID"), str) or not profile["UUID"]:
        raise ProfilePreparationError("A source profile has no valid UUID.")
    entitlements = profile.get("Entitlements")
    if not isinstance(entitlements, dict) or not isinstance(entitlements.get("application-identifier"), str) or not entitlements["application-identifier"]:
        raise ProfilePreparationError("A source profile has no application-identifier entitlement.")
    if not certificate_der or expires <= created:
        raise ProfilePreparationError("The replacement certificate or validity window is invalid.")
    updated = copy.deepcopy(profile)
    # plist 日期使用无时区的 UTC 表示，兼容构建机的 Python 3.9+ plistlib。
    updated["CreationDate"] = created.astimezone(timezone.utc).replace(tzinfo=None)
    updated["ExpirationDate"] = expires.astimezone(timezone.utc).replace(tzinfo=None)
    updated["DeveloperCertificates"] = [certificate_der]
    updated["TimeToLive"] = int(((expires - created).total_seconds() + 86399) // 86400)
    return updated


def decode_profile(executable: Path, source: Path, command: str = "cms") -> dict:
    # -noverify 只跳过公开自签证书的信任链；仍验证 CMS 内容签名，不使用 -nosigs。
    data = run_openssl(executable, [command, "-verify", "-inform", "DER", "-noverify", "-in", str(source)], "profile signature verification")
    try:
        profile = plistlib.loads(data)
    except (ValueError, plistlib.InvalidFileException) as error:
        raise ProfilePreparationError("A provisioning profile does not contain a valid plist.") from error
    if not isinstance(profile, dict):
        raise ProfilePreparationError("A provisioning profile must contain a plist dictionary.")
    return profile


def prepare_profiles(project_root: Path, requested_output: Path, openssl: Path) -> tuple[Path, int, datetime]:
    """先生成、复验全部 profile，再发布目录；失败时不会留下半成品输出或 PEM 私钥。"""
    output = validate_output(project_root, requested_output)
    executable = validate_openssl(openssl)
    source = project_root.resolve(strict=True) / "build-system" / "fake-codesigning"
    source_profiles = sorted((source / "profiles").glob("*.mobileprovision"))
    if not source_profiles or not (source / "certs" / "SelfSigned.p12").is_file():
        raise ProfilePreparationError("The bundled fake-codesigning sources are missing.")
    allowed = project_root.resolve(strict=True) / "build-input"
    allowed.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".adhoc-profiles-", dir=allowed) as temporary:
        stage = Path(temporary)
        certificate_pem = stage / "certificate.pem"
        private_key_pem = stage / "private-key.pem"
        common = ["pkcs12", "-legacy", "-in", str(source / "certs" / "SelfSigned.p12"), "-passin", "pass:"]
        # 原始公开容器使用 RC2；明确启用 OpenSSL 3 的 legacy provider 解包，不做版本降级。
        run_openssl(executable, [*common, "-clcerts", "-nokeys", "-out", str(certificate_pem)], "certificate extraction")
        run_openssl(executable, [*common, "-nocerts", "-noenc", "-out", str(private_key_pem)], "private key extraction")
        private_key_pem.chmod(0o600)
        certificate_der = run_openssl(executable, ["x509", "-in", str(certificate_pem), "-outform", "DER"], "certificate conversion")
        if certificate_der != (source / "certs" / "Public.cer").read_bytes():
            raise ProfilePreparationError("SelfSigned.p12 and Public.cer contain different certificates.")
        not_before, not_after = read_certificate_dates(executable, certificate_pem)
        created, expires = validity_window(datetime.now(timezone.utc), not_before, not_after)
        publish = stage / "publish"
        (publish / "profiles").mkdir(parents=True)
        (publish / "certs").mkdir()
        for original in source_profiles:
            updated = renew_profile(decode_profile(executable, original), certificate_der, created, expires)
            payload = stage / "profile.plist"
            payload.write_bytes(plistlib.dumps(updated, fmt=plistlib.FMT_XML, sort_keys=False))
            destination = publish / "profiles" / original.name
            run_openssl(executable, [
                "cms", "-sign", "-binary", "-nodetach", "-outform", "DER", "-md", "sha256",
                "-in", str(payload), "-signer", str(certificate_pem), "-inkey", str(private_key_pem),
                "-out", str(destination),
            ], "profile signing")
            # 同时验证 CMS 以及 Make.py 实际使用的 smime 读取路径，确保内容逐字段保留。
            if decode_profile(executable, destination) != updated or decode_profile(executable, destination, "smime") != updated:
                raise ProfilePreparationError("Generated profile verification changed its payload.")
        validate_output(project_root, output)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.rmdir()  # 仅删除已再次确认为空的目标；并发新增文件会让 rmdir 明确失败。
        publish.rename(output)
    return output, len(source_profiles), expires


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare temporary self-signed profiles for an ad-hoc IPA build; no Apple account or Keychain changes.")
    parser.add_argument("--output", required=True, type=Path, help="Empty output directory inside this project's build-input.")
    parser.add_argument("--openssl", required=True, type=Path, help="Absolute path to OpenSSL 3, including its legacy provider.")
    arguments = parser.parse_args()
    try:
        output, count, expires = prepare_profiles(Path(__file__).resolve().parents[1], arguments.output, arguments.openssl)
    except (ProfilePreparationError, OSError) as error:
        parser.exit(1, f"Error: {error}\n")
    print(f"Prepared {count} self-signed build profiles in {output}; expires {expires.isoformat()}.")
    print("These profiles do not authorize installation on a stock iOS device; re-sign the IPA with your installation tool.")


if __name__ == "__main__":
    main()
