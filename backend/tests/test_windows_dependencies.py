from pathlib import Path
from subprocess import CompletedProcess
import sys
from unittest import TestCase
from unittest.mock import Mock, patch
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import windows_dependencies as startup


class WindowsDependencyTests(TestCase):
    def setUp(self):
        self.root = Path.cwd()
        self.engine = Mock()
        self.engine.url.host = "127.0.0.1"
        self.engine.url.port = 15432
        self.stop = Mock(return_value=False)

    def test_existing_connection_skips_docker(self):
        with patch.object(startup, "docker_cli") as docker:
            self.assertIs(startup.connect_with_dependencies(self.root, self.engine, self.stop),
                          self.engine.connect.return_value)
            docker.assert_not_called()

    def test_cold_engine_starts_existing_project_database_and_waits_for_login(self):
        container = {"Config": {"Labels": {"com.docker.compose.project.working_dir": str(self.root),
                     "com.docker.compose.service": "postgres"}}, "State": {"Running": False},
                     "HostConfig": {"PortBindings": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "15432"}]}},
                     "Mounts": [{"Type": "volume", "Name": "fixture", "Destination": startup.DATA_PATH}]}
        replies = [(1, ""), (0, ""), (1, ""), (0, "linux"), (0, "container-id"), (0, json.dumps([container])), (0, "")]
        connection = Mock()
        with patch.object(startup, "WINDOWS", True), patch.object(startup.shutil, "which", return_value="docker"), \
             patch.object(startup, "docker_cli", side_effect=[CompletedProcess([], code, out, "") for code, out in replies]) as docker, \
             patch.object(startup, "connect_if_ready", side_effect=[None, None, connection]), \
             patch.object(startup.time, "sleep"):
            self.assertIs(startup.connect_with_dependencies(self.root, self.engine, self.stop), connection)
        commands = [call.args[2:] for call in docker.call_args_list]
        self.assertEqual(commands[1], ("desktop", "start", "--detach"))
        self.assertEqual(commands[-1], ("--context", "desktop-linux", "compose", "--project-directory",
                                        str(self.root), "start", "postgres"))

    def test_engine_timeout_keeps_compose_untouched(self):
        with patch.object(startup, "WINDOWS", True), patch.object(startup.shutil, "which", return_value="docker"), \
             patch.object(startup, "connect_if_ready", return_value=None), patch.object(startup, "ENGINE_TIMEOUT", 0), \
             patch.object(startup, "docker_cli", return_value=CompletedProcess([], 1, "", "")) as docker:
            with self.assertRaisesRegex(RuntimeError, "engine did not become ready"):
                startup.connect_with_dependencies(self.root, self.engine, self.stop)
        self.assertFalse(any("compose" in call.args for call in docker.call_args_list))

    def test_postgres_timeout_when_running_container_never_accepts_login(self):
        container = {"Config": {"Labels": {"com.docker.compose.project.working_dir": str(self.root),
                     "com.docker.compose.service": "postgres"}}, "State": {"Running": True},
                     "HostConfig": {"PortBindings": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "15432"}]}},
                     "Mounts": [{"Type": "volume", "Name": "fixture", "Destination": startup.DATA_PATH}]}
        replies = [CompletedProcess([], 0, value, "") for value in ("linux", "container-id", json.dumps([container]))]
        with patch.object(startup, "WINDOWS", True), patch.object(startup.shutil, "which", return_value="docker"), \
             patch.object(startup, "connect_if_ready", return_value=None), patch.object(startup, "DATABASE_TIMEOUT", 0), \
             patch.object(startup, "docker_cli", side_effect=replies):
            with self.assertRaisesRegex(RuntimeError, "did not accept the configured connection"):
                startup.connect_with_dependencies(self.root, self.engine, self.stop)

    def test_stop_cancels_before_next_dependency_probe(self):
        probe = Mock(return_value=False)
        with patch.object(startup.time, "sleep"), self.assertRaises(startup.StartupStopped):
            startup.wait_until(probe, Mock(side_effect=[False, True]), 30)
        probe.assert_called_once()
