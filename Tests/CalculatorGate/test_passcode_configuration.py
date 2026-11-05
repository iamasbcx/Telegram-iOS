"""验证构建期配置的拒绝规则、摘要格式和修改前备份，不使用真实密码。"""

import hashlib
import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("configure_passcode", ROOT / "tools/configure-calculator-passcode.py")
CONFIG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONFIG)
RELATIVE = Path("submodules/TelegramUI/Sources/CalculatorGate/CalculatorGateConfiguration.swift")


class PasscodeConfigurationTests(unittest.TestCase):
    def test_rejects_non_ascii_short_and_long_input(self):
        for value in ["", "123", "1" * 17, "１２３４", "1234\n", "12 34", "-1234"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                CONFIG.render_configuration(value, "test-salt")

    def test_digest_preserves_leading_zeros_without_plaintext(self):
        value = "00123456789"
        source = CONFIG.render_configuration(value, "test-salt")
        digest_values = re.search(r"digest: \[UInt8\] = \[(.*?)\]", source).group(1)
        digest = bytes(int(item.strip(), 16) for item in digest_values.split(","))
        self.assertEqual(digest, hashlib.sha256(f"test-salt:{value}".encode("ascii")).digest())
        self.assertNotIn(value, source)
        self.assertIn("digitCount = 11", source)

    def test_changes_backup_previous_configuration_and_reject_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            CONFIG.write_configuration(root, "13579")
            original = (root / RELATIVE).read_bytes()
            CONFIG.write_configuration(root, "24680")
            self.assertNotEqual(original, (root / RELATIVE).read_bytes())
            backups = list((root / "备份").rglob("CalculatorGateConfiguration.swift"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            current = (root / RELATIVE).read_bytes()
            with self.assertRaises(ValueError):
                CONFIG.write_configuration(root, "invalid")
            self.assertEqual((root / RELATIVE).read_bytes(), current)
            self.assertEqual(len(list((root / "备份").rglob("CalculatorGateConfiguration.swift"))), 1)


if __name__ == "__main__":
    unittest.main()
