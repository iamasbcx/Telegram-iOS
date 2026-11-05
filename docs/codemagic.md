# 在 Codemagic 运行检查

仓库根目录的 `codemagic.yaml` 提供 `calculator-checks`。它使用 M2 和 Xcode 27.1，执行配置脚本测试、生产计算模型测试、独立 UIKit 模块类型检查以及 `AppDelegate.swift` 语法解析，与 GitHub 的 `Calculator Gate Checks` 检查范围一致。它不生成 IPA，也不替代完整 App 编译或设备验收。

## 使用步骤

1. 在 [Codemagic](https://codemagic.io/signup) 注册并连接 GitHub，添加 `iamasbcx/Telegram-iOS`。
2. 选择包含 `codemagic.yaml` 的 `feat/calculator-gate` 分支，使用 YAML 配置；若尚未识别，点击 `Check for configuration file`。
3. 点击 `Start new build`，选择该分支和 `calculator-checks`。此工作流不需要 Apple 证书、App Store Connect 密钥或 Telegram API 密钥。
4. 在构建页面依次检查四个步骤的日志。所有步骤通过后，只能确认所列独立检查通过，不能据此判定可安装或启动无闪现。

配置没有自动触发和发布规则；运行前可检查账户的剩余额度。Codemagic 的 YAML 需要先提交到目标仓库分支才能被读取，详见[官方 YAML 文档](https://docs.codemagic.io/yaml-basic-configuration/yaml-getting-started/)。

## 已确认的环境

[官方 Xcode 27.1 镜像](https://docs.codemagic.io/specs-macos/xcode-27-1/)提供 Xcode 27.1 和 macOS 27.0.1。工作流固定 `xcode: "27.1"`，并按 `versions.json` 检查实际 Xcode 和 macOS 主版本，不通过 override 绕过不一致。

独立检查不需要 Bazel 或第三方子模块。配置使用官方的 [`CM_RECURSIVE_SUBMODULE_INIT=false`](https://docs.codemagic.io/yaml-basic-configuration/environment-variables/)，防止取源码时尝试克隆无关子模块。

## 为什么暂时没有完整 IPA 工作流

2026-11-05 检查发现，仓库 `build-system/fake-codesigning/profiles/` 中主应用和六个扩展的描述文件均于 `2026-10-30 17:06:30 UTC` 到期：`Telegram`、`Share`、`NotificationContent`、`NotificationService`、`Intents`、`Widget`、`BroadcastUpload`。自签证书仍有效，但不能据此认为过期描述文件在当前 Xcode 下可以成功打包。本次没有运行 macOS 完整构建，因此没有添加未经确认可用的 `telegram-unsigned` 工作流。

其余已核对项如下：

- 当前 `Make.py build` 支持 `--configurationPath`、`--codesigningInformationPath`、`--configuration=release_arm64`、`--buildNumber`；产物路径为 `bazel-bin/Telegram/Telegram.ipa`。默认不嵌入 Watch 应用；上述七个描述文件名与当前主应用和扩展目标一致。
- `BazelLocation.py` 会下载 `versions.json` 固定的 Bazel 9.2.0，并校验 SHA-256。仓库记录值与官方 `bazel-9.2.0-darwin-arm64` 发布资产的摘要一致：`dd466352a3e4d3581b8898740ee1ff208866ccbe25f8d367c5dcb950219587e6`。无需依赖 Codemagic 是否预装 Bazel。
- `.gitmodules` 的 `../rlottie.git`、`../tgcalls.git` 会在用户 fork 下解析到当前不可访问的同名仓库。完整构建需要先关闭自动递归克隆，在 CI 中执行 `git submodule sync`，再仅覆盖本地 Git 配置为 `https://github.com/TelegramMessenger/rlottie.git` 和 `https://github.com/TelegramMessenger/tgcalls.git`。固定 commit `53c9679069eb6b6513ccc3c892ef4f4a760658da` 与 `8d6dd4c61e62965cb574c29e39327a4686066381` 已分别通过上游 GitHub API 确认可达；检出并核对这两个 commit 后，再递归初始化全部依赖。本次未修改 `.gitmodules`。

完整工作流还需要处理过期的伪签名描述文件，验证整套依赖在云机器的内存、磁盘和时限内构建成功，再导出 IPA。使用伪签名生成的 IPA 必须重新签名才能安装到设备；个人开发者签名还需要匹配的 bundle ID、App Group、设备和扩展描述文件。使用自己的 Telegram API 配置时，按根目录 `README.md` 配置，不把模板占位符直接交给构建。

当前已完成 YAML/脚本的本地静态验证，尚未注册账户、启动 Codemagic 云构建或产生 IPA。
