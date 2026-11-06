# 在 Codemagic 生成 IPA

仓库根目录的 `codemagic.yaml` 提供 `telegram-ipa`：完整编译应用并导出 `Telegram.ipa`，不需要 Apple 账户、开发者证书或导入钥匙串。产物使用临时代码签名（ad-hoc），保留应用和扩展的权限声明；普通未越狱设备仍需重新签名才能安装。

## 使用步骤

1. 在 [Codemagic](https://codemagic.io/signup) 注册并连接 GitHub，添加 `iamasbcx/Telegram-iOS`。
2. 选择包含 `codemagic.yaml` 的 `feat/calculator-gate` 分支，使用 YAML 配置；若尚未识别，点击 `Check for configuration file`。
3. 点击 `Start new build`，选择该分支和 **`telegram-ipa`**，开始构建。当前工作流直接使用随 GitHub 同步的 `build-system/calculator-configuration.json`，其中已配置本项目用户提供的 Telegram API 凭据，无需在 Codemagic 另填环境变量；仍不需要 Apple 账户。
4. 构建成功后，在构建页面的 **Artifacts** 下载 **`Telegram.ipa`**。同页提供 `Telegram.ipa.sha256` 和构建日志。

另有 `calculator-checks` 工作流，单独运行同一套快速检查，不生成 IPA。完整 `telegram-ipa` 也会自动先运行这些检查，失败后直接停止，不进入 Metal 预检、子模块下载和完整编译。

配置没有自动触发和发布规则；运行前可检查账户的剩余额度。Codemagic 的 YAML 需要先提交到目标仓库分支才能被读取，详见[官方 YAML 文档](https://docs.codemagic.io/yaml-basic-configuration/yaml-getting-started/)。

## 已确认的环境

[官方 Xcode 27.1 镜像](https://docs.codemagic.io/specs-macos/xcode-27-1/)提供 Xcode 27.1 和 macOS 27.0.1。工作流固定 `xcode: "27.1"`，并按 `versions.json` 检查实际 Xcode 和 macOS 主版本，不通过 override 绕过不一致。

实际云端日志曾在 `CameraNeo.metal` 报 `cannot execute tool 'metal' due to missing Metal Toolchain`。构建入口现会先串行编译该着色器并生成 Metal 库；若失败，按照 [Apple 官方组件安装流程](https://developer.apple.com/documentation/xcode/downloading-and-installing-additional-xcode-components)执行 `xcodebuild -downloadComponent MetalToolchain`，清理 `xcrun` 查找缓存后重试一次。安装或重试失败会直接终止，不进入完整编译。独立诊断日志位于 `_杂项/ipa-build/metal-toolchain-*.log`，由 Codemagic 作为构建产物保留。

完整构建使用 M2、120 分钟时限及 Bazel 磁盘缓存。脚本默认限制两个并行任务、一个同类 worker，内存调度预算为 6144 MB；这不是进程硬性内存上限。首次构建需要下载依赖并完整编译，耗时和资源是否足够仍须以实际运行日志为准。

TD 的内部 CMake 构建另有限制：源码生成和目标库编译均固定两个并行任务，不调用 `sysctl` 推算核数，也不受顶层 `--jobs` 参数调整。两次配置均传入 `-DCCACHE_FOUND:BOOL=OFF`，避免 TD 在 CMake 搜索路径找到 `ccache` 后，又通过不包含其目录的 Bazel `PATH` 执行裸命令。Bazel 磁盘缓存配置保留。

## macOS 本地与其他 CI 使用

快速检查的公共入口为：

```sh
bash tools/check-calculator-gate.sh
```

它无需第三方子模块，依次检查计算器回调的捕获规则、运行 Python 回归测试、编译并执行真实生产计算模型测试，再使用 `iphoneos` SDK 和 `arm64-apple-ios15.0` 目标对计算器全部 Swift 文件做类型检查，最后解析 `AppDelegate.swift` 和 `AuthorizationSequencePaymentScreen.swift` 的语法。独立 Codemagic 和 GitHub 检查均复用这个入口。

捕获规则检查针对已知的计算器回调契约，`AppDelegate` 的 `-frontend -parse` 只检查语法；两者不能替代包含 Telegram 依赖和编译插件的完整模块类型检查，也不能保证完整编译不会出现其他错误。每次检查的模型二进制和日志放入独立的 `_杂项/calculator-checks/run.*/`，完整 IPA 流程同时将日志保存到 `_杂项/ipa-build/calculator-checks-*.log`。

正式构建入口为 `tools/build-calculator-ipa.sh`，Codemagic 和 GitHub 可复用同一流程。在 Apple silicon Mac 上安装匹配的 Xcode、Python 3.11+、Git 和 Homebrew 后运行：

```sh
bash tools/build-calculator-ipa.sh --help
bash tools/build-calculator-ipa.sh --build-number 1
```

可选 `--cache-dir PATH` 指定缓存目录，`--jobs NUMBER` 调整并行任务数。默认构建号取当前 CI 构建序号，本地为 `1`。脚本固定使用 `release_arm64`，默认不嵌入 Watch 应用。生成结果在 `artifacts/`，日志在 `_杂项/ipa-build/`；重复导出前将旧 IPA 和摘要备份到 `备份/calculator-ipa-<时间戳>/`。

## 构建流程与签名范围

- 计算器侧载配置将 `enable_icloud` 设为 `false`，同时关闭编译期 CloudKit 调用和应用的 iCloud 权限声明。个人账号重新签名后没有原 Telegram 的 iCloud 容器授权；若仍编入开启状态，启动时获取 CloudKit 备用机房地址会触发系统断言。普通 Telegram 网络初始化不依赖这条可选来源。原 `appstore-configuration.json` 保留给具有相应授权的原构建用途。
- Codemagic 配置了官方的 [`CM_RECURSIVE_SUBMODULE_INIT=false`](https://docs.codemagic.io/yaml-basic-configuration/environment-variables/)。首次运行截图仍显示平台在取源码阶段尝试递归克隆，因此 `.gitmodules` 也已把 `rlottie`、`tgcalls` 改为 `TelegramMessenger` 上游绝对地址，避免依赖平台是否及时应用此变量。构建脚本同步本地 Git 配置，检出并核对固定 commit 后再递归初始化其余依赖。
- `BazelLocation.py` 下载 `versions.json` 固定的 Bazel 9.2.0 并校验 SHA-256，不依赖预装 Bazel。M2 对应 `darwin-arm64`，仓库摘要已与官方发布资产核对。
- `tools/prepare-adhoc-profiles.py` 以仓库公开测试材料为输入，为本次构建生成有效期内的本地描述文件。输出使用 `build-input/ipa-signing.*` 独立目录，不覆盖仓库模板，并保留 App Group 等权限字段。所需 OpenSSL 3 在缺失时通过 Homebrew 安装。
- `Make.py` 通过 `--@build_bazel_rules_apple//apple/build_settings:signing_certificate_name=-` 使用临时代码签名；保留描述文件和签名步骤，不导入证书、不依赖 Apple 开发者身份。
- 导出只读取 `bazel-bin/Telegram/Telegram.ipa`。脚本检查 ZIP 完整性、主应用与扩展可执行文件、临时签名标志及 App Group 权限，并拒绝仍声明 iCloud/ubiquity 权限的侧载成品，再复制产物并生成 SHA-256 摘要。

这里的 ad-hoc 是 `codesign` 的临时签名，**不是 Apple 开发者的 Ad Hoc 分发授权**。生成 IPA 与在普通设备安装是两个步骤；重签时仍需匹配应用和扩展的 bundle ID、App Group、设备及描述文件。其他使用者应按根目录 `README.md` 申请并配置自己的 Telegram API 凭据。

## 侧载后的手机号登录

2026-11-06 按用户要求，将侧载配置从仓库预置 API ID 切换为用户提供的独立 API 凭据，并随源码同步至 GitHub。`telegram-ipa` 已固定读取此文件，无需调整工作流选择的配置路径。此变更纠正构建使用的客户端身份，但尚未证明此前收费分支由原 API ID 引起，也不能保证服务端一定下发站内验证码。

应用原本就支持 `auth.sentCodeTypeApp`：服务器选择此方式时，验证码发到已登录客户端的 Telegram 服务通知，新设备显示对应的验证码输入页。验证码渠道由服务器选择；本次没有强制或伪造返回类型，也没有新增二维码登录。

`SMS Fee` 对应的未授权状态会保存在本地，覆盖安装后可能仍显示旧页面。收费页新增始终可见的“重新登录”按钮，调用既有返回逻辑，仅将当前未授权会话恢复为手机号输入，不删除其他已登录账号。

更新验证步骤：

1. 在 Codemagic 选择包含本次修改的最新提交，手动运行 `telegram-ipa`，下载本次新生成的 IPA。
2. 在 LiveContainer 中更新应用，保留原数据容器，并保持官方 Telegram 在线。
3. 若仍出现 `SMS Fee`，点击左上角“重新登录”，重新输入完整的 `+1` 号码。
4. 若提示验证码已发送到 Telegram，在官方客户端查看这次请求的新验证码，输入后按需完成两步验证密码。
5. 若再次进入收费页或提示其他验证方式，记录新页面及错误；这意味着本次新请求仍未获得站内验证码路径，需要继续查服务端响应，不能认定换 API 身份必然解决。

本地 Windows 环境仅可执行配置检查、Python 回归测试和差异审阅；缺少 Xcode，未完成本次完整 IPA 编译、登录恢复页画面验收及真机登录验证。GitHub 快速检查新增该页面的 Swift 语法解析，完整类型检查仍由 Codemagic 构建执行。

此前云端曾在 `AppDelegate.swift` 的三处计算器回调遇到 `ImplicitStrongCapture` 错误，构建前检查已覆盖该问题。2026-11-06 已取得版本 `13.1.2`、构建号 `5` 的实际 IPA，并确认主程序及 TelegramCoreFramework 的 UUID 与手机崩溃记录一致。该旧包启用了 iCloud，但侧载安装后的实际签名只有应用标识、开发团队、App Group 和调试权限；两次冷启动均在 CloudKit 内以 `SIGTRAP` 终止。

本次关闭 CloudKit 的源码修复尚未在 macOS 完整编译，也未生成修复后的 IPA。需在 Codemagic 重新运行 `telegram-ipa`，由原账号覆盖安装，并验证冷启动、计算器解锁、Telegram 登录、前后台重锁和普通消息收发。模拟器逐帧视觉验收仍需另外执行，不能用构建通过代替真机结果。
