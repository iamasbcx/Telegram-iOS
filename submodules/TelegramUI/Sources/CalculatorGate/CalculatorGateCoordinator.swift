import UIKit

/// 主场景的计算器入口。所有接口必须在主线程调用，解锁只在本次前台会话内有效。
/// 持有独立窗口，不替换 Telegram 的导航栈；系统通知、扩展和通话界面不由此窗口管理。
@MainActor
final class CalculatorGateCoordinator: NSObject {
    private let scene: UIWindowScene
    private weak var contentWindow: UIWindow?
    private let keyboardWindow: () -> UIWindow?
    private let onUnlock: () -> Void
    private let gateWindow: UIWindow
    private let calculator = CalculatorViewController()
    private var keyboardCalculator: CalculatorViewController?
    private var updatingCover = false
    private var sceneIsActive = false
    private(set) var isUnlocked = false

    init(scene: UIWindowScene, contentWindow: UIWindow, keyboardWindow: @escaping () -> UIWindow?, onUnlock: @escaping () -> Void) {
        precondition(Thread.isMainThread)
        self.scene = scene
        self.contentWindow = contentWindow
        self.keyboardWindow = keyboardWindow
        self.onUnlock = onUnlock
        self.gateWindow = UIWindow(windowScene: scene)
        super.init()
        // 项目使用的键盘窗口高于 app 窗口上限，因此还要单独遮住现有键盘表面。
        self.gateWindow.windowLevel = UIWindow.Level(rawValue: 10_000_000)
        self.gateWindow.backgroundColor = UIColor(white: 16.0 / 255.0, alpha: 1.0)
        self.gateWindow.rootViewController = self.calculator
        self.calculator.onUnlockAttempt = { [weak self] candidate in
            return self?.attemptUnlock(candidate) ?? false
        }

        for name in [UIWindow.didBecomeVisibleNotification, UIWindow.didBecomeKeyNotification, UIResponder.keyboardDidShowNotification, UIResponder.keyboardDidHideNotification] {
            // UIKit 在主线程同步发布这些通知，不能异步调度遮罩，以免快照先于遮罩提交。
            NotificationCenter.default.addObserver(self, selector: #selector(self.windowSurfaceDidChange(_:)), name: name, object: nil)
        }
        self.lock()
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
        // 所有权只属于主线程 AppDelegate；清理键盘子视图，避免其被系统窗口继续持有。
        MainActor.assumeIsolated {
            self.keyboardCalculator?.view.removeFromSuperview()
            self.gateWindow.isHidden = true
        }
    }

    @objc private func windowSurfaceDidChange(_ notification: Notification) {
        precondition(Thread.isMainThread)
        self.refreshCover()
    }

    /// 失去前台时同步撤销会话，并在系统抓取切换器快照前清空输入及遮盖内容。
    func lock() {
        precondition(Thread.isMainThread)
        self.sceneIsActive = false
        self.isUnlocked = false
        self.calculator.reset()
        self.keyboardCalculator?.reset()
        UIView.performWithoutAnimation {
            self.refreshCover()
        }
    }

    /// 前台恢复只允许输入密码，不恢复旧的解锁状态。
    func didBecomeActive() {
        precondition(Thread.isMainThread)
        self.sceneIsActive = true
        if !self.isUnlocked {
            self.refreshCover()
        }
    }

    private func refreshCover() {
        guard !self.isUnlocked, !self.updatingCover else { return }
        self.updatingCover = true
        defer { self.updatingCover = false }

        self.contentWindow?.endEditing(true)
        self.contentWindow?.isHidden = true
        self.contentWindow?.accessibilityElementsHidden = true
        self.gateWindow.isHidden = false
        if !self.gateWindow.isKeyWindow {
            self.gateWindow.makeKey()
        }
        self.calculator.view.layoutIfNeeded()

        // Telegram 可把菜单/浮层放进系统键盘窗口。仅 endEditing 或提高 windowLevel
        // 不能保证遮盖这些内容；复用同样的计算器表面，避免残留窗口挡住解锁操作。
        if let keyboardWindow = self.keyboardWindow(), keyboardWindow !== self.gateWindow {
            let cover: CalculatorViewController
            if let current = self.keyboardCalculator {
                cover = current
            } else {
                cover = CalculatorViewController()
                cover.onUnlockAttempt = { [weak self] candidate in
                    return self?.attemptUnlock(candidate) ?? false
                }
                self.keyboardCalculator = cover
            }
            cover.view.frame = keyboardWindow.bounds
            cover.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
            if cover.view.superview !== keyboardWindow {
                keyboardWindow.addSubview(cover.view)
            }
            // 现有全局菜单使用 zPosition = 1000，单纯调整 subviews 顺序无法盖住。
            let highestLayer = keyboardWindow.subviews.filter { $0 !== cover.view }.map { $0.layer.zPosition }.filter { $0.isFinite }.max() ?? 0.0
            cover.view.layer.zPosition = max(1_000_000.0, highestLayer + 1.0)
            keyboardWindow.bringSubviewToFront(cover.view)
            cover.view.layoutIfNeeded()
        } else {
            self.keyboardCalculator?.view.removeFromSuperview()
            self.keyboardCalculator = nil
        }
    }

    private func attemptUnlock(_ candidate: String) -> Bool {
        precondition(Thread.isMainThread)
        guard !self.isUnlocked, self.sceneIsActive, self.scene.activationState == .foregroundActive,
              CalculatorGateConfiguration.matches(candidate) else {
            return false
        }
        self.isUnlocked = true
        self.calculator.reset()
        self.keyboardCalculator?.reset()
        self.keyboardCalculator?.view.removeFromSuperview()
        self.keyboardCalculator = nil
        self.contentWindow?.accessibilityElementsHidden = false
        self.contentWindow?.makeKeyAndVisible()
        self.gateWindow.isHidden = true
        self.onUnlock()
        return true
    }
}
