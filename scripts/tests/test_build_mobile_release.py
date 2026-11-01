"""Exercise release dispatch without invoking a real mobile toolchain."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "build-mobile-release.sh"


class MobileReleaseTest(unittest.TestCase):
    def test_builds_flutter_only_with_public_url(self):
        for value in ("https://example.test/api/", '"https://example.test/api/"', "'https://example.test/api/'"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                (root / "duxue-app").mkdir()
                binaries = root / "bin"
                binaries.mkdir()
                flutter = binaries / "flutter"
                flutter.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$@" > "$BUILD_LOG"\n')
                flutter.chmod(0o755)
                env_file = root / "server.env"
                env_file.write_text(f"APP_BASE_URL={value}\nPRIVATE_SECRET=do-not-pass-to-build\n")
                log = root / "build.log"
                result = subprocess.run(
                    ["bash", str(SCRIPT), str(env_file)], cwd=root,
                    env={**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}", "BUILD_LOG": str(log)},
                    text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(log.read_text().splitlines(), [
                    str(root / "duxue-app"), "build", "appbundle", "--release",
                    "--dart-define=API_BASE_URL=https://example.test/api",
                ])

    def test_rejects_missing_environment_file(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(["bash", str(SCRIPT), f"{folder}/absent.env"], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Environment file not found", result.stderr)

    def test_rejects_missing_public_url(self):
        with tempfile.TemporaryDirectory() as folder:
            env_file = Path(folder) / "server.env"
            env_file.write_text("UNRELATED=value\n")
            result = subprocess.run(["bash", str(SCRIPT), str(env_file)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("APP_BASE_URL is required", result.stderr)


if __name__ == "__main__":
    unittest.main()
