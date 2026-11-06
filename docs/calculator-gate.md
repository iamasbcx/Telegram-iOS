# 计算器入口

此分支把主 App 的名称、图标及入口改成计算器。输入编译时指定的数字密码，再按 `=` 进入 Telegram；首次启动、切到后台、锁屏、打开控制中心或其他导致场景失去 active 的系统界面后，都需要重新输入。没有解锁宽限期，也不持久化解锁状态。

## 使用与配置

- 计算器支持四则运算、小数、百分比、正负号、连续运算和重复等号。运算按普通计算器逐步求值，不采用表达式优先级。
- 只有首次空白或按 `AC` 后，直接输入数字再按 `=` 才检查密码。输入过运算符、小数点、正负号或百分比后，先按 `AC` 再输入密码。运算结果不会成为密码，错误密码不会显示解锁提示。
- 当前配置已经写入用户指定密码的随机盐与 SHA-256 校验值，源码不保存密码明文。以后修改请运行 `python3 tools/configure-calculator-passcode.py`，按提示输入两次，再重新编译；脚本会先把旧配置保存在 `备份/calculator-passcode-<时间戳>/`。
- 数字密码允许 4–16 位 ASCII 数字，前导零属于密码。固定数字密码可能被逆向或离线穷举；入口遮盖不改变 Telegram 数据库加密方式。

## 实现边界

`CalculatorModel` 负责有界输入与十进制计算；`CalculatorViewController` 负责界面；`CalculatorGateConfiguration` 只校验编译期密码；`CalculatorGateCoordinator` 管理单个主场景的窗口及前台解锁会话。新增文件由 `submodules/TelegramUI/BUILD` 的 `Sources/**/*.swift` 自动编译。

`AppDelegate.attach` 在主内容首次显示前建立计算器窗口；`handleWillResignActive` 同步重锁并隐藏主窗口，`handleDidEnterBackground` 再次兜底。主场景恢复 active 时保持锁定，正确密码才恢复 Telegram 的 active 信号。覆盖现有键盘窗口是为了处理 Telegram 放在键盘窗口上的菜单和浮层，不能只依赖 app windowLevel。代码不记录、持久化计算器输入。

URL、用户活动、快捷方式和点击通知产生的导航会等到解锁后执行；只保留最后一次待处理导航。主屏幕动态快捷菜单和备用图标选择已关闭。后台收信仍按 Telegram 原逻辑运行。

本功能只控制主 App 界面。系统通知预览和快速回复、CallKit、分享扩展、Widget、Watch、Siri/Spotlight 以及系统中的应用信息没有全部改造；这些入口可能显示 Telegram 内容或提供独立操作。需要隐藏通知内容时，应在 iOS 通知设置中关闭预览。已有 Telegram 自身密码锁仍然保留，解锁计算器后可能还需要它。

## 构建与验证

完整 App 必须使用仓库 `versions.json` 指定的工具链，当前为 Xcode 27.1、Bazel 9.2.0；签名、API ID、App Group 及 provisioning profiles 仍按根目录 README 配置。

计算器侧载 IPA 使用 `build-system/calculator-configuration.json`，其中 `enable_icloud=false`。这是运行时能力开关：关闭缺少 iCloud 容器授权时会触发系统断言的 CloudKit 备用地址查询，同时不生成 iCloud 权限声明。重新签名不会自动修改已经编入二进制的开关，因此旧 IPA 必须重新完整编译后替换。详见 [Codemagic 构建说明](codemagic.md)。

在 macOS 上初始化依赖：

```sh
git submodule update --init --recursive
```

使用 `build-system/Make/Make.py` 的完整 `Telegram/Telegram` 构建流程，不用独立模块检查代替完整构建。原有 `.github/workflows/build.yml` 固定 `macos-13`，与当前工具链不匹配；新增 `calculator-gate-checks.yml` 只运行配置脚本测试、生产计算模型测试、独立 UIKit 文件类型检查以及 AppDelegate 语法解析，不产出 IPA。

本地测试命令：

```sh
python3 -m unittest discover -s Tests/CalculatorGate -p 'test_*.py' -v
swiftc -warnings-as-errors submodules/TelegramUI/Sources/CalculatorGate/CalculatorModel.swift Tests/CalculatorGate/CalculatorModelTests.swift -o /tmp/calculator-model-tests
/tmp/calculator-model-tests
```

视觉验收必须遵守根目录 `AGENTS.md`：在模拟器录屏后用 `tools/animation_sheet.py` 检查帧图。应覆盖冷启动、错误/正确密码、回到桌面、切其他 App、锁屏、控制中心、权限弹窗、正在输入时切后台、长按菜单/媒体浮层、通知与 URL 冷启动、横竖屏和 iPad。预期锁定期间不显示 Telegram 内容，切换器只显示清空后的计算器，返回后需要重新输入密码。

当前 Windows 环境没有 Xcode、模拟器或 XcodeBuildMCP，尚未完成完整 App 编译、IPA 签名、真机/模拟器运行或逐帧视觉验证。独立 CI 结果应单独核对，不能据此宣称已验证无闪现。

2026-11-05 本地已通过 3 个配置生成/输入拒绝/备份测试及资源格式、补丁空白检查。首次 [GitHub 检查运行](https://github.com/iamasbcx/Telegram-iOS/actions/runs/41966329482) 在分配 runner 前被拒绝，原因为 `The job was not started because your account is locked due to a billing issue.`，没有执行 Swift 模型测试或 UIKit 编译。解决账号计费限制后，可在当前分支重新运行 `Calculator Gate Checks`；完整 App 与视觉验收仍需另外执行。

名称与图标资源说明见 [calculator-branding.md](calculator-branding.md)。
