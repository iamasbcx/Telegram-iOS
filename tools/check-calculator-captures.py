#!/usr/bin/env python3
"""在完整编译前检查计算器延迟回调的显式弱捕获约定，不替代 Swift 类型检查。"""

import argparse
from pathlib import Path
import re
import sys


DEFAULT_SOURCE = Path(__file__).resolve().parents[1] / "submodules/TelegramUI/Sources/AppDelegate.swift"
GATE_CALL = re.compile(r"^[ \t]*self\.performAfterCalculatorUnlock\s*\{", re.MULTILINE)
EXPLICIT_WEAK_SELF = re.compile(r"\[\s*weak\s+self\s*=\s*self\s*\]\s*in\b")


def skip_leading_comments(text: str) -> str:
    """跳过捕获列表前的空白及 Swift 可嵌套注释，避免插入注释后漏掉旧写法。"""
    while True:
        text = text.lstrip()
        if text.startswith("//"):
            text = text.partition("\n")[2]
        elif text.startswith("/*"):
            depth = 1
            for token in re.finditer(r"/\*|\*/", text[2:]):
                depth += 1 if token.group() == "/*" else -1
                if depth == 0:
                    text = text[token.end() + 2:]
                    break
            else:
                raise ValueError("unterminated comment before calculator callback capture")
        else:
            return text


def check_source(source: str, source_name: str) -> list[str]:
    """检查 gate 调用处的捕获列表，返回带源码位置的错误；不分析闭包体或其他 Swift 语义。

    存储的回调显式使用 [weak self = self]，避免嵌套强捕获诊断及持有 AppDelegate。
    仅引用 context 的无捕获列表回调不受此规则限制，仍由完整编译检查其闭包体。
    """
    calls = list(GATE_CALL.finditer(source))
    if not calls:
        return [f"{source_name}: error: no calculator gate callbacks found; update the preflight check for the new source structure"]
    errors = []
    for call in calls:
        line = source.count("\n", 0, call.start()) + 1
        try:
            tail = skip_leading_comments(source[call.end():])
        except ValueError as error:
            errors.append(f"{source_name}:{line}: error: {error}")
            continue
        if tail.startswith("[") and not EXPLICIT_WEAK_SELF.match(tail):
            errors.append(
                f"{source_name}:{line}: error: calculator gate callbacks must use [weak self = self]; "
                "implicit [weak self] can conflict with an outer strong capture"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    try:
        source = args.source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        print(f"Cannot read calculator integration source: {error}", file=sys.stderr)
        return 1
    errors = check_source(source, str(args.source))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Calculator gate capture declarations passed (source rule only; not full AppDelegate type checking)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
