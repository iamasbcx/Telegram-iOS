import Foundation

/// 基础计算器的值类型状态。调用方独占实例；不保存历史、不记录输入，也不持有解锁凭据。
/// 四则运算按按键顺序执行，百分比在加减法中相对于左操作数，在乘除法中表示除以 100。
struct CalculatorModel {
    enum Operation: Equatable {
        case add
        case subtract
        case multiply
        case divide
    }

    enum Key {
        case digit(Int)
        case decimal
        case clear
        case sign
        case percent
        case operation(Operation)
        case equals
    }

    private static let maximumInputDigits = 16
    private static let inputLocale = Locale(identifier: "en_US_POSIX")

    private var input = "0"
    private var inputDigitCount = 0
    private var accumulator: Decimal?
    private var pendingOperation: Operation?
    private var repeatedOperation: Operation?
    private var repeatedOperand: Decimal?
    private var replaceInputOnDigit = false
    private var hasNewOperand = true
    private var showsResult = false
    private var hasError = false

    // 只有 clear/新实例才恢复资格；不能把计算结果或被截断的输入当成密码。
    private var digitCandidate: String? = ""

    var display: String {
        if self.hasError {
            return "错误"
        }
        guard self.showsResult, let value = self.value else {
            return self.input
        }
        let number = NSDecimalNumber(decimal: value)
        let magnitude = value < 0 ? -value : value
        let formatter = NumberFormatter()
        formatter.locale = Self.inputLocale
        formatter.usesGroupingSeparator = false
        formatter.usesSignificantDigits = true
        formatter.minimumSignificantDigits = 1
        formatter.maximumSignificantDigits = Self.maximumInputDigits
        let usesScientificNotation = magnitude >= Decimal(10_000_000_000_000_000 as Int64)
            || (magnitude != 0 && magnitude < Decimal(1) / Decimal(1_000_000_000))
        formatter.numberStyle = usesScientificNotation ? .scientific : .decimal
        formatter.exponentSymbol = "e"
        return formatter.string(from: number) ?? number.stringValue
    }

    /// 处理一个按键。只在首次输入或 AC 后，连续手输数字再按等号时返回一次原始候选。
    /// 返回值仅交给本地校验器；失败时已经完成普通计算，禁止将候选写入日志或持久存储。
    @discardableResult
    mutating func press(_ key: Key) -> String? {
        switch key {
        case .clear:
            self = CalculatorModel()
        case let .digit(digit):
            self.enterDigit(digit)
        case .decimal:
            self.digitCandidate = nil
            self.prepareForEntry()
            if !self.input.contains(".") {
                self.input += "."
            }
        case .sign:
            self.digitCandidate = nil
            guard !self.hasError else { return nil }
            if !self.hasNewOperand {
                self.prepareForEntry()
            }
            if self.input.hasPrefix("-") {
                self.input.removeFirst()
            } else if self.value != Decimal.zero {
                self.input = "-" + self.input
            }
            self.repeatedOperation = nil
            self.repeatedOperand = nil
        case .percent:
            self.digitCandidate = nil
            guard !self.hasError, let current = self.value else { return nil }
            guard var result = Self.calculate(current, .divide, 100) else {
                self.fail()
                return nil
            }
            if let operation = self.pendingOperation, let left = self.accumulator,
               operation == .add || operation == .subtract {
                guard let relative = Self.calculate(left, .multiply, result) else {
                    self.fail()
                    return nil
                }
                result = relative
            }
            self.setResult(result)
            self.hasNewOperand = true
            self.repeatedOperation = nil
            self.repeatedOperand = nil
        case let .operation(operation):
            self.digitCandidate = nil
            guard !self.hasError, let current = self.value else { return nil }
            if let previous = self.pendingOperation, let left = self.accumulator, self.hasNewOperand {
                guard let result = Self.calculate(left, previous, current) else {
                    self.fail()
                    return nil
                }
                self.setResult(result)
                self.accumulator = result
            } else if self.pendingOperation == nil {
                self.accumulator = current
            }
            self.pendingOperation = operation
            self.repeatedOperation = nil
            self.repeatedOperand = nil
            self.hasNewOperand = false
            self.replaceInputOnDigit = true
        case .equals:
            let candidate = self.digitCandidate.flatMap { $0.isEmpty ? nil : $0 }
            self.digitCandidate = nil
            self.evaluate()
            return candidate
        }
        return nil
    }

    private var value: Decimal? {
        return Decimal(string: self.input, locale: Self.inputLocale)
    }

    private mutating func enterDigit(_ digit: Int) {
        guard (0 ... 9).contains(digit) else {
            self.digitCandidate = nil
            return
        }
        self.prepareForEntry()
        guard self.inputDigitCount < Self.maximumInputDigits else {
            self.digitCandidate = nil
            return
        }
        self.inputDigitCount += 1
        let text = String(digit)
        if self.input == "0" {
            self.input = text
        } else if self.input == "-0" {
            self.input = "-" + text
        } else {
            self.input += text
        }
        self.digitCandidate?.append(contentsOf: text)
    }

    private mutating func prepareForEntry() {
        if self.hasError {
            // 错误后的普通数字能重新计算，但解锁资格仍须由 AC 明确重置。
            self = CalculatorModel()
            self.digitCandidate = nil
        }
        if self.replaceInputOnDigit {
            self.input = "0"
            self.inputDigitCount = 0
            self.replaceInputOnDigit = false
        }
        self.showsResult = false
        self.hasNewOperand = true
        self.repeatedOperation = nil
        self.repeatedOperand = nil
    }

    private mutating func evaluate() {
        guard !self.hasError, let current = self.value else { return }
        if let operation = self.pendingOperation, let left = self.accumulator {
            let right = self.hasNewOperand ? current : left
            guard let result = Self.calculate(left, operation, right) else {
                self.fail()
                return
            }
            self.setResult(result)
            self.repeatedOperation = operation
            self.repeatedOperand = right
        } else if let operation = self.repeatedOperation, let right = self.repeatedOperand {
            guard let result = Self.calculate(current, operation, right) else {
                self.fail()
                return
            }
            self.setResult(result)
        } else {
            self.setResult(current)
        }
        self.accumulator = nil
        self.pendingOperation = nil
        self.hasNewOperand = true
    }

    private mutating func setResult(_ result: Decimal) {
        self.input = NSDecimalNumber(decimal: result).stringValue
        self.showsResult = true
        self.replaceInputOnDigit = true
    }

    private mutating func fail() {
        self = CalculatorModel()
        self.hasError = true
        self.digitCandidate = nil
    }

    private static func calculate(_ lhs: Decimal, _ operation: Operation, _ rhs: Decimal) -> Decimal? {
        var left = lhs
        var right = rhs
        var result = Decimal.zero
        let status: NSDecimalNumber.CalculationError
        switch operation {
        case .add:
            status = NSDecimalAdd(&result, &left, &right, .plain)
        case .subtract:
            status = NSDecimalSubtract(&result, &left, &right, .plain)
        case .multiply:
            status = NSDecimalMultiply(&result, &left, &right, .plain)
        case .divide:
            status = NSDecimalDivide(&result, &left, &right, .plain)
        }
        switch status {
        case .noError, .lossOfPrecision:
            // 循环小数允许 Decimal 自身精度内的舍入；溢出、下溢和除零必须显式报错。
            return result.isNaN ? nil : result
        case .underflow, .overflow, .divideByZero:
            return nil
        @unknown default:
            return nil
        }
    }
}
