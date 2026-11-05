# 计算器外观资源

主应用显示名称为“计算器”，主图标为深色计算器，启动背景固定为 `#101010`。入口密码与前后台锁定逻辑由计算器入口模块负责；本文仅说明名称、图标及启动资源。

## 构建来源

- `Telegram/BUILD` 的 `TelegramInfoPlist` 生成主应用 `CFBundleDisplayName` 和 `CFBundleName`；`AppNameInfoPlist` 为使用它的扩展提供显示名称。Bazel 主目标不读取 `Telegram/Telegram-iOS/Info.plist`，该文件仅同步必要字段，避免源码中的两处定义冲突。
- `Telegram/Telegram-iOS/ar.lproj/InfoPlist.strings` 与 `ko.lproj/InfoPlist.strings` 原本覆盖显示名称，现同步为“计算器”。其余权限用途说明保留原始内容。
- 主图标仍通过 `Telegram.icon` 的 Icon Composer 资源接入。`CalculatorBody.svg` 负责背景，`CalculatorKeys.svg` 负责显示区域及计算符号，不依赖字体。系统负责图标圆角和最终外观。
- `alternate_icons` 为空，本地 plist 中的 iPhone、iPad 备用图标声明也已移除。原来的 `.alticon` 源素材保留在仓库，但不由主应用打包规则引用。应用内备用图标清单和切换行为必须同时关闭。
- `Telegram/Telegram-iOS/Base.lproj/LaunchScreen.xib` 使用固定深色背景，不随系统深浅色切换。
- 可选 Watch 应用有独立的名称和图标，本次未修改；默认构建不嵌入 Watch 应用。启用 `--embedWatchApp` 时需单独处理并验证该部分。

应用的 bundle ID、可执行文件名、URL scheme 和 Telegram 网络协议保持原有构建配置。这些名称不决定主屏幕图标下的显示文字。系统通知内容、Widget、Siri 和分享扩展需要单独验证，不能用主应用入口遮罩推断它们的显示效果。

## 验证与交付限制

Windows 可验证 plist、XIB、SVG XML、Icon Composer JSON 的语法，检查 SVG 引用是否存在、Bazel 源文件语法及名称覆盖，并运行 `git diff --check`。这些检查不能代替 Apple 工具链编译，也不能验证 Icon Composer 渲染或启动过程。

当前 `versions.json` 固定 `Xcode 27.1`、`macOS 27`；现有 `.github/workflows/build.yml` 仍指定 `macos-13`，并尝试选择 `/Applications/Xcode_27.1.app`。两者配置不一致，不能据此认为 GitHub Actions 可以直接生成 IPA。该 workflow 还沿用旧版 actions、伪签名材料和自动发布 Release 步骤，本次未执行或修改它。

最终验收需要在匹配版本的 macOS/Xcode 环境构建 `//Telegram:Telegram`，检查产物 `Info.plist` 的名称与图标键，在 iPhone、iPad 上确认浅色、深色及着色图标。按 `AGENTS.md` 录制冷启动、解锁、切后台和返回过程并逐帧检查，确认无内容闪现、无亮色闪屏；当前 Windows 环境未完成这些设备验证。

修改前的原始文件集中备份于 `备份/calculator-gate-20261105/branding/`，按原目录结构保存。
