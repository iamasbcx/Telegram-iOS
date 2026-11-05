"""自签名构建资料的边界与真实 OpenSSL 回归测试；不导入系统证书存储。"""

import hashlib
import importlib.util
import os
import plistlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("prepare_adhoc_profiles", ROOT / "tools" / "prepare-adhoc-profiles.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProfilePreparationTests(unittest.TestCase):
    def test_output_must_stay_in_project_build_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for candidate in (root, root / "build-input", root / "elsewhere", root / "build-input" / ".." / "elsewhere"):
                with self.subTest(candidate=candidate), self.assertRaises(MODULE.ProfilePreparationError):
                    MODULE.validate_output(root, candidate)
            self.assertEqual(MODULE.validate_output(root, Path("build-input/generated")), root / "build-input/generated")

    def test_output_never_overwrites_existing_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / "build-input/generated"
            output.mkdir(parents=True)
            self.assertEqual(MODULE.validate_output(root, output), output)
            sentinel = output / "keep.txt"
            sentinel.write_text("do not replace", encoding="utf-8")
            with self.assertRaises(MODULE.ProfilePreparationError):
                MODULE.validate_output(root, output)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "do not replace")
            with self.assertRaises(MODULE.ProfilePreparationError):
                MODULE.validate_output(root, sentinel)

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "build-input").mkdir()
            (root / "outside").mkdir()
            link = root / "build-input/escape"
            try:
                link.symlink_to(root / "outside", target_is_directory=True)
            except OSError:
                self.skipTest("Creating directory symlinks is unavailable on this host.")
            with self.assertRaises(MODULE.ProfilePreparationError):
                MODULE.validate_output(root, link / "generated")

    def test_exact_openssl_major_version_is_required(self):
        # 假可执行文件只用于边界测试；run_openssl 被替换，不执行文件内容。
        import sys
        executable = Path(sys.executable).resolve()
        for version in (b"LibreSSL 3.3.6", b"OpenSSL 1.1.1w", b"OpenSSL 4.0.0"):
            with self.subTest(version=version), patch.object(MODULE, "run_openssl", return_value=version):
                with self.assertRaises(MODULE.ProfilePreparationError):
                    MODULE.validate_openssl(executable)
        with patch.object(MODULE, "run_openssl", return_value=b"OpenSSL 3.2.1 30 Jan 2024\n"):
            self.assertEqual(MODULE.validate_openssl(executable), executable)
        with self.assertRaises(MODULE.ProfilePreparationError):
            MODULE.validate_openssl(Path("openssl"))

    def test_validity_is_short_lived_and_capped_by_certificate(self):
        now = datetime(2026, 11, 5, 8, 0, tzinfo=timezone.utc)
        before = now - timedelta(days=1)
        self.assertEqual(MODULE.validity_window(now, before, now + timedelta(days=100)), (now, now + timedelta(days=30)))
        self.assertEqual(MODULE.validity_window(now, before, now + timedelta(hours=1)), (now, now + timedelta(hours=1)))
        for not_before, not_after in ((before, now), (now + timedelta(seconds=1), now + timedelta(days=10))):
            with self.assertRaises(MODULE.ProfilePreparationError):
                MODULE.validity_window(now, not_before, not_after)
        with self.assertRaises(MODULE.ProfilePreparationError):
            MODULE.validity_window(now.replace(tzinfo=None), before, now + timedelta(days=1))

    def test_renewal_preserves_identifiers_and_entitlements(self):
        now = datetime(2026, 11, 5, tzinfo=timezone.utc)
        original = {
            "UUID": "fixture-uuid",
            "Name": "Fixture",
            "ApplicationIdentifierPrefix": ["TEAM"],
            "Entitlements": {"application-identifier": "TEAM.example.app", "com.apple.security.application-groups": ["group.example"], "get-task-allow": True},
            "DeveloperCertificates": [b"old"],
        }
        snapshot = plistlib.dumps(original)
        result = MODULE.renew_profile(original, b"replacement", now, now + timedelta(days=30))
        self.assertEqual(plistlib.dumps(original), snapshot)
        for key in ("UUID", "Name", "ApplicationIdentifierPrefix", "Entitlements"):
            self.assertEqual(result[key], original[key])
        self.assertEqual(result["DeveloperCertificates"], [b"replacement"])
        self.assertEqual(result["CreationDate"], now.replace(tzinfo=None))
        self.assertEqual(result["ExpirationDate"], (now + timedelta(days=30)).replace(tzinfo=None))
        self.assertEqual(result["TimeToLive"], 30)
        for invalid in (None, {}, {"UUID": "test"}, {"UUID": "test", "Entitlements": {}}):
            with self.subTest(invalid=invalid), self.assertRaises(MODULE.ProfilePreparationError):
                MODULE.renew_profile(invalid, b"replacement", now, now + timedelta(days=1))


@unittest.skipUnless(os.environ.get("TELEGRAM_TEST_OPENSSL3"), "Set TELEGRAM_TEST_OPENSSL3 to an absolute OpenSSL 3 executable path for integration tests.")
class RealOpenSSLTests(unittest.TestCase):
    def test_generated_cms_roundtrips_and_sources_are_unchanged(self):
        executable = Path(os.environ["TELEGRAM_TEST_OPENSSL3"])
        source = ROOT / "build-system/fake-codesigning"
        original_hashes = {path: hashlib.sha256(path.read_bytes()).digest() for path in source.rglob("*") if path.is_file()}
        build_input = ROOT / "build-input"
        build_input.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="adhoc-test-", dir=build_input) as temporary:
            started = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
            output, count, expires = MODULE.prepare_profiles(ROOT, Path(temporary) / "generated", executable)
            source_profiles = sorted((source / "profiles").glob("*.mobileprovision"))
            self.assertEqual(count, len(source_profiles))
            self.assertEqual(len(list((output / "profiles").iterdir())), count)
            self.assertEqual(list((output / "certs").iterdir()), [])
            self.assertEqual(list(output.rglob("*.pem")), [])
            expected_certificate = (source / "certs/Public.cer").read_bytes()
            for original in source_profiles:
                old = MODULE.decode_profile(executable, original)
                new = MODULE.decode_profile(executable, output / "profiles" / original.name)
                self.assertEqual(new, MODULE.decode_profile(executable, output / "profiles" / original.name, "smime"))
                for key, value in old.items():
                    if key not in ("CreationDate", "ExpirationDate", "DeveloperCertificates", "TimeToLive"):
                        self.assertEqual(new[key], value, f"Changed {original.name}: {key}")
                self.assertEqual(new["DeveloperCertificates"], [expected_certificate])
                self.assertEqual(new["ExpirationDate"], expires.replace(tzinfo=None))
                self.assertGreaterEqual(new["CreationDate"], started)
                self.assertLessEqual(new["CreationDate"], datetime.now(timezone.utc).replace(tzinfo=None))
                self.assertGreater(new["ExpirationDate"] - new["CreationDate"], timedelta())
                self.assertLessEqual(new["ExpirationDate"] - new["CreationDate"], timedelta(days=30))
            with self.assertRaises(MODULE.ProfilePreparationError):
                MODULE.prepare_profiles(ROOT, output, executable)
        for path, digest in original_hashes.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), digest, f"Source changed: {path.name}")
        self.assertEqual(list(build_input.glob(".adhoc-profiles-*")), [])

    def test_signing_failure_cleans_temporary_keys_without_publishing(self):
        executable = Path(os.environ["TELEGRAM_TEST_OPENSSL3"])
        build_input = ROOT / "build-input"
        build_input.mkdir(exist_ok=True)
        original_run = MODULE.run_openssl

        def fail_signing(program, arguments, purpose):
            if purpose == "profile signing":
                raise MODULE.ProfilePreparationError("Simulated signing failure.")
            return original_run(program, arguments, purpose)

        with tempfile.TemporaryDirectory(prefix="adhoc-failure-test-", dir=build_input) as temporary:
            output = Path(temporary) / "generated"
            with patch.object(MODULE, "run_openssl", side_effect=fail_signing):
                with self.assertRaisesRegex(MODULE.ProfilePreparationError, "Simulated signing failure"):
                    MODULE.prepare_profiles(ROOT, output, executable)
            self.assertFalse(output.exists())
            self.assertEqual(list(build_input.glob(".adhoc-profiles-*")), [])


if __name__ == "__main__":
    unittest.main()
