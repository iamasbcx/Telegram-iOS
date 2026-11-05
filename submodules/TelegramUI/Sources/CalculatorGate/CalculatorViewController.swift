import UIKit

/// 独立的计算器表面；窗口所有权和锁定状态由宿主负责，所有接口仅在主线程调用。
final class CalculatorViewController: UIViewController {
    /// 候选仅来自 AC 后手输数字并按等号。返回 true 表示宿主已解锁；闭包不得记录输入。
    /// 宿主持有控制器时，必须弱捕获宿主，避免形成引用环。
    var onUnlockAttempt: ((String) -> Bool)?

    private var model = CalculatorModel()
    private let displayLabel = UILabel()
    private let keypad = UIStackView()
    private var buttons: [UIButton] = []
    private var keys: [CalculatorModel.Key] = []

    override var preferredStatusBarStyle: UIStatusBarStyle {
        return .lightContent
    }

    override func loadView() {
        let view = UIView()
        view.backgroundColor = UIColor(white: 16.0 / 255.0, alpha: 1.0)
        view.isOpaque = true
        self.view = view

        self.displayLabel.translatesAutoresizingMaskIntoConstraints = false
        self.displayLabel.textColor = .white
        self.displayLabel.font = UIFont.monospacedDigitSystemFont(ofSize: 68.0, weight: .light)
        self.displayLabel.textAlignment = .right
        self.displayLabel.adjustsFontSizeToFitWidth = true
        self.displayLabel.minimumScaleFactor = 0.25
        self.displayLabel.numberOfLines = 1
        self.displayLabel.accessibilityIdentifier = "calculator.display"
        self.displayLabel.accessibilityLabel = "结果"
        self.displayLabel.isAccessibilityElement = true

        self.keypad.translatesAutoresizingMaskIntoConstraints = false
        self.keypad.axis = .vertical
        self.keypad.spacing = 12.0
        self.keypad.distribution = .fillEqually

        let rows: [[(String, CalculatorModel.Key)]] = [
            [("AC", .clear), ("+/−", .sign), ("%", .percent), ("÷", .operation(.divide))],
            [("7", .digit(7)), ("8", .digit(8)), ("9", .digit(9)), ("×", .operation(.multiply))],
            [("4", .digit(4)), ("5", .digit(5)), ("6", .digit(6)), ("−", .operation(.subtract))],
            [("1", .digit(1)), ("2", .digit(2)), ("3", .digit(3)), ("+", .operation(.add))],
            [("0", .digit(0)), (".", .decimal), ("=", .equals)]
        ]

        for (rowIndex, items) in rows.enumerated() {
            let row = UIStackView()
            row.axis = .horizontal
            row.spacing = 12.0
            row.distribution = .fill
            var rowButtons: [UIButton] = []
            for (column, item) in items.enumerated() {
                let button = UIButton(type: .custom)
                button.setTitle(item.0, for: .normal)
                button.titleLabel?.font = UIFont.systemFont(ofSize: 30.0, weight: .regular)
                button.titleLabel?.adjustsFontSizeToFitWidth = true
                button.titleLabel?.minimumScaleFactor = 0.5
                let isOperator = column == items.count - 1
                button.backgroundColor = isOperator ? UIColor(red: 1.0, green: 0.62, blue: 0.04, alpha: 1.0) : UIColor(white: rowIndex == 0 ? 0.66 : 0.20, alpha: 1.0)
                button.setTitleColor(rowIndex == 0 && !isOperator ? .black : .white, for: .normal)
                button.layer.cornerCurve = .continuous
                button.accessibilityLabel = Self.accessibilityLabel(for: item.1, title: item.0)
                button.accessibilityIdentifier = "calculator.key.\(item.0)"
                button.tag = self.keys.count
                self.keys.append(item.1)
                self.buttons.append(button)
                rowButtons.append(button)
                button.addTarget(self, action: #selector(self.buttonPressed(_:)), for: .touchUpInside)
                row.addArrangedSubview(button)
            }
            if rowIndex == rows.count - 1 {
                rowButtons[1].widthAnchor.constraint(equalTo: rowButtons[2].widthAnchor).isActive = true
                rowButtons[0].widthAnchor.constraint(equalTo: rowButtons[1].widthAnchor, multiplier: 2.0, constant: 12.0).isActive = true
            } else {
                for button in rowButtons.dropFirst() {
                    button.widthAnchor.constraint(equalTo: rowButtons[0].widthAnchor).isActive = true
                }
            }
            self.keypad.addArrangedSubview(row)
        }

        view.addSubview(self.displayLabel)
        view.addSubview(self.keypad)
        let safe = view.safeAreaLayoutGuide
        let preferredWidth = self.keypad.widthAnchor.constraint(equalTo: safe.widthAnchor, constant: -32.0)
        preferredWidth.priority = .defaultHigh
        let preferredHeight = self.keypad.heightAnchor.constraint(equalTo: self.keypad.widthAnchor, multiplier: 1.25)
        preferredHeight.priority = .defaultHigh
        NSLayoutConstraint.activate([
            self.keypad.centerXAnchor.constraint(equalTo: safe.centerXAnchor),
            self.keypad.leadingAnchor.constraint(greaterThanOrEqualTo: safe.leadingAnchor, constant: 16.0),
            self.keypad.trailingAnchor.constraint(lessThanOrEqualTo: safe.trailingAnchor, constant: -16.0),
            self.keypad.widthAnchor.constraint(lessThanOrEqualToConstant: 430.0),
            self.keypad.bottomAnchor.constraint(equalTo: safe.bottomAnchor, constant: -12.0),
            self.keypad.heightAnchor.constraint(lessThanOrEqualTo: safe.heightAnchor, multiplier: 0.78),
            preferredWidth,
            preferredHeight,
            self.displayLabel.leadingAnchor.constraint(equalTo: self.keypad.leadingAnchor),
            self.displayLabel.trailingAnchor.constraint(equalTo: self.keypad.trailingAnchor),
            self.displayLabel.bottomAnchor.constraint(equalTo: self.keypad.topAnchor, constant: -16.0),
            self.displayLabel.topAnchor.constraint(greaterThanOrEqualTo: safe.topAnchor, constant: 8.0)
        ])
        self.updateDisplay()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        for button in self.buttons {
            button.layer.cornerRadius = min(button.bounds.width, button.bounds.height) * 0.5
        }
    }

    /// 清除数字、运算和候选。宿主每次进入锁定状态都应调用，且不做可泄露旧界面的过渡动画。
    func reset() {
        precondition(Thread.isMainThread)
        self.model = CalculatorModel()
        if self.isViewLoaded {
            self.updateDisplay()
        }
    }

    @objc private func buttonPressed(_ sender: UIButton) {
        guard self.keys.indices.contains(sender.tag) else { return }
        let candidate = self.model.press(self.keys[sender.tag])
        self.updateDisplay()
        if let candidate, self.onUnlockAttempt?(candidate) == true {
            self.reset()
        }
    }

    private func updateDisplay() {
        self.displayLabel.text = self.model.display
        self.displayLabel.accessibilityValue = self.model.display
    }

    private static func accessibilityLabel(for key: CalculatorModel.Key, title: String) -> String {
        switch key {
        case .clear: return "全部清除"
        case .sign: return "切换正负"
        case .percent: return "百分比"
        case .decimal: return "小数点"
        case .operation(.add): return "加"
        case .operation(.subtract): return "减"
        case .operation(.multiply): return "乘"
        case .operation(.divide): return "除"
        case .equals: return "等于"
        case .digit: return title
        }
    }
}
