"""The updater must not overwrite itself while it is running.

`update.sh` downloads a newer copy of itself and installs it. Doing that with
`cp` truncates and rewrites the file in place, keeping the inode. Bash reads a
script incrementally by byte offset, so the interpreter carries on reading the
*new* content from the *old* offset and executes whatever fragment lands there.

On a real production upgrade this surfaced as:

    ./update.sh: line 311: rn: command not found

-- the tail of a word, at the byte offset that used to begin `chmod`. The
update aborted midway. Renaming instead gives the name a new inode and leaves
the running shell's descriptor pointing at the original file.
"""

import re
import subprocess
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
UPDATE_SH = REPO / "update.sh"


class UpdaterSourceTests(unittest.TestCase):
    def test_the_updater_never_copies_over_itself(self):
        """`cp` onto the running script is the exact shape of the bug."""
        offenders = [
            line.strip()
            for line in UPDATE_SH.read_text().splitlines()
            if re.match(r"^\s*cp\s+.*\bupdate\.sh\s*$", line) and not line.strip().startswith("#")
        ]
        self.assertEqual(offenders, [], "update.sh must be replaced with mv, not cp")

    def test_the_replacement_is_an_atomic_rename(self):
        text = UPDATE_SH.read_text()
        self.assertRegex(text, r"mv\s+-f\s+\./\.update\.sh\.new\s+update\.sh")

    def test_the_staging_file_sits_next_to_the_target(self):
        """A rename is only atomic within one filesystem, so /tmp will not do."""
        text = UPDATE_SH.read_text()
        self.assertIn('cp "$tmpdir/update.sh" ./.update.sh.new', text)


class SelfReplacementBehaviourTests(unittest.TestCase):
    """Demonstrate the failure and the fix on a script of the same shape."""

    def build(self, root: Path, install: str, name: str) -> Path:
        padding = "\n".join(f"filler_{index}=1" for index in range(200))
        script = root / name
        script.write_text(
            textwrap.dedent(f"""\
                #!/usr/bin/env bash
                echo started
                {padding}
                {install}
                echo reached-the-end
                """)
        )
        # The replacement must be long enough that the old read offset lands
        # inside a different token.
        (root / "new.sh").write_text(
            "#!/usr/bin/env bash\n" + "\n".join(f"# padding padding padding {i}" for i in range(400)) + "\n"
        )
        return script

    def run_script(self, script: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(script.name)],
            cwd=script.parent,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_copying_over_a_running_script_corrupts_execution(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = self.build(root, "cp ./new.sh ./victim.sh", "victim.sh")
            result = self.run_script(script)

            self.assertNotIn("reached-the-end", result.stdout)
            self.assertIn("command not found", result.stderr)

    def test_renaming_into_place_leaves_the_running_script_intact(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = self.build(root, "cp ./new.sh ./.victim.new && mv -f ./.victim.new ./victim.sh", "victim.sh")
            result = self.run_script(script)

            self.assertIn("reached-the-end", result.stdout, result.stderr)
            self.assertEqual(result.returncode, 0, result.stderr)


class UpdaterSyntaxTests(unittest.TestCase):
    def test_both_operator_scripts_parse(self):
        for name in ("update.sh", "install.sh"):
            with self.subTest(script=name):
                result = subprocess.run(["bash", "-n", str(REPO / name)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
