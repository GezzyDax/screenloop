import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SYNC_DEV_WORKFLOW = ROOT / ".github" / "workflows" / "sync-dev.yml"


class SyncDevWorkflowTests(unittest.TestCase):
    def test_retag_uses_lowercase_image_references(self):
        workflow = yaml.safe_load(SYNC_DEV_WORKFLOW.read_text(encoding="utf-8"))
        steps = workflow["jobs"]["retag"]["steps"]
        retag_step = next(step for step in steps if step.get("name") == "Point the dev tags at the main build")

        mixed_case_repository = "GezzyDax/screenloop"
        script = retag_step["run"].replace("${{ github.repository }}", mixed_case_repository)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            calls_path = temp_path / "docker-calls"
            docker_path = temp_path / "docker"
            docker_path.write_text(
                "#!/bin/sh\n"
                "case \"$*\" in\n"
                "  *[A-Z]*) exit 64 ;;\n"
                "esac\n"
                "printf '%s\\n' \"$*\" >> \"$DOCKER_CALLS\"\n",
                encoding="utf-8",
            )
            docker_path.chmod(0o755)

            env = os.environ.copy()
            env.update(
                {
                    "DOCKER_CALLS": str(calls_path),
                    "GITHUB_REPOSITORY": mixed_case_repository,
                    "PATH": f"{temp_path}:{env['PATH']}",
                }
            )
            result = subprocess.run(
                ["bash", "-e", "-o", "pipefail", "-c", script],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                calls_path.read_text(encoding="utf-8").splitlines(),
                [
                    "buildx imagetools create -t ghcr.io/gezzydax/screenloop:dev ghcr.io/gezzydax/screenloop:main",
                    "buildx imagetools create -t ghcr.io/gezzydax/screenloop-ui:dev ghcr.io/gezzydax/screenloop-ui:main",
                    "buildx imagetools create -t ghcr.io/gezzydax/screenloop-node:dev ghcr.io/gezzydax/screenloop-node:main",
                ],
            )


if __name__ == "__main__":
    unittest.main()
