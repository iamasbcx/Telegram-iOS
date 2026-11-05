import Foundation

/// 独立命令行回归测试，直接编译生产模型，不依赖 UIKit、Telegram 账号或签名。
@main
enum CalculatorModelTests {
    static func main() {
        self.testArithmetic()
        self.testPercentAndSign()
        self.testErrorsAndBounds()
        self.testUnlockCandidates()
        print("CalculatorModelTests passed")
    }

    private static func type(_ text: String, into model: inout CalculatorModel) {
        for character in text {
            if character == "." {
                model.press(.decimal)
            } else {
                guard let digit = character.wholeNumberValue else { fatalError("Invalid test input") }
                model.press(.digit(digit))
            }
        }
    }

    private static func expect(_ condition: @autoclosure () -> Bool, _ message: String, line: UInt = #line) {
        guard condition() else { fatalError("Line \(line): \(message)") }
    }

    private static func testArithmetic() {
        var model = CalculatorModel()
        self.type("0.1", into: &model)
        model.press(.operation(.add))
        self.type("0.2", into: &model)
        model.press(.equals)
        self.expect(model.display == "0.3", "Decimal addition must avoid binary float artifacts")
        model.press(.equals)
        self.expect(model.display == "0.5", "Repeated equals must reuse the previous operand")

        model.press(.clear)
        self.type("12", into: &model)
        model.press(.operation(.add))
        self.type("3", into: &model)
        model.press(.operation(.multiply))
        self.type("4", into: &model)
        model.press(.equals)
        self.expect(model.display == "60", "Basic calculator must evaluate sequentially")

        model.press(.clear)
        self.type("8", into: &model)
        model.press(.operation(.add))
        model.press(.operation(.divide))
        self.type("2", into: &model)
        model.press(.equals)
        self.expect(model.display == "4", "Consecutive operators must replace the pending operator")

        model.press(.clear)
        self.type("6", into: &model)
        model.press(.operation(.subtract))
        model.press(.equals)
        self.expect(model.display == "0", "Equals without a right operand must reuse the left operand")
        self.type("7", into: &model)
        self.expect(model.display == "7", "Digit after equals must start a new entry")
    }

    private static func testPercentAndSign() {
        var model = CalculatorModel()
        self.type("200", into: &model)
        model.press(.operation(.add))
        self.type("10", into: &model)
        model.press(.percent)
        model.press(.equals)
        self.expect(model.display == "220", "Add percent must use a percentage of the left operand")
        model.press(.clear)
        self.type("200", into: &model)
        model.press(.operation(.multiply))
        self.type("10", into: &model)
        model.press(.percent)
        model.press(.equals)
        self.expect(model.display == "20", "Multiply percent must divide the right operand by 100")
        model.press(.sign)
        self.expect(model.display == "-20", "Sign must change a result without rounding it")
        model.press(.operation(.add))
        self.type("5", into: &model)
        model.press(.equals)
        self.expect(model.display == "-15", "A sign-changed result must remain an arithmetic operand")
    }

    private static func testErrorsAndBounds() {
        var model = CalculatorModel()
        self.type("9", into: &model)
        model.press(.operation(.divide))
        self.type("0", into: &model)
        model.press(.equals)
        self.expect(model.display == "错误", "Division by zero must report an error")
        self.type("7", into: &model)
        self.expect(model.display == "7", "A digit must recover ordinary calculation after an error")
        self.expect(model.press(.equals) == nil, "Error recovery must not re-enable unlock candidates")
        model.press(.clear)
        self.type(String(repeating: "9", count: 40), into: &model)
        self.expect(model.display == String(repeating: "9", count: 16), "Input length must remain bounded")
        self.expect(model.press(.equals) == nil, "Truncated input must never become an unlock candidate")
        model.press(.operation(.multiply))
        self.type("9999999999999999", into: &model)
        for _ in 0 ..< 12 {
            model.press(.equals)
        }
        self.expect(model.display == "错误", "Decimal overflow must report an error instead of silently wrapping")
    }

    private static func testUnlockCandidates() {
        var model = CalculatorModel()
        self.expect(model.press(.equals) == nil, "An empty entry must not attempt unlock")
        model.press(.clear)
        self.type("002468", into: &model)
        self.expect(model.press(.equals) == "002468", "Candidate must preserve explicitly typed leading zeros")
        self.expect(model.press(.equals) == nil, "A candidate must be consumed by the first equals")
        self.type("2468", into: &model)
        self.expect(model.press(.equals) == nil, "A new number after a result must still require AC")

        let modifiers: [CalculatorModel.Key] = [.decimal, .sign, .percent, .operation(.add)]
        for modifier in modifiers {
            model.press(.clear)
            self.type("2468", into: &model)
            model.press(modifier)
            self.expect(model.press(.equals) == nil, "Non-digit input must invalidate the candidate")
        }
        model.press(.clear)
        self.type("1234", into: &model)
        model.press(.operation(.multiply))
        self.type("2", into: &model)
        self.expect(model.press(.equals) == nil, "A computed matching result must never attempt unlock")
        self.expect(model.display == "2468", "The matching result must still be calculated normally")
        model.press(.clear)
        self.type("2468", into: &model)
        self.expect(model.press(.equals) == "2468", "AC must restore eligibility for direct numeric input")
        model.press(.clear)
        model.press(.digit(99))
        self.expect(model.press(.equals) == nil, "An invalid digit must not produce a candidate")
    }
}
