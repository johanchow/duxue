"""Check workflow wiring and execute the publisher shell with a harmless double."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class DownloadWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.load((ROOT / ".github/workflows/app-release.yml").read_text(), Loader=yaml.BaseLoader)

    def test_every_main_merge_runs_both_gates_and_serializes_production_releases(self):
        self.assertEqual(self.workflow["on"]["push"], {"branches": ["main"]})
        jobs = self.workflow["jobs"]
        self.assertEqual(set(jobs["release"]["needs"]), {"test", "download-test"})
        for gate in ["test", "download-test"]:
            self.assertEqual(jobs[gate]["if"], "github.ref == 'refs/heads/main'")
            self.assertTrue((ROOT / jobs[gate]["uses"]).is_file())
        self.assertEqual(jobs["release"]["environment"], "production")
        self.assertEqual(self.workflow["concurrency"], {"group": "guardian-release", "cancel-in-progress": "false"})

    def test_publisher_receives_actual_build_identity_and_preserves_existing_artifacts(self):
        steps = self.workflow["jobs"]["release"]["steps"]
        publish = next(step for step in steps if step.get("name") == "Publish download page and latest APK")
        artifact_index = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("actions/upload-artifact@"))
        self.assertLess(artifact_index, steps.index(publish))
        self.assertEqual(publish["working-directory"], ".")
        self.assertEqual(publish["env"]["OSS_ACCESS_KEY_SECRET"], "${{ secrets.OSS_ACCESS_KEY_SECRET }}")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "duxue-app").mkdir()
            (root / "duxue-app/pubspec.yaml").write_text("version: 1.2.3+999\n")
            (root / "bin").mkdir()
            executable = root / "bin/python"
            executable.write_text("#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\nPath('args.json').write_text(json.dumps(sys.argv[1:]))\n")
            executable.chmod(0o755)
            result = subprocess.run(["bash", "-eu", "-c", publish["run"]], cwd=root, capture_output=True, text=True,
                env={**os.environ, "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
                     "RUNNER_TEMP": str(root / "runner folder"), "ARTIFACT_NAME": "guardian-1.2.3+42-abcdef1",
                     "GITHUB_RUN_NUMBER": "42", "GITHUB_SHA": "abcdef1234567890"})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((root / "args.json").read_text()), [
                "scripts/publish-download.py", "--apk", str(root / "runner folder/guardian-1.2.3+42-abcdef1.apk"),
                "--version", "1.2.3", "--build", "42", "--commit", "abcdef1234567890",
            ])


if __name__ == "__main__":
    unittest.main()
