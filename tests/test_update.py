import contextlib
import errno
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_manager import Rig, SOURCE, cm, write

UPDATE_SOURCE = SOURCE.parent / "update.py"
spec = importlib.util.spec_from_file_location("updater", UPDATE_SOURCE)
up = importlib.util.module_from_spec(spec)
spec.loader.exec_module(up)


class ProfileTypes(Rig):
    def test_cli_only_creates_no_gui_root_or_launcher(self):
        self.m.create("cliuser", kind="cli")
        self.assertEqual(set(self.m.profile("cliuser")), {"cli"})
        result = self.m.launchers("cliuser")
        self.assertIn("cli", result)
        self.assertNotIn("gui", result)
        self.assertFalse((self.home / "Library/Application Support/Claude-cliuser").exists())
        self.assertFalse((self.root / "Applications/Claude cliuser.app").exists())

    def test_gui_only_creates_no_cli_root_or_launcher(self):
        self.m.create("guiuser", kind="gui")
        result = self.m.launchers("guiuser")
        self.assertEqual(set(self.m.profile("guiuser")), {"gui"})
        self.assertIn("gui", result)
        self.assertNotIn("cli", result)
        self.assertFalse((self.root / "data/claude-guiuser").exists())
        self.assertFalse((self.root / "sbin/claude-guiuser").exists())

    def test_cli_only_backup_both_means_enabled_cli(self):
        self.m.create("single", kind="cli")
        backup = self.m.backup("single")
        self.assertEqual(set(self.m.verify(backup)["roots"]), {"cli"})
        with self.assertRaises(cm.Error):
            self.m.backup("single", "gui")

    def test_gui_only_backup_restore(self):
        self.m.create("single", kind="gui")
        gui = self.m.profile("single")["gui"]
        write(gui / "config.json", {"old": True})
        backup = self.m.backup("single")
        write(gui / "config.json", {"old": False})
        self.m.restore("single", backup, "both")
        self.assertEqual(cm.object_json(gui / "config.json"), {"old": True})

    def test_disabled_type_has_clear_error(self):
        self.m.create("single", kind="gui")
        with self.assertRaisesRegex(cm.Error, "no CLI"):
            self.m.launch_cli("single", [])
        with self.assertRaisesRegex(cm.Error, "no CLI"):
            self.m.edit_settings("single", "cli")

    def test_migrate_cli_only_default_scope(self):
        self.m.create("single", kind="cli")
        self.m.create("other", kind="cli")
        write(self.m.profile("single")["cli"] / "skills/demo/SKILL.md", "demo")
        self.m.migrate("single", "other", "both", ["skills"], dry_run=False)
        self.assertTrue((self.m.profile("other")["cli"] / "skills/demo/SKILL.md").is_file())

    def test_migrate_gui_only_settings(self):
        self.m.create("single", kind="gui")
        self.m.create("other", kind="gui")
        write(self.m.profile("single")["gui"] / "claude_desktop_config.json",
              {"mcpServers": {"x": {}}})
        self.m.migrate("single", "other", "both", ["settings"], dry_run=False)
        self.assertIn("x", cm.object_json(self.m.profile("other")["gui"] /
                                        "claude_desktop_config.json")["mcpServers"])

    def test_migrate_mixed_types_needs_explicit_scope(self):
        self.m.create("single", kind="cli")
        with self.assertRaisesRegex(cm.Error, "types differ"):
            self.m.migrate("alpha", "single", "both", ["settings"])
        self.m.migrate("alpha", "single", "cli", ["settings"])

    def test_import_both_backup_into_cli_only(self):
        self.m.create("single", kind="cli")
        write(self.a["cli"] / "skills/demo/SKILL.md", "demo")
        backup = self.m.backup("alpha")
        self.m.migrate_backup(backup, "single", "both", ["skills"], dry_run=False)
        self.assertTrue((self.m.profile("single")["cli"] / "skills/demo/SKILL.md").exists())

    def test_old_registry_without_kind_is_both(self):
        self.m.cfg["profiles"]["alpha"].pop("kind")
        self.m.save()
        loaded = cm.Manager(self.root, self.home)
        self.assertEqual(set(loaded.profile("alpha")), {"cli", "gui"})

    def test_set_type_preserves_and_reenables_old_data(self):
        write(self.a["gui"] / "original", "keep")
        result = self.m.set_type("alpha", "cli")
        self.assertEqual(set(self.m.profile("alpha")), {"cli"})
        self.assertTrue((self.a["gui"] / "original").exists())
        self.assertTrue(Path(result["backup"]).is_dir())
        self.m.set_type("alpha", "both")
        self.assertEqual((self.m.profile("alpha")["gui"] / "original").read_text(), "keep")

    def test_no_process_scan_during_cli_launch(self):
        self.m.create("single", kind="cli")
        binary = self.home / "fake-binary"
        write(binary, "#!/bin/sh\nexit 0\n")
        binary.chmod(0o700)
        self.m.cfg["binary"] = str(binary)
        self.m.processes = mock.Mock(side_effect=AssertionError("must not scan at launch"))
        with mock.patch.object(cm.os, "execve", side_effect=OSError(errno.ENOENT, "test")) as run, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.m.launch_cli("single", ["--print", "a"]), 127)
        self.m.processes.assert_not_called()
        self.assertEqual(run.call_args.args[1], [str(binary), "--print", "a"])

    def test_data_operation_still_checks_processes(self):
        self.m.create("single", kind="cli")
        self.m.processes = mock.Mock(return_value=[(999, "Claude GUI", True)])
        with self.assertRaisesRegex(cm.Error, "Close all"):
            cm.dispatch(self.m, cm.parser().parse_args(["backup", "single"]))
        self.m.processes.assert_called_once()

    def test_metadata_launchers_dont_block_active_cli_lock(self):
        self.m.create("single", kind="cli")
        # CLI runtime holds only this profile lock after releasing the global handoff lock.
        lockdir = self.root / "locks"
        lockdir.mkdir()
        import fcntl
        with (lockdir / "profile-single.lock").open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            cm.dispatch(self.m, cm.parser().parse_args(["launchers", "single"]))

    def test_gui_only_launch_does_not_inherit_cli_config(self):
        self.m.create("single", kind="gui")
        app = self.home / "Applications/Claude.app"
        write(app / "Contents/MacOS/Claude", "")
        self.m.cfg["gui_app"] = str(app)
        marker = "--user-data-dir=" + str(self.m.profile("single")["gui"])
        self.m.processes = mock.Mock(side_effect=[
            [], [(777, str(app / "Contents/MacOS/Claude") + " " + marker, True)]])
        with mock.patch.object(cm.sys, "platform", "darwin"), \
                mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/wrong/profile"}), \
                mock.patch.object(cm.subprocess, "run") as run:
            self.m.launch_gui("single")
            self.assertNotIn("CLAUDE_CONFIG_DIR", run.call_args.kwargs["env"])

    def test_gui_only_doctor_does_not_require_cli_binary(self):
        self.m.cfg["profiles"] = {}
        self.m.create("single", kind="gui")
        self.m.find_binary = mock.Mock(side_effect=AssertionError("not a CLI profile"))
        self.assertIsNone(self.m.doctor()["binary"])
        self.m.find_binary.assert_not_called()

    def test_gui_only_launchers_do_not_depend_on_shell_rc(self):
        self.m.cfg["profiles"] = {}
        self.m.create("single", kind="gui")
        write(self.home / "rc-real", "# keep")
        (self.home / ".zshrc").symlink_to(self.home / "rc-real")
        with mock.patch.dict(os.environ, {"SHELL": "/bin/zsh"}):
            result = self.m.launchers("single")
            self.assertEqual(result["path_status"], {"not_required": True})
            self.assertEqual(self.m.doctor()["path"], {"not_required": True})

    def test_gui_only_launch_ignores_unrelated_cli_process(self):
        self.m.create("single", kind="gui")
        app = self.home / "Applications/Claude.app"
        write(app / "Contents/MacOS/Claude", "")
        self.m.cfg["gui_app"] = str(app)
        marker = "--user-data-dir=" + str(self.m.profile("single")["gui"])
        self.m.processes = mock.Mock(side_effect=[
            [(321, "claude --print", False)],
            [(777, str(app / "Contents/MacOS/Claude") + " " + marker, True)]])
        with mock.patch.object(cm.sys, "platform", "darwin"), \
                mock.patch.object(cm.subprocess, "run"):
            self.assertEqual(self.m.launch_gui("single"), 0)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cm-updater-")
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.root = self.home / "old installation"
        self.root.mkdir()
        self.release = self.base / "new release"
        self.release.mkdir()
        for rel in up.PAYLOAD:
            if rel == "SHA256SUMS":
                continue
            dest = self.release / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE.parent / rel, dest)
        self.hash_release()
        old = SOURCE.read_text().replace(f'VERSION = "{cm.VERSION}"', 'VERSION = "1.0.0"')
        write(self.root / "claude-manager.py", old)
        self.manager = cm.Manager(self.root, self.home)
        self.manager.create("work", kind="cli")
        write(self.manager.profile("work")["cli"] / "private-history", "DO NOT TOUCH")
        self.env = dict(os.environ, HOME=str(self.home), SHELL="/bin/zsh")
        self.env.pop("ZDOTDIR", None)

    def tearDown(self):
        self.tmp.cleanup()

    def hash_release(self):
        lines = [cm.digest(self.release / rel) + "  " + rel
                 for rel in up.PAYLOAD if rel != "SHA256SUMS"]
        write(self.release / "SHA256SUMS", "\n".join(lines) + "\n")

    def call(self, *args):
        return subprocess.run([sys.executable, str(self.release / "update.py"), str(self.root),
                               *args], env=self.env, text=True, capture_output=True)

    def test_update_repairs_shell_and_preserves_registry_and_data(self):
        cli = self.manager.profile("work")["cli"]
        before = cm.inventory(cli)
        registry = self.manager.state.read_bytes()
        block = up.path_block(self.root).replace(str(self.root / "sbin"), "/wrong/bin")
        write(self.home / ".zshrc", "# USER_KEEP\n" + block + "\n" + block)
        write(self.home / ".bashrc", "export CUSTOM_KEEP=1\n")
        result = self.call("--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(cm.inventory(cli), before)
        self.assertEqual(self.manager.state.read_bytes(), registry)
        self.assertIn(f'VERSION = "{cm.VERSION}"', (self.root / "claude-manager.py").read_text())
        rc = (self.home / ".zshrc").read_text()
        self.assertEqual(rc.count("# BEGIN CLAUDE PROFILE MANAGER "), 1)
        self.assertIn("# USER_KEEP", rc)
        self.assertNotIn("/wrong/bin", rc)
        self.assertIn("export CUSTOM_KEEP=1", (self.home / ".bashrc").read_text())
        self.assertTrue((self.home / ".profile").exists())
        link = self.root / "sbin/claude-work"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), self.root / "claude-manager.py")
        self.assertFalse((self.root / "Applications/Claude work.app").exists())
        self.assertTrue(json.loads(result.stdout)["backup"])
        self.assertFalse((self.root / "update-transaction.json").exists())

    def test_idempotent_repeated_update(self):
        self.assertEqual(self.call("--yes").returncode, 0)
        rc = (self.home / ".zshrc").read_text()
        again = self.call("--yes")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual((self.home / ".zshrc").read_text(), rc)

    def test_missing_yes_changes_nothing(self):
        old = (self.root / "claude-manager.py").read_bytes()
        self.assertNotEqual(self.call().returncode, 0)
        self.assertEqual((self.root / "claude-manager.py").read_bytes(), old)
        self.assertFalse((self.home / ".zshrc").exists())

    def test_corrupt_candidate_refused_before_import(self):
        write(self.release / "claude-manager.py", "raise Exception('MUST NOT IMPORT')\n")
        result = self.call("--yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr)
        self.assertNotIn("MUST NOT IMPORT", result.stderr)
        self.assertFalse((self.home / ".zshrc").exists())

    def test_other_payload_corruption_refused(self):
        write(self.release / "install.sh", "# modified")
        result = self.call("--yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr)

    def test_partial_shell_block_refuses_before_changes(self):
        old = (self.root / "claude-manager.py").read_bytes()
        text = "# BEGIN CLAUDE PROFILE MANAGER " + str(self.root) + "\n# KEEP THIS\n"
        write(self.home / ".zshrc", text)
        result = self.call("--yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / "claude-manager.py").read_bytes(), old)
        self.assertEqual((self.home / ".zshrc").read_text(), text)

    def test_shell_symlink_refused_no_overwrite(self):
        dotfiles = self.home / "real-zshrc"
        write(dotfiles, "# KEEP\n")
        (self.home / ".zshrc").symlink_to(dotfiles)
        result = self.call("--yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.home / ".zshrc").is_symlink())
        self.assertEqual(dotfiles.read_text(), "# KEEP\n")

    def test_skip_shell_respects_symlink(self):
        dotfiles = self.home / "real-zshrc"
        write(dotfiles, "# KEEP\n")
        (self.home / ".zshrc").symlink_to(dotfiles)
        result = self.call("--yes", "--skip-shell")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(dotfiles.read_text(), "# KEEP\n")
        self.assertFalse((self.home / ".profile").exists())

    def test_old_root_only_removes_owned_old_block(self):
        previous = self.home / "previous installation"
        write(self.home / ".zshrc", "# KEEP\n" + up.path_block(previous))
        result = self.call("--yes", "--old-root", str(previous))
        self.assertEqual(result.returncode, 0, result.stderr)
        rc = (self.home / ".zshrc").read_text()
        self.assertNotIn(str(previous), rc)
        self.assertIn("# KEEP", rc)

    def test_failed_launcher_regeneration_rolls_back_scripts_and_shell(self):
        self.manager.create("desktop", kind="gui")
        app = self.root / "Applications/Claude desktop.app"
        write(app / "Contents/unowned.txt", "KEEP")
        old = (self.root / "claude-manager.py").read_bytes()
        write(self.home / ".zshrc", "# ORIGINAL\n")
        result = self.call("--yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / "claude-manager.py").read_bytes(), old)
        self.assertEqual((self.home / ".zshrc").read_text(), "# ORIGINAL\n")
        self.assertEqual((app / "Contents/unowned.txt").read_text(), "KEEP")
        self.assertFalse((self.home / ".profile").exists())
        self.assertFalse((self.root / "update-transaction.json").exists())

    def test_busy_cli_lock_refuses_update(self):
        lockdir = self.root / "locks"
        lockdir.mkdir()
        import fcntl
        with (lockdir / "profile-work.lock").open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            result = self.call("--yes")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("busy", result.stderr)

    def test_update_journal_blocks_launch_but_recovery_can_acquire_lock(self):
        write(self.root / "update-transaction.json", {})
        with self.assertRaisesRegex(cm.Error, "Interrupted update"):
            with self.manager.lock(["work"], shared=True):
                pass
        with self.manager.lock(["work"], allow_update=True):
            pass

    def test_recovery_of_interrupted_update(self):
        backup = self.root / "update-backups/manual"
        backup.mkdir(parents=True)
        target = self.root / "README.cs.md"
        write(target, "original")
        record = up.snapshot(cm, target, backup, 0)
        write(target, "new interrupted update")
        journal = self.root / "update-transaction.json"
        cm.atomic_json(journal, {"format": 1, "phase": "applying",
                                "backup": str(backup), "entries": [record]})
        result = self.call("--recover", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_text(), "original")
        self.assertTrue(list((backup / "recovery-current").iterdir()))

    def test_old_both_registry_and_owned_gui_launcher_upgrade(self):
        self.manager.create("old", kind="both")
        self.manager.cfg["profiles"]["old"].pop("kind")
        self.manager.save()
        with mock.patch.object(cm, "SCRIPT", self.root / "claude-manager.py"):
            self.manager.launchers("old")
        registry = self.manager.state.read_bytes()
        result = self.call("--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        app = self.root / "Applications/Claude old.app"
        launcher = (app / "Contents/MacOS/launcher").read_text()
        self.assertIn(str(self.root / "claude-manager.py"), launcher)
        self.assertNotIn(str(self.release), launcher)
        self.assertEqual(self.manager.state.read_bytes(), registry)

    def test_committed_update_recovery_keeps_new_files(self):
        backup = self.root / "update-backups/committed"
        backup.mkdir(parents=True)
        target = self.root / "README.cs.md"
        write(target, "old")
        record = up.snapshot(cm, target, backup, 0)
        write(target, "new committed")
        journal = self.root / "update-transaction.json"
        cm.atomic_json(journal, {"format": 1, "phase": "committed",
                                "backup": str(backup), "entries": [record]})
        result = self.call("--recover", "--yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_text(), "new committed")
        self.assertFalse(journal.exists())


if __name__ == "__main__":
    unittest.main()
