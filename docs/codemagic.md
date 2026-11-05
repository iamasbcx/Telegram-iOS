# 在 Codemagic 生成 IPA

仓库根目录的 `codemagic.yaml` 提供 `telegram-ipa`：完整编译应用并导出 `Telegram.ipa`，不需要 Apple 账户、开发者证书或导入钥匙串。产物使用临时代码签名（ad-hoc），保留应用和扩展的权限声明；普通未越狱设备仍需重新签名才能安装。

## 使用步骤

1. 在 [Codemagic](https://codemagic.io/signup) 注册并连接 GitHub，添加 `iamasbcx/Telegram-iOS`。
2. 选择包含 `codemagic.yaml` 的 `feat/calculator-gate` 分支，使用 YAML 配置；若尚未识别，点击 `Check for configuration file`。
3. 点击 `Start new build`，选择该分支和 **`telegram-ipa`**，开始构建。当前工作流使用仓库已有的构建配置，不需要额外填写 Apple 或 Telegram 密钥。
4. 构建成功后，在构建页面的 **Artifacts** 下载 **`Telegram.ipa`**。同页提供 `Telegram.ipa.sha256` 和构建日志。

另有 `calculator-checks` 工作流，只执行配置脚本测试、生产计算模型测试、UIKit 模块类型检查以及 `AppDelegate.swift` 语法解析，不生成 IPA。

配置没有自动触发和发布规则；运行前可检查账户的剩余额度。Codemagic 的 YAML 需要先提交到目标仓库分支才能被读取，详见[官方 YAML 文档](https://docs.codemagic.io/yaml-basic-configuration/yaml-getting-started/)。

## 已确认的环境

[官方 Xcode 27.1 镜像](https://docs.codemagic.io/specs-macos/xcode-27-1/)提供 Xcode 27.1 和 macOS 27.0.1。工作流固定 `xcode: "27.1"`，并按 `versions.json` 检查实际 Xcode 和 macOS 主版本，不通过 override 绕过不一致。

实际云端日志曾在 `CameraNeo.metal` 报 `cannot execute tool 'metal' due to missing Metal Toolchain`。构建入口现会先串行编译该着色器并生成 Metal 库；若失败，按照 [Apple 官方组件安装流程](https://developer.apple.com/documentation/xcode/downloading-and-installing-additional-xcode-components)执行 `xcodebuild -downloadComponent MetalToolchain`，清理 `xcrun` 查找缓存后重试一次。安装或重试失败会直接终止，不进入完整编译。独立诊断日志位于 `_杂项/ipa-build/metal-toolchain-*.log`，由 Codemagic 作为构建产物保留。

完整构建使用 M2、120 分钟时限及 Bazel 磁盘缓存。脚本默认限制两个并行任务、一个同类 worker，内存调度预算为 6144 MB；这不是进程硬性内存上限。首次构建需要下载依赖并完整编译，耗时和资源是否足够仍须以实际运行日志为准。

TD 的内部 CMake 构建另有限制：源码生成和目标库编译均固定两个并行任务，不调用 `sysctl` 推算核数，也不受顶层 `--jobs` 参数调整。两次配置均传入 `-DCCACHE_FOUND:BOOL=OFF`，避免 TD 在 CMake 搜索路径找到 `ccache` 后，又通过不包含其目录的 Bazel `PATH` 执行裸命令。Bazel 磁盘缓存配置保留。

## macOS 本地与其他 CI 使用

正式构建入口为 `tools/build-calculator-ipa.sh`，Codemagic 和 GitHub 可复用同一流程。在 Apple silicon Mac 上安装匹配的 Xcode、Python 3.11+、Git 和 Homebrew 后运行：

```sh
bash tools/build-calculator-ipa.sh --help
bash tools/build-calculator-ipa.sh --build-number 1
```

可选 `--cache-dir PATH` 指定缓存目录，`--jobs NUMBER` 调整并行任务数。默认构建号取当前 CI 构建序号，本地为 `1`。脚本固定使用 `release_arm64`，默认不嵌入 Watch 应用。生成结果在 `artifacts/`，日志在 `_杂项/ipa-build/`；重复导出前将旧 IPA 和摘要备份到 `备份/calculator-ipa-<时间戳>/`。

## 构建流程与签名范围

- Codemagic 配置了官方的 [`CM_RECURSIVE_SUBMODULE_INIT=false`](https://docs.codemagic.io/yaml-basic-configuration/environment-variables/)。首次运行截图仍显示平台在取源码阶段尝试递归克隆，因此 `.gitmodules` 也已把 `rlottie`、`tgcalls` 改为 `TelegramMessenger` 上游绝对地址，避免依赖平台是否及时应用此变量。构建脚本同步本地 Git 配置，检出并核对固定 commit 后再递归初始化其余依赖。
- `BazelLocation.py` 下载 `versions.json` 固定的 Bazel 9.2.0 并校验 SHA-256，不依赖预装 Bazel。M2 对应 `darwin-arm64`，仓库摘要已与官方发布资产核对。
- `tools/prepare-adhoc-profiles.py` 以仓库公开测试材料为输入，为本次构建生成有效期内的本地描述文件。输出使用 `build-input/ipa-signing.*` 独立目录，不覆盖仓库模板，并保留 App Group 等权限字段。所需 OpenSSL 3 在缺失时通过 Homebrew 安装。
- `Make.py` 通过 `--@build_bazel_rules_apple//apple/build_settings:signing_certificate_name=-` 使用临时代码签名；保留描述文件和签名步骤，不导入证书、不依赖 Apple 开发者身份。
- 导出只读取 `bazel-bin/Telegram/Telegram.ipa`。脚本检查 ZIP 完整性、主应用与扩展可执行文件、临时签名标志及 App Group 权限，再复制产物并生成 SHA-256 摘要。

这里的 ad-hoc 是 `codesign` 的临时签名，**不是 Apple 开发者的 Ad Hoc 分发授权**。生成 IPA 与在普通设备安装是两个步骤；重签时仍需匹配应用和扩展的 bundle ID、App Group、设备及描述文件。需要自己的 Telegram API 配置时按根目录 `README.md` 设置，不把模板占位符交给构建。

当前已完成本地配置、Shell/Python 语法及相关单元测试检查；最新云端运行已通过 Metal 预检，编译约 31 分钟后在 TD 源码生成阶段遇到 `sysctl: command not found` 和 `ccache: command not found`。本次 TD 修复仍需在 macOS 云端重跑验证，尚无成功生成 IPA 的证据。模拟器和设备上的功能、通知、解锁及逐帧视觉验收仍需另行完成。
