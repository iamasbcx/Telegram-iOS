#!/usr/bin/env bash
# 负责 macOS 本地与 CI 的完整 IPA 构建；使用仓库公开测试材料和临时签名，不访问 Apple 账户。
# 每次生成独立描述文件目录，保留日志；重写交付产物前先备份，调用方负责归档构建目录。
set -euo pipefail

usage() {
  cat <<'HELP'
Usage: bash tools/build-calculator-ipa.sh [options]

Build the complete iOS release IPA using ad-hoc code signatures.
Requires macOS, the Xcode version pinned in versions.json, Git, Python 3.11+,
Homebrew and OpenSSL 3 (installed through Homebrew if missing).
No Apple account, signing identity or keychain import is required.

Options:
  --build-number NUMBER  Positive bundle build number (default: CI number or 1)
  --cache-dir PATH      Bazel disk cache (default: $HOME/telegram-bazel-cache)
  --jobs NUMBER         Positive Bazel concurrency limit (default: 2)
  -h, --help            Show this help

Output: artifacts/Telegram.ipa and artifacts/Telegram.ipa.sha256
This ad-hoc signature does not authorize installation on a stock iOS device.
HELP
}

build_number="${PROJECT_BUILD_NUMBER:-${GITHUB_RUN_NUMBER:-1}}"
cache_dir="${HOME}/telegram-bazel-cache"
build_jobs=2
while [ "$#" -gt 0 ]; do
  case "$1" in
    --build-number|--cache-dir|--jobs)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for $1" >&2
        exit 2
      fi
      case "$1" in
        --build-number) build_number="$2" ;;
        --cache-dir) cache_dir="$2" ;;
        --jobs) build_jobs="$2" ;;
      esac
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
if ! [[ "$build_number" =~ ^[1-9][0-9]*$ ]] || ! [[ "$build_jobs" =~ ^[1-9][0-9]*$ ]]; then
  echo "--build-number and --jobs must be positive integers" >&2
  exit 2
fi
if [ -z "$cache_dir" ]; then
  echo "--cache-dir must not be empty" >&2
  exit 2
fi
if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
  echo "This workflow requires an Apple silicon Mac" >&2
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
# 容器运行不具有独立应用的系统身份，配置与成品均须通过同一能力策略。
build_configuration="$repo_root/build-system/calculator-configuration.json"
for tool in git python3 xcodebuild xcrun security codesign ditto brew; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Required tool is missing: $tool" >&2
    exit 1
  fi
done
python3 - "$build_configuration" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path("tools").resolve()))
from sideload_build_policy import check_configuration_file

if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required")
check_configuration_file(Path(sys.argv[1]))
versions = json.loads(Path("versions.json").read_text())
xcode = subprocess.check_output(["xcodebuild", "-version"], text=True).splitlines()[0].split()[1]
macos = subprocess.check_output(["sw_vers", "-productVersion"], text=True).strip()
if xcode != versions["xcode"]:
    raise SystemExit(f"Required Xcode {versions['xcode']}, found {xcode}")
if macos.split(".")[0] != versions["macos"]:
    raise SystemExit(f"Required macOS major {versions['macos']}, found {macos}")
print(f"Xcode {xcode}; macOS {macos}; Bazel {versions['bazel'].split(':')[0]}")
PY

log_dir="$repo_root/_杂项/ipa-build"
mkdir -p "$log_dir" "$repo_root/build-input"
run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"

# 先检查本次入口改动，失败立即停止，避免下载依赖或长时间完整编译后才发现局部错误。
bash tools/check-calculator-gate.sh 2>&1 | tee "$log_dir/calculator-checks-$run_id.log"

# 串行编译并链接真实着色器，确认可选组件已安装且挂载可用；仅找到 metal 启动器不足以证明这一点。
# 使用接近 Bazel action 的最小环境，预检产物归本次构建所有，不参与正式 IPA 打包。
metal_log="$log_dir/metal-toolchain-$run_id.log"
metal_output="$repo_root/build-input/metal-preflight-$run_id"
metal_environment=(
  /usr/bin/env -i
  APPLE_SDK_PLATFORM=iPhoneOS
  "APPLE_SDK_VERSION_OVERRIDE=$(/usr/bin/xcrun --sdk iphoneos --show-sdk-version)"
  PATH=/bin:/usr/bin:/usr/local/bin
  ZERO_AR_DATE=1
)
check_metal_toolchain() {
  "${metal_environment[@]}" /usr/bin/xcrun metal \
    -c -target air64-apple-ios15.0 -ffast-math \
    -o "$metal_output.air" \
    submodules/Camera/CameraNeo/MetalResources/CameraNeo.metal || return "$?"
  "${metal_environment[@]}" /usr/bin/xcrun metallib \
    "$metal_output.air" -o "$metal_output.metallib" || return "$?"
  test -s "$metal_output.air" && test -s "$metal_output.metallib"
}
echo "Checking Metal compilation and linking before the full build"
if ! check_metal_toolchain 2>&1 | tee "$metal_log"; then
  echo "Metal preflight failed; installing Metal Toolchain and retrying once" | tee -a "$metal_log"
  xcodebuild -downloadComponent MetalToolchain 2>&1 | tee -a "$metal_log"
  "${metal_environment[@]}" /usr/bin/xcrun --kill-cache 2>&1 | tee -a "$metal_log"
  check_metal_toolchain 2>&1 | tee -a "$metal_log"
fi
echo "Metal compilation and linking passed" | tee -a "$metal_log"

# 仅覆盖本地 Git 配置；必须先 sync 再覆盖，避免相对地址再次解析到用户 fork。
git submodule sync --recursive
git config submodule.submodules/rlottie/rlottie.url https://github.com/TelegramMessenger/rlottie.git
git config submodule.submodules/TgVoipWebrtc/tgcalls.url https://github.com/TelegramMessenger/tgcalls.git
git submodule update --init --jobs 2 -- submodules/rlottie/rlottie submodules/TgVoipWebrtc/tgcalls
for module_path in submodules/rlottie/rlottie submodules/TgVoipWebrtc/tgcalls; do
  expected_commit="$(git rev-parse "HEAD:$module_path")"
  actual_commit="$(git -C "$module_path" rev-parse HEAD)"
  if [ "$actual_commit" != "$expected_commit" ]; then
    echo "Submodule commit mismatch: $module_path" >&2
    exit 1
  fi
done
git submodule update --init --recursive --jobs 2
git submodule status --recursive | tee "$log_dir/submodules-$run_id.log"
python3 - <<'PY'
import subprocess
status = subprocess.check_output(["git", "submodule", "status", "--recursive"], text=True)
if any(line and line[0] != " " for line in status.splitlines()):
    raise SystemExit("A submodule is missing or differs from its pinned commit")
PY

if ! brew --prefix openssl@3 >/dev/null 2>&1; then
  brew install openssl@3
fi
openssl_binary="$(brew --prefix openssl@3)/bin/openssl"
test -x "$openssl_binary"
# mktemp 创建的空目录归本次构建所有；不覆盖模板或上次构建的描述文件。
export TELEGRAM_ADHOC_PROFILES_DIR
TELEGRAM_ADHOC_PROFILES_DIR="$(mktemp -d "$repo_root/build-input/ipa-signing.XXXXXX")"
python3 tools/prepare-adhoc-profiles.py \
  --output "$TELEGRAM_ADHOC_PROFILES_DIR" \
  --openssl "$openssl_binary"

# 资源参数降低并发压力；memory 是调度预算，不是编译器进程的硬性内存上限。
bazel_arguments="--@build_bazel_rules_apple//apple/build_settings:signing_certificate_name=- --jobs=$build_jobs --local_resources=cpu=$build_jobs --local_resources=memory=6144 --worker_max_instances=1"
python3 -u build-system/Make/Make.py \
  --cacheDir="$cache_dir" \
  --bazelArguments="$bazel_arguments" \
  build \
  --configurationPath="$build_configuration" \
  --codesigningInformationPath="$TELEGRAM_ADHOC_PROFILES_DIR" \
  --configuration=release_arm64 \
  --buildNumber="$build_number" \
  2>&1 | tee "$log_dir/fullbuild-$run_id.log"

# 只检查本次 Bazel 输出的 IPA；archive-root 目录可能在增量构建中残留旧产物。
python3 - <<'PY'
import hashlib
import fnmatch
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path("tools").resolve()))
from sideload_build_policy import validate_container_archive_members, validate_container_entitlements

source = Path("bazel-bin/Telegram/Telegram.ipa")
if not source.is_file() or source.stat().st_size == 0:
    raise SystemExit("Build did not produce bazel-bin/Telegram/Telegram.ipa")
with zipfile.ZipFile(source) as archive:
    bad_file = archive.testzip()
    if bad_file:
        raise SystemExit(f"IPA ZIP integrity check failed: {bad_file}")
    validate_container_archive_members(archive.namelist())

expected_entitlements = {}
for profile in (Path(os.environ["TELEGRAM_ADHOC_PROFILES_DIR"]) / "profiles").glob("*.mobileprovision"):
    decoded = subprocess.check_output(["security", "cms", "-D", "-i", str(profile)])
    entitlements = plistlib.loads(decoded)["Entitlements"]
    bundle_id = entitlements["application-identifier"].split(".", 1)[1]
    expected_entitlements[bundle_id] = entitlements

with tempfile.TemporaryDirectory(prefix="telegram-ipa-") as staging:
    subprocess.run(["ditto", "-x", "-k", str(source.resolve()), staging], check=True)
    roots = list((Path(staging) / "Payload").glob("*.app"))
    if len(roots) != 1:
        raise SystemExit("Expected exactly one main app in IPA")
    app = roots[0]
    bundles = [app] + list(app.rglob("*.appex")) + list(app.rglob("*.app"))
    for bundle in bundles:
        info = plistlib.loads((bundle / "Info.plist").read_bytes())
        executable = bundle / info["CFBundleExecutable"]
        if not executable.is_file() or executable.stat().st_size == 0:
            raise SystemExit(f"Missing bundle executable: {bundle.name}")
        details = subprocess.run(["codesign", "--display", "--verbose=2", str(bundle)],
                                 capture_output=True, text=True, check=True)
        if "Signature=adhoc" not in details.stderr:
            raise SystemExit(f"Expected ad-hoc code signature: {bundle.name}")
        subprocess.run(["codesign", "--verify", "--strict", str(bundle)], check=True)
        signed = subprocess.check_output(["codesign", "--display", "--entitlements", ":-", str(bundle)])
        entitlements = plistlib.loads(signed)
        bundle_id = info["CFBundleIdentifier"]
        # 描述文件模板的授权范围不代表容器能力；按实际签名权限拒绝不支持的成品。
        validate_container_entitlements(entitlements)
        if bundle_id not in expected_entitlements:
            raise SystemExit(f"No expected profile for {bundle_id}")
        expected = expected_entitlements[bundle_id]
        if sorted(entitlements.get("com.apple.security.application-groups", [])) != sorted(expected.get("com.apple.security.application-groups", [])):
            raise SystemExit(f"App Group entitlements mismatch: {bundle_id}")
        if entitlements.get("application-identifier") != expected["application-identifier"]:
            raise SystemExit(f"Application identifier entitlement mismatch: {bundle_id}")
        # 描述文件中的钥匙串组可为通配范围；签名中的具体组必须属于该范围。
        allowed_keychains = expected.get("keychain-access-groups", [])
        for group in entitlements.get("keychain-access-groups", []):
            if not any(fnmatch.fnmatchcase(group, pattern) for pattern in allowed_keychains):
                raise SystemExit(f"Unexpected keychain access group for {bundle_id}")
        print(f"Verified ad-hoc signature and entitlement scope: {bundle_id}")

output = Path("artifacts")
output.mkdir(exist_ok=True)
destination = output / "Telegram.ipa"
checksum = output / "Telegram.ipa.sha256"
existing = [path for path in [destination, checksum] if path.exists()]
if existing:
    backup = Path("备份") / f"calculator-ipa-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}" / "artifacts"
    backup.mkdir(parents=True)
    for path in existing:
        shutil.copy2(path, backup / path.name)
    print(f"Previous artifacts backed up to {backup}")
with tempfile.NamedTemporaryFile(dir=output, prefix="Telegram.ipa.", delete=False) as temporary:
    temporary_path = Path(temporary.name)
try:
    shutil.copy2(source, temporary_path)
    with temporary_path.open("rb") as artifact:
        digest = hashlib.file_digest(artifact, "sha256").hexdigest()
    temporary_path.replace(destination)
    checksum.write_text(f"{digest}  Telegram.ipa\n", encoding="utf-8")
finally:
    temporary_path.unlink(missing_ok=True)
print(f"Exported {destination} ({destination.stat().st_size} bytes)")
PY
