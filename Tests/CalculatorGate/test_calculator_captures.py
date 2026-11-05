"""确保构建前检查读取生产源码，并能阻止已出现的弱捕获写法回归。"""

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("calculator_capture_check", ROOT / "tools/check-calculator-captures.py")
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class CalculatorCaptureTests(unittest.TestCase):
    def test_production_source_passes(self):
        source = CHECKER.DEFAULT_SOURCE.read_text(encoding="utf-8")
        self.assertEqual(CHECKER.check_source(source, "AppDelegate.swift"), [])

    def test_original_capture_regression_is_rejected_in_production_source(self):
        source = CHECKER.DEFAULT_SOURCE.read_text(encoding="utf-8")
        count = source.count("self.performAfterCalculatorUnlock { [weak self = self] in")
        self.assertGreater(count, 0)
        regressed = source.replace("self.performAfterCalculatorUnlock { [weak self = self] in", "self.performAfterCalculatorUnlock { [weak self] in")
        self.assertEqual(len(CHECKER.check_source(regressed, "AppDelegate.swift")), count)

    def test_multiline_capture_declaration(self):
        source = "self.performAfterCalculatorUnlock {\n    [weak self = self] in\n    self?.open()\n}"
        self.assertEqual(CHECKER.check_source(source, "example.swift"), [])
        self.assertEqual(len(CHECKER.check_source(source.replace("self = self", "self"), "example.swift")), 1)

    def test_strong_capture_is_rejected_with_line_number(self):
        source = "\n    self.performAfterCalculatorUnlock { [self] in\n        self.open()\n    }"
        errors = CHECKER.check_source(source, "example.swift")
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith("example.swift:2: error:"))

    def test_comments_cannot_hide_the_original_capture_regression(self):
        for comment in ("/* note */", "// note\n", "/* outer /* nested */ note */"):
            with self.subTest(comment=comment):
                source = f"self.performAfterCalculatorUnlock {{ {comment} [weak self] in\n    self?.open()\n}}"
                self.assertEqual(len(CHECKER.check_source(source, "example.swift")), 1)
                self.assertEqual(CHECKER.check_source(source.replace("[weak self]", "[weak self = self]"), "example.swift"), [])

    def test_unterminated_capture_comment_is_rejected(self):
        source = "self.performAfterCalculatorUnlock { /* unfinished"
        self.assertEqual(len(CHECKER.check_source(source, "example.swift")), 1)

    def test_context_only_callback(self):
        source = "self.performAfterCalculatorUnlock {\n    context.openNotificationSettings()\n}"
        self.assertEqual(CHECKER.check_source(source, "example.swift"), [])

    def test_unrecognized_source_structure_does_not_silently_pass(self):
        self.assertEqual(len(CHECKER.check_source("", "empty.swift")), 1)


if __name__ == "__main__":
    unittest.main()
