#!/usr/bin/env python3
"""在编译前设置计算器数字密码；不接受命令行明文，不把密码写进日志。"""

import getpass
import hashlib
import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path


def render_configuration(passcode: str, salt: str) -> str:
    """生成固定校验值；这不是聊天数据库加密，也不能阻止离线穷举。"""
    if not re.fullmatch(r"[0-9]{4,16}", passcode):
        raise ValueError("Passcode must contain 4 to 16 ASCII digits.")
    digest = hashlib.sha256(f"{salt}:{passcode}".encode("ascii")).digest()
    values = ", ".join(f"0x{value:02x}" for value in digest)
    return f'''import CryptoKit
import Foundation

/// 编译期固定密码的校验值，由 tools/configure-calculator-passcode.py 生成。
/// 仅用于入口访问控制；短数字密码可被离线枚举，不作为数据加密密钥。
enum CalculatorGateConfiguration {{
    private static let salt = "{salt}"
    private static let digitCount = {len(passcode)}
    private static let digest: [UInt8] = [{values}]

    static func matches(_ candidate: String) -> Bool {{
        let bytes = Array(candidate.utf8)
        guard bytes.count == self.digitCount, bytes.allSatisfy({{ $0 >= 48 && $0 <= 57 }}) else {{
            return false
        }}
        let actual = SHA256.hash(data: Data((self.salt + ":" + candidate).utf8))
        var difference: UInt8 = 0
        for (left, right) in zip(actual, self.digest) {{
            difference |= left ^ right
        }}
        return difference == 0
    }}
}}
'''


def write_configuration(root: Path, passcode: str) -> None:
    """先备份旧配置再写入；备份失败时中止，不能绕过备份覆盖。"""
    source = render_configuration(passcode, secrets.token_hex(16))
    relative = Path("submodules/TelegramUI/Sources/CalculatorGate/CalculatorGateConfiguration.swift")
    target = root / relative
    if target.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = root / "备份" / f"calculator-passcode-{stamp}" / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8", newline="\n")


def main() -> None:
    passcode = getpass.getpass("New numeric passcode (4-16 digits): ")
    if passcode != getpass.getpass("Confirm passcode: "):
        raise SystemExit("Passcodes do not match; no files changed.")
    try:
        write_configuration(Path(__file__).resolve().parents[1], passcode)
    except (ValueError, OSError) as error:
        raise SystemExit(str(error)) from error
    print("Calculator passcode configuration updated. Rebuild the app to apply it.")


if __name__ == "__main__":
    main()
