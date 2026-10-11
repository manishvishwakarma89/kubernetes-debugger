"""Scanner tests use a fake CLI process; no registry or daemon is contacted."""
import io
import unittest
from unittest.mock import patch

from docker_debugger import DockerDebugger


class FakeProcess:
    def __init__(self, returncode=0):
        self.stdout = io.BytesIO(b"scan report")
        self.stderr = io.BytesIO(b"")
        self.returncode = returncode

    def wait(self, timeout=None):
        return self.returncode


class ScoutSourceTests(unittest.TestCase):
    def scan(self, image, source, code=0):
        with patch("docker_debugger.shutil.which", return_value="/usr/bin/docker"), \
             patch("docker_debugger.subprocess.Popen", return_value=FakeProcess(code)) as start, \
             patch("docker_debugger.docker.from_env", side_effect=AssertionError("daemon used")), \
             patch.dict("os.environ", {"DEBUGGER_API_TOKEN": "secret", "DOCKER_SCOUT_HUB_USER": "tester"}):
            result = DockerDebugger.scout_scan(image, source)
            command = start.call_args.args[0]
            environment = start.call_args.kwargs["env"]
            self.assertNotIn("DEBUGGER_API_TOKEN", environment)
            self.assertEqual(environment["DOCKER_SCOUT_HUB_USER"], "tester")
            return result, command

    def test_registry_needs_no_daemon(self):
        result, command = self.scan("nginx:latest", "registry")
        self.assertEqual(command[-1], "registry://nginx:latest")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["stdout"], "scan report")

    def test_local_and_vulnerability_exit(self):
        result, command = self.scan("5e2309035332", "local", code=2)
        self.assertEqual(command[-1], "local://5e2309035332")
        self.assertEqual(result["status"], "vulnerabilities_found")

    def test_registry_digest(self):
        image = "user/image@sha256:" + "a" * 64
        result, command = self.scan(image, "registry")
        self.assertEqual(command[-1], "registry://" + image)

    def test_bad_sources_and_ids(self):
        for image, source in [("5e2309035332", "registry"), ("nginx", "archive"), ("--help", "local"), ("fs:///etc", "registry")]:
            with self.subTest(image=image, source=source), self.assertRaises(ValueError):
                DockerDebugger.scout_scan(image, source)

    def test_failure_remains_failure(self):
        result, _ = self.scan("user/image:tag", "registry", code=1)
        self.assertEqual(result["status"], "execution_failed")

    def test_omitted_source_rejects_local_id(self):
        with self.assertRaisesRegex(ValueError, "published image"):
            DockerDebugger.scout_scan("5e2309035332")


if __name__ == "__main__":
    unittest.main()
