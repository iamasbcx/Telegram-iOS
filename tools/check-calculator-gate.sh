#!/usr/bin/env bash
# 负责无需第三方子模块的计算器入口快速检查，供独立 CI 和完整 IPA 构建复用。
# 每次独占一个检查目录并保留日志；应用入口和登录恢复页仅做静态检查与语法解析，不声称完整类型检查。
set -euo pipefail

if [ "$#" -gt 0 ]; then
  if [ "$#" -eq 1 ] && { [ "$1" = --help ] || [ "$1" = -h ]; }; then
    echo "Usage: bash tools/check-calculator-gate.sh"
    echo "Run capture rules, Python tests, production model tests, iOS device type checks and app/login syntax checks."
    echo "Requires macOS, Xcode and Python 3; does not build the full app or require Git submodules."
    exit 0
  fi
  echo "Unexpected arguments; use --help for usage" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
mkdir -p "$repo_root/_杂项/calculator-checks"
check_dir="$(mktemp -d "$repo_root/_杂项/calculator-checks/run.XXXXXX")"

run_checks() {
  for tool in python3 xcrun; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      echo "Required tool is missing: $tool" >&2
      return 1
    fi
  done

  echo "Checking calculator callback capture rules"
  python3 tools/check-calculator-captures.py || return "$?"

  echo "Running Python configuration and regression tests"
  python3 -m unittest discover -s Tests/CalculatorGate -p 'test_*.py' -v || return "$?"

  echo "Compiling and running the production calculator model"
  xcrun swiftc -warnings-as-errors \
    submodules/TelegramUI/Sources/CalculatorGate/CalculatorModel.swift \
    Tests/CalculatorGate/CalculatorModelTests.swift \
    -o "$check_dir/calculator-model-tests" || return "$?"
  "$check_dir/calculator-model-tests" || return "$?"

  echo "Type-checking calculator Swift sources for arm64 iOS 15 devices"
  local sdk_path
  sdk_path="$(xcrun --sdk iphoneos --show-sdk-path)" || return "$?"
  xcrun swiftc -swift-version 5 -warnings-as-errors -typecheck \
    -sdk "$sdk_path" \
    -target arm64-apple-ios15.0 \
    submodules/TelegramUI/Sources/CalculatorGate/*.swift || return "$?"

  echo "Parsing app entry and login recovery syntax; full-module type checking remains part of the IPA build"
  xcrun swiftc -frontend -parse \
    submodules/TelegramUI/Sources/AppDelegate.swift \
    submodules/AuthorizationUI/Sources/AuthorizationSequencePaymentScreen.swift || return "$?"
  echo "Calculator quick checks passed"
}

echo "Calculator check log: $check_dir/checks.log"
run_checks 2>&1 | tee "$check_dir/checks.log"
