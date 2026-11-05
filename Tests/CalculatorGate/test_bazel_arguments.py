"""隔离测试生产 Bazel 命令组装，不加载只在 macOS 提供的 VM/签名模块。"""

import ast
import contextlib
import io
import os
import shlex
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parents[2] / "build-system/Make/Make.py"


class BazelArgumentsTests(unittest.TestCase):
    def setUp(self):
        # 直接执行生产类的 AST，替换系统探测和进程执行边界，不复制组装实现。
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        production_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BazelCommandLine")
        self.execute = Mock()
        namespace = {
            "os": os, "shlex": shlex, "subprocess": subprocess,
            "BuildEnvironment": lambda **args: SimpleNamespace(bazel_path=args["bazel_path"]),
            "call_executable": self.execute,
        }
        module = ast.Module(body=[production_class], type_ignores=[])
        exec(compile(module, str(SOURCE), "exec"), namespace)
        self.builder = namespace["BazelCommandLine"]("/test/bazel", False, False, None)
        self.builder.set_configuration("release_arm64")
        self.builder.set_build_number(1)

    def test_adhoc_identity_and_resource_limits_reach_final_build(self):
        flag = "--@build_bazel_rules_apple//apple/build_settings:signing_certificate_name=-"
        self.builder.add_additional_args(f'{flag} --jobs=2 --define="label=value with spaces"')
        with contextlib.redirect_stdout(io.StringIO()):
            self.builder.invoke_build()
        argv = self.execute.call_args.args[0]
        self.assertIn(flag, argv)
        self.assertIn("--jobs=2", argv)
        self.assertIn("--define=label=value with spaces", argv)
        self.assertGreater(argv.index(flag), argv.index("--ios_multi_cpus=arm64"))

    def test_project_generation_receives_the_same_arguments(self):
        self.builder.add_additional_args("--jobs=2 --worker_max_instances=1")
        argv = self.builder.get_project_generation_arguments()
        self.assertEqual(argv[-2:], ["--jobs=2", "--worker_max_instances=1"])

    def test_empty_and_invalid_quoting(self):
        self.builder.add_additional_args(None)
        self.assertEqual(self.builder.additional_args, [])
        with self.assertRaises(ValueError):
            self.builder.add_additional_args('--define="unterminated')


if __name__ == "__main__":
    unittest.main()
