import contextlib
import hashlib
import importlib.util
import io
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "claude-manager.py"
spec = importlib.util.spec_from_file_location("cm", SOURCE)
cm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cm)


def write(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data if isinstance(data, str) else json.dumps(data))


class Rig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cm-test-")
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.root = self.home / "install with spaces"
        self.m = cm.Manager(self.root, self.home)
        self.m.processes = lambda: []
        for n in ("alpha", "beta"):
            self.m.create(n)
        self.a, self.b = self.m.profile("alpha"), self.m.profile("beta")
        self.cwd = self.home / "project"
        self.cwd.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def index(self, name, account="acct", org="org"):
        p = self.m.profile(name)["gui"] / "claude-code-sessions" / account / org
        p.mkdir(parents=True, exist_ok=True)
        return p

    def session(self, idx, name="local_test", **kwargs):
        data = {"sessionId": name, "cwd": str(self.cwd), "title": "Example",
                "permissionMode": "bypassPermissions", "bridgeSessionIds": ["SECRET"]}
        data.update(kwargs)
        write(idx / (name + ".json"), data)


class Profiles(Rig):
    def test_defaults(self):
        self.assertEqual(self.a["cli"], self.root / "data/claude-alpha")
        self.assertEqual(self.a["gui"], self.home / "Library/Application Support/Claude-alpha")

    def test_invalid_names(self):
        for n in ("../x", "a b", "A", "gui-foo", "x;id", "ž", "", "a" * 33):
            with self.subTest(n=n), self.assertRaises(cm.Error):
                self.m.create(n)

    def test_no_overlapping_roots(self):
        with self.assertRaises(cm.Error):
            self.m.create("overlap", cli=self.a["cli"] / "nested")
        with self.assertRaises(cm.Error):
            self.m.create("overlap", cli=self.home)

    def test_symlink_root_refused(self):
        link = self.home / "link"
        link.symlink_to(self.a["cli"])
        with self.assertRaises(cm.Error):
            self.m.create("bad", cli=link)

    def test_existing_not_overwritten(self):
        p = self.home / "existing"
        p.mkdir()
        write(p / "data", "keep")
        with self.assertRaises(cm.Error):
            self.m.create("new", cli=p)
        self.m.create("new", cli=p, existing=True)
        self.assertEqual((p / "data").read_text(), "keep")

    def test_unknown_schema(self):
        write(self.root / "manager.json", {"version": 99, "profiles": {}})
        with self.assertRaises(cm.Error):
            cm.Manager(self.root, self.home)

    def test_manager_named_profile_has_independent_lock(self):
        self.m.create("manager")
        with self.m.lock(["manager"]):
            pass

    def test_symlink_lock_directory_refused(self):
        outside = self.home / "outside"
        outside.mkdir()
        (self.root / "locks").symlink_to(outside)
        with self.assertRaises(cm.Error):
            with self.m.lock():
                pass

    def test_managed_backup_root_refused(self):
        with self.assertRaises(cm.Error):
            self.m.create("bad", cli=self.root / "backups/source", existing=True)


class Backups(Rig):
    def seed(self):
        write(self.a["cli"] / "settings.json", {"enabledPlugins": {"x": True}})
        write(self.a["cli"] / ".credentials.json", {"token": "do-not-print"})
        write(self.a["gui"] / "config.json", {"account": "source"})

    def test_backup_verify(self):
        self.seed()
        b = self.m.backup("alpha")
        self.assertTrue(self.m.verify(b)["complete"])
        self.assertEqual(json.loads((b / "cli/.credentials.json").read_text())["token"],
                         "do-not-print")
        self.assertEqual(b.stat().st_mode & 0o777, 0o700)

    def test_corrupt_backup_refused(self):
        self.seed()
        b = self.m.backup("alpha")
        write(b / "cli/settings.json", {"changed": 1})
        with self.assertRaises(cm.Error):
            self.m.verify(b)

    def test_unknown_file_in_backup(self):
        b = self.m.backup("alpha")
        write(b / "unexpected", "x")
        with self.assertRaises(cm.Error):
            self.m.verify(b)

    def test_exact_restore_and_prebackup(self):
        self.seed()
        b = self.m.backup("alpha")
        write(self.a["cli"] / "new", "preserve me")
        old = self.m.restore("alpha", b, "both")
        self.assertFalse((self.a["cli"] / "new").exists())
        self.assertEqual((old / "cli/new").read_text(), "preserve me")
        self.assertFalse(self.m.journal.exists())

    def test_cross_profile_restore_refused(self):
        b = self.m.backup("alpha")
        with self.assertRaises(cm.Error):
            self.m.restore("beta", b, "both")

    def test_export_round_trip(self):
        self.seed()
        b = self.m.backup("alpha")
        archive = self.m.export(b, self.home / "transfer.tar.gz")
        imported = self.m.import_archive(archive, cm.digest(archive))
        self.assertEqual(self.m.verify(imported)["files"], self.m.verify(b)["files"])

    def test_import_checksum(self):
        b = self.m.backup("alpha")
        a = self.m.export(b, self.home / "a.tar.gz")
        with self.assertRaises(cm.Error):
            self.m.import_archive(a, "0" * 64)

    def malicious_tar(self, name, kind="file", link=None):
        archive = self.home / "evil.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo(name)
            if kind == "file":
                info.size = 1
                tar.addfile(info, io.BytesIO(b"x"))
            else:
                info.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
                info.linkname = link
                tar.addfile(info)
        return archive

    def test_traversal_and_absolute_archive(self):
        for path in ("../escaped", "/tmp/escaped", "cli/../../escaped"):
            with self.subTest(path=path):
                a = self.malicious_tar(path)
                with self.assertRaises(cm.Error):
                    self.m.import_archive(a, cm.digest(a))
        self.assertFalse((self.home / "escaped").exists())

    def test_external_symlink_and_hardlink(self):
        for kind, target in (("symlink", "/etc/passwd"), ("symlink", "../../outside"),
                             ("hardlink", "cli/safe")):
            with self.subTest(kind=kind, target=target):
                a = self.malicious_tar("cli/link", kind, target)
                with self.assertRaises(cm.Error):
                    self.m.import_archive(a, cm.digest(a))

    def test_internal_symlink_roundtrip(self):
        write(self.a["cli"] / "skills/x/SKILL.md", "skill")
        (self.a["cli"] / "skills/y").symlink_to("x")
        b = self.m.backup("alpha")
        a = self.m.export(b, self.home / "a.tar.gz")
        imported = self.m.import_archive(a, cm.digest(a))
        self.assertTrue((imported / "cli/skills/y").is_symlink())

    def test_socket_refused(self):
        import socket
        if len(str(self.a["cli"] / "test.sock").encode()) > 100:
            self.skipTest("Temporary path exceeds macOS AF_UNIX socket path limit")
        sock = socket.socket(socket.AF_UNIX)
        try:
            sock.bind(str(self.a["cli"] / "test.sock"))
            with self.assertRaises(cm.Error):
                self.m.backup("alpha", "cli")
        finally:
            sock.close()

    def test_default_adjacent_state_backup_restore(self):
        default = self.home / ".claude"
        self.m.create("system", cli=default)
        write(self.home / ".claude.json", {"account": "original"})
        b = self.m.backup("system", "cli")
        write(self.home / ".claude.json", {"account": "changed"})
        self.m.restore("system", b, "cli")
        self.assertEqual(cm.object_json(self.home / ".claude.json"), {"account": "original"})

    def test_restore_absence_of_default_adjacent_state(self):
        self.m.create("system", cli=self.home / ".claude")
        b = self.m.backup("system", "cli")
        write(self.home / ".claude.json", {"new": True})
        self.m.restore("system", b, "cli")
        self.assertFalse((self.home / ".claude.json").exists())
        self.assertTrue(list(self.home.glob(".cm-old-*-*")))

    def test_portable_export_rebases_absolute_internal_links(self):
        write(self.a["cli"] / "skills/x/SKILL.md", "skill")
        (self.a["cli"] / "skills/y").symlink_to(self.a["cli"] / "skills/x")
        b = self.m.backup("alpha")
        archive = self.m.export(b, self.home / "portable.tar.gz")
        new = self.m.import_archive(archive, cm.digest(archive))
        self.assertEqual(os.readlink(new / "cli/skills/y"), "x")
        self.assertTrue((new / "cli/skills/y/SKILL.md").is_file())

    def test_export_external_link_refused(self):
        (self.a["cli"] / "outside").symlink_to("/etc/passwd")
        b = self.m.backup("alpha")
        with self.assertRaises(cm.Error):
            self.m.export(b, self.home / "bad.tar.gz")

    def test_extraction_limits(self):
        a = self.malicious_tar("cli/large")
        with self.assertRaises(cm.Error):
            self.m.import_archive(a, cm.digest(a), max_bytes=0)


class Migration(Rig):
    def test_dry_run_unchanged(self):
        write(self.a["cli"] / "skills/demo/SKILL.md", "Hello")
        before = cm.inventory(self.b["cli"])
        r = self.m.migrate("alpha", "beta", "cli", ["skills"])
        self.assertTrue(r["dry_run"])
        self.assertEqual(cm.inventory(self.b["cli"]), before)
        self.assertFalse(self.m.journal.exists())

    def test_migrate_only_selected(self):
        write(self.a["cli"] / "skills/demo/SKILL.md", "Hello")
        write(self.a["cli"] / ".credentials.json", {"secret": "source"})
        write(self.b["cli"] / ".credentials.json", {"secret": "target"})
        write(self.a["cli"] / "settings.json", {"a": 1})
        r = self.m.migrate("alpha", "beta", "cli", ["skills"], dry_run=False)
        self.assertTrue(Path(r["backup"]).is_dir())
        self.assertTrue((self.b["cli"] / "skills/demo/SKILL.md").is_file())
        self.assertFalse((self.b["cli"] / "settings.json").exists())
        self.assertEqual(cm.object_json(self.b["cli"] / ".credentials.json")["secret"], "target")

    def test_conflict_aborts_both_scopes(self):
        write(self.a["cli"] / "settings.json", {"a": 1})
        write(self.b["cli"] / "settings.json", {"a": 2})
        before = cm.inventory(self.b["cli"])
        with self.assertRaises(cm.Error):
            self.m.migrate("alpha", "beta", "both", ["settings"], dry_run=False)
        self.assertEqual(before, cm.inventory(self.b["cli"]))
        self.assertFalse(self.m.journal.exists())

    def test_explicit_keep_replace(self):
        write(self.a["cli"] / "settings.json", {"a": 1})
        write(self.b["cli"] / "settings.json", {"a": 2})
        self.m.migrate("alpha", "beta", "cli", ["settings"], "keep", dry_run=False)
        self.assertEqual(cm.object_json(self.b["cli"] / "settings.json"), {"a": 2})
        self.m.migrate("alpha", "beta", "cli", ["settings"], "replace", dry_run=False)
        self.assertEqual(cm.object_json(self.b["cli"] / "settings.json"), {"a": 1})

    def test_rebase_plugins_and_history(self):
        old, new = str(self.a["cli"]), str(self.b["cli"])
        write(self.a["cli"] / "plugins/installed_plugins.json",
              {"path": old + "/plugins/cache/x", "not_a_path": "prefix " + old})
        write(self.a["cli"] / "projects/-old/one.jsonl",
              json.dumps({"cwd": "/old", "message": "/oldness"}) + "\n")
        self.m.migrate("alpha", "beta", "cli", ["plugins", "history"], dry_run=False,
                       mappings={"/old": "/new"})
        d = cm.object_json(self.b["cli"] / "plugins/installed_plugins.json")
        self.assertEqual(d["path"], new + "/plugins/cache/x")
        self.assertEqual(d["not_a_path"], "prefix " + old)
        d = json.loads((self.b["cli"] / "projects/-new/one.jsonl").read_text())
        self.assertEqual(d, {"cwd": "/new", "message": "/oldness"})

    def test_mcp_only_not_account(self):
        write(self.a["cli"] / ".claude.json",
              {"mcpServers": {"x": {"command": "node"}}, "oauthAccount": {"token": "source"}})
        write(self.b["cli"] / ".claude.json", {"oauthAccount": {"token": "target"}})
        self.m.migrate("alpha", "beta", "cli", ["settings"], dry_run=False)
        d = cm.object_json(self.b["cli"] / ".claude.json")
        self.assertEqual(d["oauthAccount"], {"token": "target"})
        self.assertIn("x", d["mcpServers"])

    def test_cli_credentials_only_explicit(self):
        write(self.a["cli"] / ".credentials.json", {"token": "source"})
        self.m.migrate("alpha", "beta", "cli", ["skills"], credentials=True, dry_run=False)
        self.assertEqual(cm.object_json(self.b["cli"] / ".credentials.json")["token"], "source")
        with self.assertRaises(cm.Error):
            self.m.migrate("alpha", "beta", "gui", ["settings"], credentials=True)

    def test_gui_permissions_reset_and_target_auth_preserved(self):
        ia, ib = self.index("alpha"), self.index("beta")
        self.session(ia)
        write(self.b["gui"] / "config.json", {"token": "target"})
        self.m.migrate("alpha", "beta", "gui", ["history"], dry_run=False)
        d = cm.object_json(ib / "local_test.json")
        self.assertEqual(d["bridgeSessionIds"], [])
        self.assertEqual(d["permissionMode"], "default")
        self.assertEqual(cm.object_json(self.b["gui"] / "config.json"), {"token": "target"})
        self.assertFalse((ib / "scheduled-tasks.json").exists())

    def test_gui_missing_or_ambiguous_index_refused(self):
        self.index("alpha")
        with self.assertRaises(cm.Error):
            self.m.migrate("alpha", "beta", "gui", ["history"])
        self.index("beta")
        self.index("beta", "other")
        with self.assertRaises(cm.Error):
            self.m.migrate("alpha", "beta", "gui", ["history"])

    def test_gui_worktree_refused(self):
        self.session(self.index("alpha"), worktreeName="branch-x")
        self.index("beta")
        with self.assertRaises(cm.Error):
            self.m.migrate("alpha", "beta", "gui", ["history"], dry_run=False)

    def test_gui_scratch_staged_before_commit(self):
        ia, ib = self.index("alpha"), self.index("beta")
        scratch = self.a["gui"] / "scratch/local_x"
        write(scratch / "code.txt", "unsaved")
        self.session(ia, cwd=str(scratch))
        self.m.migrate("alpha", "beta", "gui", ["history"], dry_run=False, workspaces=True)
        d = cm.object_json(ib / "local_test.json")
        self.assertEqual(d["cwd"], str(self.b["gui"] / "scratch/local_x"))
        self.assertEqual((Path(d["cwd"]) / "code.txt").read_text(), "unsaved")

    def test_gui_settings_no_epitaxy_or_routines(self):
        write(self.a["gui"] / "claude_desktop_config.json",
              {"mcpServers": {"x": {}}, "preferences": {"epitaxyPrefs": {"secret": "source"}}})
        self.m.migrate("alpha", "beta", "gui", ["settings"], dry_run=False)
        self.assertEqual(cm.object_json(self.b["gui"] / "claude_desktop_config.json"),
                         {"mcpServers": {"x": {}}})

    def test_divergent_transcripts_no_silent_merge(self):
        write(self.a["cli"] / "projects/p/x.jsonl", '{"a":1}\n')
        write(self.b["cli"] / "projects/p/x.jsonl", '{"b":2}\n')
        with self.assertRaises(cm.Error):
            self.m.migrate("alpha", "beta", "cli", ["history"], dry_run=False)
        self.assertEqual((self.b["cli"] / "projects/p/x.jsonl").read_text(), '{"b":2}\n')

    def test_symlink_subtree_not_followed(self):
        outside = self.home / "outside"
        outside.mkdir()
        write(outside / "keep", "safe")
        (self.b["cli"] / "skills").symlink_to(outside)
        write(self.a["cli"] / "skills/demo/SKILL.md", "new")
        with self.assertRaises(cm.Error):
            self.m.migrate("alpha", "beta", "cli", ["skills"], dry_run=False)
        self.assertEqual(list(outside.iterdir()), [outside / "keep"])

    def test_backup_as_source_does_not_change_backup(self):
        write(self.a["cli"] / "plugins/installed_plugins.json",
              {"path": str(self.a["cli"]) + "/plugins/cache/x"})
        b = self.m.backup("alpha", "cli")
        before = cm.inventory(b)
        self.m.migrate_backup(b, "beta", "cli", ["plugins"], dry_run=False)
        self.assertEqual(cm.inventory(b), before)
        d = cm.object_json(self.b["cli"] / "plugins/installed_plugins.json")
        self.assertEqual(d["path"], str(self.b["cli"]) + "/plugins/cache/x")
        self.assertFalse(any(n.startswith("backup-source-") for n in self.m.cfg["profiles"]))
        self.assertFalse(any(n.startswith("backup-source-")
                             for n in cm.object_json(self.m.state)["profiles"]))

    def test_backup_default_mcp_portable(self):
        self.m.create("system", cli=self.home / ".claude")
        write(self.home / ".claude.json", {"mcpServers": {"portable": {}}, "oauthAccount": "private"})
        b = self.m.backup("system", "cli")
        self.m.migrate_backup(b, "beta", "cli", ["settings"], dry_run=False)
        d = cm.object_json(self.b["cli"] / ".claude.json")
        self.assertEqual(d, {"mcpServers": {"portable": {}}})

    def test_target_default_adjacent_state(self):
        self.m.create("system", cli=self.home / ".claude")
        write(self.home / ".claude.json", {"oauthAccount": "keep"})
        write(self.a["cli"] / ".claude.json", {"mcpServers": {"x": {}}})
        self.m.migrate("alpha", "system", "cli", ["settings"], dry_run=False)
        self.assertEqual(cm.object_json(self.home / ".claude.json"),
                         {"oauthAccount": "keep", "mcpServers": {"x": {}}})
        self.assertFalse((self.home / ".claude/.claude.json").exists())

    def test_valid_worktree_registry_migrates_without_git_mutation(self):
        subprocess.run(["git", "init", "--quiet", str(self.cwd)], check=True)
        ia, ib = self.index("alpha"), self.index("beta")
        self.session(ia, worktreeName="working", worktreePath=str(self.cwd))
        registry = {"schemaVersion": 2,
                    "worktrees": {"working": {"name": "working", "path": str(self.cwd),
                                             "leasedBy": "local_test"}},
                    "originUrls": {}, "originPins": {},
                    "untrackedDirGc": {"sightings": {"bad": 1}}}
        write(self.a["gui"] / "git-worktrees.json", registry)
        self.m.migrate("alpha", "beta", "gui", ["history"],
                       workspaces=True, dry_run=False)
        d = cm.object_json(self.b["gui"] / "git-worktrees.json")
        self.assertEqual(d["worktrees"]["working"]["leasedBy"], "local_test")
        self.assertNotIn("untrackedDirGc", d)
        self.assertTrue((ib / "local_test.json").exists())

    def test_unknown_worktree_registry_refused(self):
        ia = self.index("alpha")
        self.index("beta")
        self.session(ia, worktreeName="working")
        write(self.a["gui"] / "git-worktrees.json", {"schemaVersion": 99})
        with self.assertRaises(cm.Error):
            self.m.migrate("alpha", "beta", "gui", ["history"],
                           workspaces=True, dry_run=False)

    def test_writer_appears_before_commit(self):
        write(self.a["cli"] / "skills/demo/SKILL.md", "new")
        self.m.processes = lambda: [(999, "claude", False)]
        with self.assertRaises(cm.Error):
            self.m.migrate("alpha", "beta", "cli", ["skills"], dry_run=False)
        self.assertFalse((self.b["cli"] / "skills").exists())

    def test_gui_requires_real_shared_transcript_when_id_present(self):
        self.session(self.index("alpha"), cliSessionId="session-123")
        self.index("beta")
        with self.assertRaises(cm.Error):
            self.m.migrate("alpha", "beta", "gui", ["history"], dry_run=False)
        write(self.home / ".claude/projects/project/session-123.jsonl", '{"type":"user"}\n')
        self.m.migrate("alpha", "beta", "gui", ["history"], dry_run=False)

    def test_real_scratch_workspaces_directory(self):
        ia, ib = self.index("alpha"), self.index("beta")
        scratch = self.a["gui"] / "scratch-workspaces/local_real"
        write(scratch / "file.txt", "unsaved work")
        self.session(ia, cwd=str(scratch))
        self.m.migrate("alpha", "beta", "gui", ["history"],
                       workspaces=True, dry_run=False)
        d = cm.object_json(ib / "local_test.json")
        self.assertEqual((Path(d["cwd"]) / "file.txt").read_text(), "unsaved work")


class Transactions(Rig):
    def test_rollback_after_second_rename_failure(self):
        write(self.b["cli"] / "original", "old")
        stage = self.m.stage(self.b["cli"])
        write(stage / "new", "new")
        real_replace = os.replace
        def replace(src, dst):
            if Path(src) == stage and Path(dst) == self.b["cli"]:
                raise OSError("simulated disk failure")
            return real_replace(src, dst)
        with mock.patch.object(cm.os, "replace", side_effect=replace):
            with self.assertRaises(OSError):
                self.m.transaction([(self.b["cli"], stage)])
        self.assertEqual((self.b["cli"] / "original").read_text(), "old")
        self.assertFalse((self.b["cli"] / "new").exists())
        self.assertFalse(self.m.journal.exists())

    def test_recover_after_installed_new_tree(self):
        target = self.b["cli"]
        write(target / "old", "old")
        stage = self.m.stage(target)
        write(stage / "new", "new")
        tx = "a" * 32
        old = target.parent / (".cm-old-" + tx + "-" + target.name)
        os.replace(target, old)
        os.replace(stage, target)
        cm.atomic_json(self.m.journal, {"format": 1, "id": tx, "phase": "applying",
                                       "entries": [{"target": str(target), "stage": str(stage),
                                                    "old": str(old), "existed": True}]})
        self.m.recover()
        self.assertFalse((target / "new").exists())
        self.assertTrue((target / "old").exists())
        self.assertTrue(list(target.parent.glob(".cm-recovered-*")))

    def test_committed_recovery_does_not_rollback(self):
        target = self.b["cli"]
        stage = target.parent / (".cm-stage-" + "b" * 32)
        tx = "b" * 32
        old = target.parent / (".cm-old-" + tx + "-" + target.name)
        write(target / "committed", "new")
        cm.atomic_json(self.m.journal, {"format": 1, "id": tx, "phase": "committed",
                                       "entries": [{"target": str(target), "stage": str(stage),
                                                    "old": str(old), "existed": True}]})
        self.m.recover()
        self.assertTrue((target / "committed").exists())

    def test_unsafe_journal_refused(self):
        cm.atomic_json(self.m.journal, {"format": 1, "id": "a" * 32, "phase": "applying",
                                       "entries": [{"target": "/etc", "stage": "/tmp/x",
                                                    "old": "/tmp/y", "existed": True}]})
        with self.assertRaises(cm.Error):
            self.m.recover()

    def test_busy_profile_lock(self):
        with self.m.lock(["alpha"], shared=True):
            with self.assertRaises(cm.Error):
                with self.m.lock(["alpha"]):
                    pass

    def test_pending_blocks_new_operation(self):
        write(self.m.journal, {})
        with self.assertRaises(cm.Error):
            with self.m.lock(["alpha"]):
                pass

    def test_running_writer_refused(self):
        self.m.processes = lambda: [(123, "claude", False)]
        with self.assertRaises(cm.Error):
            self.m.cold()


class ProjectsAndLaunchers(Rig):
    def test_project_copy_with_dirty_files(self):
        src = self.home / "src"
        src.mkdir()
        subprocess.run(["git", "init", "--quiet", str(src)], check=True)
        write(src / "untracked.txt", "dirty")
        dst = self.home / "dst"
        self.m.project_copy("beta", src, dst)
        self.assertFalse(dst.exists())
        self.m.project_copy("beta", src, dst, dry_run=False)
        self.assertEqual((dst / "untracked.txt").read_text(), "dirty")
        with self.assertRaises(cm.Error):
            self.m.project_copy("beta", src, dst, dry_run=False)

    def test_linked_worktree_refused(self):
        src = self.home / "src"
        write(src / ".git", "gitdir: /elsewhere")
        with self.assertRaises(cm.Error):
            self.m.project_copy("beta", src, self.home / "dst", False)

    def test_git_alternates_refused(self):
        src = self.home / "src"
        write(src / ".git/objects/info/alternates", "/outside/objects\n")
        with self.assertRaises(cm.Error):
            self.m.project_copy("beta", src, self.home / "dst", False)

    def test_registered_worktrees_refused_for_project_copy(self):
        src = self.home / "src"
        write(src / ".git/worktrees/other/gitdir", "/outside/.git\n")
        with self.assertRaises(cm.Error):
            self.m.project_copy("beta", src, self.home / "dst", False)

    def test_absolute_internal_project_link_rebased(self):
        src = self.home / "src"
        write(src / "files/a.txt", "original")
        (src / "link").symlink_to(src / "files/a.txt")
        dst = self.home / "dst"
        self.m.project_copy("beta", src, dst, False)
        self.assertEqual(os.readlink(dst / "link"), "files/a.txt")
        write(src / "files/a.txt", "changed")
        self.assertEqual((dst / "link").read_text(), "original")

    def test_nested_submodule_pointer_refused(self):
        src = self.home / "src"
        write(src / "sub/.git", "gitdir: ../.git/modules/sub")
        with self.assertRaises(cm.Error):
            self.m.project_copy("beta", src, self.home / "dst", False)

    def test_external_project_symlink_refused(self):
        src = self.home / "src"
        src.mkdir()
        (src / "outside").symlink_to("/etc/passwd")
        with self.assertRaises(cm.Error):
            self.m.project_copy("beta", src, self.home / "dst", False)

    def test_launchers_and_plist(self):
        result = self.m.launchers("alpha")
        self.assertTrue(Path(result["cli"]).is_symlink())
        app = Path(result["gui"])
        plist = plistlib.loads((app / "Contents/Info.plist").read_bytes())
        self.assertEqual(plist["CFBundleExecutable"], "launcher")
        launcher = app / "Contents/MacOS/launcher"
        subprocess.run(["/bin/sh", "-n", str(launcher)], check=True)
        self.m.launchers("alpha")  # idempotent owned regeneration

    def test_no_unowned_launcher_overwrite(self):
        bindir = self.root / "sbin"
        bindir.mkdir()
        write(bindir / "claude-alpha", "do not overwrite")
        with self.assertRaises(cm.Error):
            self.m.launchers("alpha")

    def test_path_idempotent_and_quoted(self):
        with mock.patch.dict(os.environ, {"SHELL": "/bin/zsh"}):
            r = self.m.path_setup(True)
            rc = Path(r["file"])
            first = rc.read_text()
            self.m.path_setup(True)
            self.assertEqual(first, rc.read_text())
            subprocess.run(["/bin/bash", "-n", str(rc)], check=True)
            p = subprocess.run(["/bin/bash", "-c", '. "$1"; . "$1"; printf "%s" "$PATH"',
                                "bash", str(rc)], text=True, capture_output=True, check=True)
            self.assertEqual(p.stdout.split(":").count(str(self.root / "sbin")), 1)

    def test_shell_rc_backup(self):
        write(self.home / ".profile", "# original\n")
        with mock.patch.dict(os.environ, {"SHELL": "/bin/bash"}):
            self.m.path_setup(True)
        backups = list((self.root / "shell-backups").iterdir())
        self.assertEqual(backups[0].read_text(), "# original\n")

    def test_recursive_binary_refused(self):
        self.m.cfg["binary"] = str(SOURCE)
        with self.assertRaises(cm.Error):
            self.m.find_binary()

    def test_gui_duplicate_returns_without_open(self):
        marker = "--user-data-dir=" + str(self.a["gui"])
        self.m.processes = lambda: [(888, "/Applications/Claude.app/Contents/MacOS/Claude " + marker, True)]
        with mock.patch.object(cm.sys, "platform", "darwin"), \
                mock.patch.object(cm.subprocess, "run") as run:
            self.assertEqual(self.m.launch_gui("alpha"), 0)
            run.assert_not_called()

    def test_gui_other_profile_refused(self):
        self.m.processes = lambda: [(888, "other", True)]
        with mock.patch.object(cm.sys, "platform", "darwin"), self.assertRaises(cm.Error):
            self.m.launch_gui("alpha")

    def test_gui_open_command_and_confirmation(self):
        app = self.home / "Applications/Claude.app"
        write(app / "Contents/MacOS/Claude", "")
        self.m.cfg["gui_app"] = str(app)
        marker = "--user-data-dir=" + str(self.a["gui"])
        self.m.processes = mock.Mock(side_effect=[
            [], [(777, str(app / "Contents/MacOS/Claude") + " " + marker, True)]])
        with mock.patch.object(cm.sys, "platform", "darwin"), \
                mock.patch.object(cm.subprocess, "run") as run:
            self.assertEqual(self.m.launch_gui("alpha"), 0)
            args = run.call_args.args[0]
            self.assertEqual(args, ["/usr/bin/open", "-n", "-a", str(app), "--args", marker])

    def test_bundle_identifiers_do_not_collide(self):
        self.m.create("alpha_test")
        self.m.create("alpha-test")
        ids = []
        for n in ("alpha_test", "alpha-test"):
            result = self.m.launchers(n)
            ids.append(plistlib.loads((Path(result["gui"]) / "Contents/Info.plist").read_bytes())
                       ["CFBundleIdentifier"])
        self.assertNotEqual(ids[0], ids[1])

    def test_settings_edit_validates_and_backs_up(self):
        write(self.a["cli"] / "settings.json", {"old": 1})
        def editor(args, **kw):
            write(Path(args[-1]), {"new": 2})
        with mock.patch.object(cm.subprocess, "run", side_effect=editor):
            result = self.m.edit_settings("alpha", "cli")
        self.assertTrue(Path(result["backup"]).is_dir())
        self.assertEqual(cm.object_json(self.a["cli"] / "settings.json"), {"new": 2})

    def test_settings_editor_invalid_json_preserves_original(self):
        write(self.a["cli"] / "settings.json", {"old": 1})
        def editor(args, **kw):
            write(Path(args[-1]), "{broken")
        with mock.patch.object(cm.subprocess, "run", side_effect=editor), self.assertRaises(cm.Error):
            self.m.edit_settings("alpha", "cli")
        self.assertEqual(cm.object_json(self.a["cli"] / "settings.json"), {"old": 1})


class EndToEnd(unittest.TestCase):
    def make_install(self, root, fake_body):
        root.mkdir()
        script = root / "claude-manager.py"
        shutil.copy2(SOURCE, script)
        script.chmod(0o700)
        fake = root / "real-claude"
        fake.write_text("#!" + sys.executable + "\n" + fake_body)
        fake.chmod(0o700)
        env = dict(os.environ, HOME=str(root.parent))
        for args in (["create", "test", "--yes"], ["set-binary", str(fake)],
                     ["launchers", "test"]):
            p = subprocess.run([sys.executable, str(script), *args], env=env,
                               text=True, capture_output=True)
            self.assertEqual(p.returncode, 0, p.stderr)
        return root / "sbin/claude-test", env

    def test_symlink_exec_streams_arguments_exit_and_auth(self):
        with tempfile.TemporaryDirectory(prefix="cm-e2e-") as tmp:
            root = Path(tmp).resolve() / "installation with spaces"
            root.mkdir()
            script = root / "claude-manager.py"
            shutil.copy2(SOURCE, script)
            script.chmod(0o700)
            fake = root / "real-claude"
            fake.write_text("#!" + sys.executable + "\n"
                            "import sys,os,json\n"
                            "print(json.dumps({'args':sys.argv[1:],"
                            "'config':os.environ['CLAUDE_CONFIG_DIR'],"
                            "'input':sys.stdin.read(),'secret':os.environ.get('ANTHROPIC_API_KEY')}))\n"
                            "print('native stderr',file=sys.stderr)\n"
                            "sys.exit(23)\n")
            fake.chmod(0o700)
            env = dict(os.environ, HOME=str(root.parent))
            def call(*args, **kw):
                return subprocess.run([sys.executable, str(script), *args],
                                      env=env, text=True, capture_output=True, **kw)
            self.assertEqual(call("create", "test", "--yes").returncode, 0)
            self.assertEqual(call("set-binary", str(fake)).returncode, 0)
            self.assertEqual(call("launchers", "test").returncode, 0)
            link = root / "sbin/claude-test"
            env["ANTHROPIC_API_KEY"] = "must-not-leak"
            args = ["--print", "spaces and 'quotes'", "--", "-x", ""]
            p = subprocess.run([str(link), *args], input="hello\n", env=env,
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 23)
            self.assertEqual(p.stderr, "native stderr\n")
            d = json.loads(p.stdout)
            self.assertEqual(d["args"], args)
            self.assertEqual(d["input"], "hello\n")
            self.assertIsNone(d["secret"])
            self.assertEqual(d["config"], str(root / "data/claude-test"))
            # Persistent per-profile lock is released on real child exit.
            m = cm.Manager(root, Path(tmp).resolve())
            with m.lock(["test"]):
                pass

    def test_direct_without_tty_fails_cleanly(self):
        p = subprocess.run([sys.executable, str(SOURCE)], input="", text=True,
                           capture_output=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("Administration requires a terminal", p.stderr)

    def test_all_three_streams_remain_tty(self):
        import pty
        with tempfile.TemporaryDirectory(prefix="cm-tty-") as tmp:
            link, env = self.make_install(Path(tmp).resolve() / "install",
                                         "import os,json\n"
                                         "print(json.dumps([os.isatty(i) for i in (0,1,2)]))\n")
            master, slave = pty.openpty()
            try:
                p = subprocess.Popen([str(link)], env=env, stdin=slave, stdout=slave, stderr=slave)
                os.close(slave)
                slave = None
                data = b""
                while True:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    data += chunk
                self.assertEqual(p.wait(timeout=5), 0)
                self.assertEqual(json.loads(data.decode()), [True, True, True])
            finally:
                os.close(master)
                if slave is not None:
                    os.close(slave)

    def test_exec_retains_profile_lock_until_real_cli_exits(self):
        with tempfile.TemporaryDirectory(prefix="cm-lock-") as tmp:
            root = Path(tmp).resolve() / "install"
            link, env = self.make_install(
                root, "import sys\nprint('READY',flush=True)\nsys.stdin.read()\n")
            p = subprocess.Popen([str(link)], env=env, stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(p.stdout.readline().strip(), "READY")
                manager = cm.Manager(root, Path(tmp).resolve())
                with self.assertRaises(cm.Error):
                    with manager.lock(["test"]):
                        pass
                p.communicate("finish", timeout=5)
                with manager.lock(["test"]):
                    pass
            finally:
                if p.poll() is None:
                    p.kill()
                    p.communicate()


class Tools(Rig):
    def setUp(self):
        super().setUp()
        self.m.tool_processes = lambda tool: []

    def test_create_layouts_and_env(self):
        for tool in cm.TOOLS:
            with self.subTest(tool=tool):
                self.m.tool_create(tool, "work")
                root = self.root / "tools" / tool / "work"
                self.assertTrue(root.is_dir())
                env = self.m.tool_env(tool, "work")
                if tool == "codex":
                    self.assertEqual(env, {"CODEX_HOME": str(root)})
                    self.assertIn('cli_auth_credentials_store = "file"',
                                  (root / "config.toml").read_text())
                elif tool == "gemini":
                    self.assertEqual(env, {"GEMINI_CLI_HOME": str(root)})
                    self.assertTrue((root / ".gemini").is_dir())
                elif tool == "grok":
                    self.assertEqual(env, {"GROK_HOME": str(root), "GROK_DISABLE_AUTOUPDATER": "1"})
                elif tool == "copilot":
                    self.assertEqual(env["COPILOT_HOME"], str(root))
                    self.assertEqual(env["COPILOT_CACHE_HOME"], str(self.root / "cache/copilot-work"))
                else:
                    self.assertEqual(env["XDG_DATA_HOME"], str(root / "data"))
                    self.assertEqual(env["XDG_CONFIG_HOME"], str(root / "config"))
                    self.assertEqual(env["XDG_STATE_HOME"], str(root / "state"))
                    self.assertEqual(env["XDG_CACHE_HOME"], str(self.root / "cache/opencode-work"))

    def test_same_name_independent_per_tool_and_duplicates_refused(self):
        self.m.tool_create("codex", "alpha")
        self.m.tool_create("gemini", "alpha")
        with self.assertRaises(cm.Error):
            self.m.tool_create("codex", "alpha")
        with self.assertRaises(cm.Error):
            self.m.tool_create("nope", "x")

    def test_register_existing_without_modifying(self):
        codex = self.home / ".codex"
        write(codex / "config.toml", "model = 'x'\n")
        self.m.tool_create("codex", "default", codex, existing=True)
        self.assertEqual((codex / "config.toml").read_text(), "model = 'x'\n")
        with self.assertRaises(cm.Error):
            self.m.tool_create("opencode", "default", self.home / ".local/share/opencode", existing=True)
        with self.assertRaises(cm.Error):  # ~ itself is never a managed root
            self.m.tool_create("gemini", "default", self.home, existing=True)
        gem = self.home / "gemhome"
        (gem / ".gemini").mkdir(parents=True)
        self.m.tool_create("gemini", "default", gem, existing=True)

    def test_overlap_with_claude_and_other_tools_refused(self):
        with self.assertRaises(cm.Error):
            self.m.tool_create("codex", "x", self.a["cli"] / "nested")
        self.m.tool_create("codex", "x")
        with self.assertRaises(cm.Error):
            self.m.tool_create("gemini", "y", self.root / "tools/codex/x/sub")
        with self.assertRaises(cm.Error):
            self.m.create("gamma", cli=self.root / "tools/codex/x/inner")

    def test_unregister_keeps_data(self):
        self.m.tool_create("copilot", "w")
        root = self.m.tool_root("copilot", "w")
        write(root / "settings.json", {})
        self.m.tool_unregister("copilot", "w")
        self.assertTrue((root / "settings.json").exists())
        with self.assertRaises(cm.Error):
            self.m.tool_profile("copilot", "w")

    def test_backup_verify_restore(self):
        self.m.tool_create("codex", "w")
        root = self.m.tool_root("codex", "w")
        write(root / "auth.json", {"t": "old"})
        b = self.m.tool_backup("codex", "w")
        self.assertEqual(self.m.tool_verify(b)["tool"], "codex")
        write(root / "auth.json", {"t": "new"})
        pre = self.m.tool_restore("codex", "w", b)
        self.assertEqual(json.loads((root / "auth.json").read_text()), {"t": "old"})
        self.assertEqual(json.loads((pre / "data/auth.json").read_text()), {"t": "new"})
        write(b / "data/auth.json", {"t": "tampered"})
        with self.assertRaises(cm.Error):
            self.m.tool_verify(b)

    def test_restore_to_other_profile_refused(self):
        self.m.tool_create("codex", "a")
        self.m.tool_create("codex", "b")
        b = self.m.tool_backup("codex", "a")
        with self.assertRaises(cm.Error):
            self.m.tool_restore("codex", "b", b)

    def test_running_tool_blocks_data_operation(self):
        self.m.tool_processes = lambda tool: [(42, "/usr/local/bin/codex")]
        with self.assertRaises(cm.Error):
            self.m.tool_cold("codex")

    def test_process_detection_patterns(self):
        out = "  1 /opt/homebrew/bin/codex exec\n  2 node /x/@google/gemini-cli/dist/index.js\n" \
              "  3 /bin/zsh\n  4 /x/sbin/codex-work\n"
        result = subprocess.CompletedProcess([], 0, stdout=out, stderr="")
        m = cm.Manager(self.root, self.home)
        with mock.patch.object(cm.subprocess, "run", return_value=result):
            self.assertEqual([p for p, _ in m.tool_processes("codex")], [1])
            self.assertEqual([p for p, _ in m.tool_processes("gemini")], [2])
            self.assertEqual(m.tool_processes("opencode"), [])

    def test_recursive_binary_refused(self):
        link = self.home / "codex"
        link.symlink_to(SOURCE)
        with self.assertRaises(cm.Error):
            self.m.tool_set_binary("codex", str(link))
        self.assertEqual(self.m.tool_registry("codex").get("binary", ""), "")


class ToolExec(unittest.TestCase):
    def test_symlink_launch_env_isolation_args_and_exit(self):
        with tempfile.TemporaryDirectory(prefix="cm-tool-") as tmp:
            root = Path(tmp).resolve() / "install dir"
            root.mkdir()
            script = root / "claude-manager.py"
            shutil.copy2(SOURCE, script)
            script.chmod(0o700)
            env = dict(os.environ, HOME=str(root.parent))
            for k in ("CODEX_HOME", "GEMINI_CLI_HOME", "COPILOT_HOME", "XDG_DATA_HOME"):
                env.pop(k, None)
            def call(*args):
                return subprocess.run([sys.executable, str(script), *args], env=env,
                                      text=True, capture_output=True)
            for tool in cm.TOOLS:
                fake = root / ("real-" + tool)
                fake.write_text("#!" + sys.executable + "\n"
                                "import sys,os,json\n"
                                "keys=['CODEX_HOME','GEMINI_CLI_HOME','COPILOT_HOME',"
                                "'COPILOT_CACHE_HOME','XDG_CONFIG_HOME','XDG_DATA_HOME',"
                                "'XDG_STATE_HOME','XDG_CACHE_HOME','CODEX_API_KEY','GH_TOKEN','GROK_HOME',"
                                "'GEMINI_API_KEY','OPENCODE_CONFIG','KEEP']\n"
                                "print(json.dumps({'args':sys.argv[1:],"
                                "'env':{k:os.environ.get(k) for k in keys}}))\n"
                                "sys.exit(7)\n")
                fake.chmod(0o700)
                for args in (["tool-create", tool, "w", "--yes"], ["tool-set-binary", tool, str(fake)],
                             ["tool-launchers", tool, "w"]):
                    p = call(*args)
                    self.assertEqual(p.returncode, 0, p.stderr)
            secrets = {"CODEX_API_KEY": "x", "GH_TOKEN": "x", "GEMINI_API_KEY": "x",
                       "OPENCODE_CONFIG": "/elsewhere.json", "KEEP": "kept"}
            run_env = dict(env, **secrets)
            for tool in cm.TOOLS:
                with self.subTest(tool=tool):
                    link = root / "sbin" / (tool + "-w")
                    p = subprocess.run([str(link), "--flag", "a b", ""], env=run_env,
                                       text=True, capture_output=True)
                    self.assertEqual(p.returncode, 7, p.stderr)
                    d = json.loads(p.stdout)
                    self.assertEqual(d["args"], ["--flag", "a b", ""])
                    e = d["env"]
                    prof = str(root / "tools" / tool / "w")
                    self.assertEqual(e["KEEP"], "kept")
                    expected = {"codex": ("CODEX_HOME", prof), "gemini": ("GEMINI_CLI_HOME", prof),
                                "copilot": ("COPILOT_HOME", prof), "grok": ("GROK_HOME", prof),
                                "opencode": ("XDG_DATA_HOME", prof + "/data")}[tool]
                    self.assertEqual(e[expected[0]], expected[1])
                    leaked = {k for k in ("CODEX_API_KEY", "GH_TOKEN", "GEMINI_API_KEY",
                                          "OPENCODE_CONFIG") if e[k] is not None}
                    owned = set(cm.TOOLS[tool]["auth_env"])
                    self.assertFalse(leaked & owned, leaked)
            # Explicit inherit keeps the variables for that profile only.
            self.assertEqual(call("tool-auth-env", "copilot", "w", "inherit").returncode, 0)
            p = subprocess.run([str(root / "sbin/copilot-w")], env=run_env, text=True,
                               capture_output=True)
            self.assertEqual(json.loads(p.stdout)["env"]["GH_TOKEN"], "x")
            listing = json.loads(call("tool-list").stdout)
            self.assertTrue(listing["opencode"]["profiles"]["w"]["launcher"].endswith("opencode-w"))


class ToolMigration(Rig):
    def setUp(self):
        super().setUp()
        self.m.tool_processes = lambda tool: []

    def seed_codex(self):
        self.m.tool_create("codex", "src")
        self.m.tool_create("codex", "dst")
        src = self.m.tool_root("codex", "src")
        write(src / "config.toml", 'model = "gpt"\ncli_auth_credentials_store = "keyring"\n')
        write(src / "AGENTS.md", "rules")
        write(src / "skills/a/SKILL.md", "skill")
        write(src / "auth.json", {"token": "secret"})
        write(src / "sessions/2026/11/05/rollout-1.jsonl", "{}\n")
        write(src / "history.jsonl", "{}\n")
        write(src / "state_5.sqlite", "db")
        write(src / "log/codex-tui.log", "noise")
        return src, self.m.tool_root("codex", "dst")

    def test_classification(self):
        c = self.m.tool_classify
        self.assertEqual(c("codex", "auth.json"), "credentials")
        self.assertEqual(c("codex", "sessions/x.jsonl"), "history")
        self.assertEqual(c("codex", "state_5.sqlite-wal"), "history")
        self.assertEqual(c("codex", "log/a.log"), "ephemeral")
        self.assertEqual(c("codex", "skills/a/SKILL.md"), "settings")
        self.assertEqual(c("gemini", ".gemini/oauth_creds.json"), "credentials")
        self.assertEqual(c("gemini", ".gemini/settings.json"), "settings")
        self.assertEqual(c("copilot", "config.json"), "credentials")
        self.assertEqual(c("copilot", "permissions-config.json"), "credentials")
        self.assertEqual(c("copilot", "session-state/x"), "history")
        self.assertEqual(c("opencode", "data/opencode/auth.json"), "credentials")
        self.assertEqual(c("opencode", "data/opencode/opencode.db"), "history")
        self.assertEqual(c("opencode", "config/opencode/opencode.json"), "settings")

    def test_dry_run_changes_nothing(self):
        src, dst = self.seed_codex()
        before = cm.inventory(dst)
        r = self.m.tool_migrate("codex", "src", "dst", ["settings"], "replace")
        self.assertTrue(r["dry_run"])
        self.assertEqual(cm.inventory(dst), before)
        self.assertEqual(r["by_class"], {"settings": 3})

    def test_settings_only_without_credentials_or_logs(self):
        src, dst = self.seed_codex()
        r = self.m.tool_migrate("codex", "src", "dst", ["settings"], "replace", dry_run=False)
        self.assertEqual((dst / "AGENTS.md").read_text(), "rules")
        self.assertTrue((dst / "skills/a/SKILL.md").exists())
        self.assertFalse((dst / "auth.json").exists())
        self.assertFalse((dst / "sessions").exists())
        self.assertFalse((dst / "log").exists())
        # Target keeps its own file-based login store; source model setting arrives.
        cfg = (dst / "config.toml").read_text()
        self.assertIn('cli_auth_credentials_store = "file"', cfg)
        self.assertNotIn("keyring", cfg)
        self.assertIn('model = "gpt"', cfg)
        self.assertTrue(r["kept_target_auth_store"])
        self.assertEqual(self.m.tool_verify(Path(r["target_backup"]))["profile"], "dst")

    def test_history_and_explicit_credentials(self):
        src, dst = self.seed_codex()
        self.m.tool_migrate("codex", "src", "dst", ["history"], "error", credentials=True, dry_run=False)
        self.assertTrue((dst / "sessions/2026/11/05/rollout-1.jsonl").exists())
        self.assertTrue((dst / "state_5.sqlite").exists())
        self.assertTrue((dst / "auth.json").exists())
        self.assertFalse((dst / "AGENTS.md").exists())

    def test_conflicts(self):
        src, dst = self.seed_codex()
        write(dst / "AGENTS.md", "target")
        with self.assertRaises(cm.Error) as e:
            self.m.tool_migrate("codex", "src", "dst", ["settings"], "error")
        self.assertIn("AGENTS.md", str(e.exception))
        self.m.tool_migrate("codex", "src", "dst", ["settings"], "keep", dry_run=False)
        self.assertEqual((dst / "AGENTS.md").read_text(), "target")
        self.m.tool_migrate("codex", "src", "dst", ["settings"], "replace", dry_run=False)
        self.assertEqual((dst / "AGENTS.md").read_text(), "rules")

    def test_running_tool_and_bad_input_refused(self):
        self.seed_codex()
        for args in ((["nope"],), ([],)):
            with self.assertRaises(cm.Error):
                self.m.tool_migrate("codex", "src", "dst", *args)
        with self.assertRaises(cm.Error):
            self.m.tool_migrate("codex", "src", "src", ["settings"])
        self.m.tool_processes = lambda tool: [(5, "codex")]
        with self.assertRaises(cm.Error):
            self.m.tool_migrate("codex", "src", "dst", ["settings"])

    def test_symlinks_not_followed(self):
        src, dst = self.seed_codex()
        outside = self.home / "outside"
        write(outside / "secret.txt", "x")
        (src / "linked").symlink_to(outside)
        self.m.tool_migrate("codex", "src", "dst", ["settings"], "replace", dry_run=False)
        self.assertTrue((dst / "linked").is_symlink())
        self.assertFalse((dst / "secret.txt").exists())

    def test_export_import_and_migrate_from_backup(self):
        src, dst = self.seed_codex()
        (src / "rel-link").symlink_to("AGENTS.md")
        (src / "abs-link").symlink_to(src / "AGENTS.md")
        b = self.m.tool_backup("codex", "src")
        out = self.home / "export/codex.tar.gz"
        self.m.tool_export(b, out)
        sha = (out.parent / "codex.tar.gz.sha256").read_text().split()[0]
        with self.assertRaises(cm.Error):
            self.m.tool_import(out, "0" * 64)
        imported = self.m.tool_import(out, sha)
        self.assertEqual(imported.parent, self.root / "tool-backups")
        self.assertEqual(os.readlink(imported / "data/abs-link"), "AGENTS.md")
        r = self.m.tool_migrate("codex", imported, "dst", ["settings", "history"], "replace",
                                dry_run=False, from_backup=True)
        self.assertEqual((dst / "AGENTS.md").read_text(), "rules")
        self.assertTrue((dst / "sessions/2026/11/05/rollout-1.jsonl").exists())
        self.assertFalse((dst / "auth.json").exists())
        self.m.tool_create("gemini", "g")
        with self.assertRaises(cm.Error):  # backup of another tool
            self.m.tool_migrate("gemini", imported, "g", ["settings"], from_backup=True)

    def test_import_refuses_foreign_layout(self):
        evil = self.home / "evil.tar.gz"
        with tarfile.open(evil, "w:gz") as tar:
            data = b"x"
            info = tarfile.TarInfo("cli/settings.json")
            info.size = 1
            tar.addfile(info, io.BytesIO(data))
        sha = hashlib.sha256(evil.read_bytes()).hexdigest()
        with self.assertRaises(cm.Error):
            self.m.tool_import(evil, sha)
        self.assertEqual(list((self.root / "tool-backups").iterdir()), [])


class Grok(Rig):
    def setUp(self):
        super().setUp()
        self.m.tool_processes = lambda tool: []

    def test_registered_default_home_keeps_autoupdater(self):
        grok = self.home / ".grok"
        write(grok / "config.toml", "")
        self.m.tool_create("grok", "default", grok, existing=True)
        self.assertEqual(self.m.tool_env("grok", "default"), {"GROK_HOME": str(grok)})

    def test_installer_binary_preferred_over_path_namesake(self):
        real = self.home / ".grok/bin/grok"
        write(real, "#!/bin/sh\n")
        real.chmod(0o700)
        brew = self.home / "brew/bin/grok"  # unrelated Homebrew regex tool
        write(brew, "#!/bin/sh\n")
        brew.chmod(0o700)
        with mock.patch.dict(os.environ, {"PATH": str(brew.parent)}):
            self.assertEqual(self.m.find_tool_binary("grok"), real)
            real.unlink()
            self.assertEqual(self.m.find_tool_binary("grok"), brew)

    def test_migration_classes(self):
        c = self.m.tool_classify
        for rel, kind in (("auth.json", "credentials"), ("agent_id", "credentials"),
                          ("trusted_folders.toml", "credentials"), ("sessions/x/s.jsonl", "history"),
                          ("memory-v2/index", "history"), ("worktrees.db", "history"),
                          ("downloads/grok-1.0.70-macos-aarch64", "ephemeral"), ("bin/grok", "ephemeral"),
                          ("leader.lock", "ephemeral"), ("auth.json.lock", "ephemeral"),
                          ("logs/unified.jsonl", "ephemeral"), ("config.toml", "settings"),
                          ("sandbox.toml", "settings"), ("skills/a/SKILL.md", "settings"),
                          ("installed-plugins/p/plugin.json", "settings")):
            with self.subTest(rel=rel):
                self.assertEqual(c("grok", rel), kind)

    def test_migration_never_copies_binary_or_login(self):
        self.m.tool_create("grok", "a")
        self.m.tool_create("grok", "b")
        a, b = self.m.tool_root("grok", "a"), self.m.tool_root("grok", "b")
        write(a / "config.toml", "[cli]\n")
        write(a / "skills/x/SKILL.md", "s")
        write(a / "auth.json", {"token": "t"})
        write(a / "downloads/grok-1.0.70-macos-aarch64", "binary")
        write(a / "sessions/p/s.jsonl", "{}")
        self.m.tool_migrate("grok", "a", "b", ["settings"], dry_run=False)
        self.assertTrue((b / "skills/x/SKILL.md").exists())
        for rel in ("auth.json", "downloads", "sessions"):
            self.assertFalse((b / rel).exists(), rel)


@unittest.skipUnless(os.access(os.path.expanduser("~/.grok/bin/grok"), os.X_OK), "grok not installed")
class GrokReal(unittest.TestCase):
    """End-to-end with the real Grok Build CLI: a new profile is signed out and isolated."""
    def test_profile_isolated_and_signed_out(self):
        with tempfile.TemporaryDirectory(prefix="cm-grok-") as tmp:
            root = Path(tmp).resolve() / "install"
            root.mkdir()
            script = root / "claude-manager.py"
            shutil.copy2(SOURCE, script)
            env = {k: v for k, v in os.environ.items() if k not in cm.TOOLS["grok"]["auth_env"]}
            env.pop("GROK_HOME", None)
            for args in (["tool-create", "grok", "w", "--yes"],
                         ["tool-set-binary", "grok", os.path.expanduser("~/.grok/bin/grok")]):
                p = subprocess.run([sys.executable, str(script), *args], env=env, text=True,
                                   capture_output=True)
                self.assertEqual(p.returncode, 0, p.stderr)
            p = subprocess.run([sys.executable, str(script), "tool-run", "grok", "w", "models"],
                               env=env, text=True, capture_output=True, timeout=120, cwd=tmp)
            self.assertIn("not authenticated", p.stdout + p.stderr)
            self.assertTrue((root / "tools/grok/w/config.toml").exists())


if __name__ == "__main__":
    unittest.main()
