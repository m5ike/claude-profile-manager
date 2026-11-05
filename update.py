#!/usr/bin/env python3
"""Cold, backed-up in-place code update and bounded shell PATH repair. No profile data copying."""
import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
import uuid
import types
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
PAYLOAD = ("claude-manager.py", "README.cs.md", "install.sh", "update.py", "update.sh",
           "run-tests.sh", "tests/test_manager.py", "tests/test_update.py",
           "TEST_REPORT.md", "test-output.txt", ".gitignore", "SHA256SUMS")
EXECUTABLES = {"claude-manager.py", "install.sh", "update.py", "update.sh", "run-tests.sh"}


def load_manager(source, destination):
    entries = (source / "SHA256SUMS").read_text().splitlines()
    expected = [line.split("  ", 1)[0] for line in entries if line.endswith("  claude-manager.py")]
    candidate = source / "claude-manager.py"
    if candidate.is_symlink():
        raise RuntimeError("Candidate manager must not be a symlink")
    candidate_bytes = candidate.read_bytes()
    if (len(expected) != 1 or
            hashlib.sha256(candidate_bytes).hexdigest() != expected[0]):
        raise RuntimeError("Candidate manager checksum mismatch before import")
    module = types.ModuleType("cm_update_candidate")
    module.__file__ = str(candidate)
    exec(compile(candidate_bytes, str(candidate), "exec"), module.__dict__)
    module.SCRIPT = destination / "claude-manager.py"
    module.ROOT = destination
    return module


def verify_release(module, source):
    hashes = {}
    for line in (source / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match or match[2] in hashes:
            raise module.Error("Invalid/duplicate release checksum entry")
        hashes[match[2]] = match[1]
    payload = {}
    for rel in PAYLOAD:
        p = module.safe_abs(source / rel)
        if not p.is_file():
            raise module.Error("Missing release file: " + rel)
        if rel != "SHA256SUMS" and (rel not in hashes or module.digest(p) != hashes[rel]):
            raise module.Error("Release checksum mismatch: " + rel)
        payload[rel] = p.read_bytes()
        if rel.endswith(".py"):
            compile(payload[rel], str(p), "exec")
    # Verify the exact in-memory bytes that will be installed, not just a prior read.
    import hashlib
    for rel, data in payload.items():
        if rel != "SHA256SUMS" and hashlib.sha256(data).hexdigest() != hashes[rel]:
            raise module.Error("Release changed during verification: " + rel)
    return payload


def shell_paths(module, home):
    paths = [home / ".profile", home / ".zshrc"]
    for name in (".zprofile", ".zshenv", ".bash_profile", ".bashrc", ".bash_login"):
        if (home / name).exists() or (home / name).is_symlink():
            paths.append(home / name)
    zdot = os.environ.get("ZDOTDIR")
    if zdot:
        zdot = module.safe_abs(zdot)
        for name in (".zshrc", ".zprofile", ".zshenv"):
            if name == ".zshrc" or (zdot / name).exists():
                paths.append(zdot / name)
    return list(dict.fromkeys(paths))


def path_block(root):
    quoted = shlex.quote(str(root / "sbin"))
    return (f"# BEGIN CLAUDE PROFILE MANAGER {root}\n"
            f'case ":$PATH:" in\n  *:{quoted}:*) ;;\n'
            f'  *) export PATH={quoted}:"$PATH" ;;\nesac\n'
            f"# END CLAUDE PROFILE MANAGER {root}\n")


def repair_text(module, text, root, old_roots=()):
    """Strip only well-bounded manager-owned blocks; preserve all other lines."""
    roots = [str(root), *map(str, old_roots)]
    begins = {"# BEGIN CLAUDE PROFILE MANAGER " + r for r in roots}
    ends = {"# END CLAUDE PROFILE MANAGER " + r for r in roots}
    stack, out = [], []
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if stripped in begins:
            stack.append(stripped.replace("# BEGIN ", "# END ", 1))
        elif stripped in ends:
            if not stack or stack[-1] != stripped:
                raise module.Error("Unmatched managed PATH end marker; manual shell review required")
            stack.pop()
        elif not stack:
            out.append(line)
    if stack:
        raise module.Error("Unterminated managed PATH block; refusing to discard unrelated settings")
    body = "".join(out).rstrip("\n")
    return body + ("\n\n" if body else "") + path_block(root)


def shell_plans(module, manager, old_roots):
    plans = []
    for p in shell_paths(module, manager.home):
        module.safe_abs(p)  # Dotfile symlinks are never silently replaced or followed.
        if p.exists() and not p.is_file():
            raise module.Error("Shell config is not a regular file: " + str(p))
        old = p.read_text() if p.exists() else ""
        new = repair_text(module, old, manager.root, old_roots)
        if p.name.startswith(".zsh") or p.name == ".zprofile":
            checker = shutil.which("zsh")
        else:
            checker = shutil.which("bash")
        if checker:
            result = subprocess.run([checker, "-n"], input=new, text=True, capture_output=True)
            if result.returncode:
                raise module.Error(f"Shell syntax error in {p}: {result.stderr.strip()}")
        plans.append((p, new.encode(), stat.S_IMODE(p.stat().st_mode) if p.exists() else 0o600))
    return plans


def allowed_targets(module, manager, shells):
    targets = {manager.root / p for p in PAYLOAD}
    targets.update(shells)
    for name in manager.cfg["profiles"]:
        targets.add(manager.root / "sbin" / ("claude-" + name))
        targets.add(manager.root / "Applications" / ("Claude " + name + ".app"))
    return targets


def snapshot(module, target, backup, number):
    dest = backup / "items" / str(number)
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    record = {"target": str(target), "snapshot": "items/" + str(number), "kind": "missing"}
    if target.is_symlink():
        record.update(kind="link", link=os.readlink(target))
    elif target.is_dir():
        module.copy_tree(target, dest)
        record.update(kind="dir", inventory=module.inventory(dest))
    elif target.is_file():
        shutil.copy2(target, dest)
        module.durable_tree(dest)
        record.update(kind="file", sha256=module.digest(dest))
    elif target.exists():
        raise module.Error("Unsupported update target: " + str(target))
    return record


def rollback(module, manager, journal, allowed):
    data = module.object_json(journal)
    backup = module.safe_abs(data["backup"])
    base = module.safe_abs(manager.root / "update-backups")
    if (backup.parent != base or data.get("format") != 1 or
            data.get("phase") not in ("applying", "committed")):
        raise module.Error("Unsafe/unknown update journal")
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise module.Error("Invalid update journal entries")
    for item in entries:
        target = Path(item["target"])
        if target not in allowed or module.safe_abs(target.parent) != target.parent:
            raise module.Error("Unsafe update journal target: " + str(target))
        rel = item.get("snapshot", "")
        if not re.fullmatch(r"items/[0-9]+", rel):
            raise module.Error("Unsafe update snapshot path")
        src = module.safe_abs(backup / rel)
        kind = item.get("kind")
        if kind == "file" and module.digest(src) != item["sha256"]:
            raise module.Error("Damaged update rollback file")
        if kind == "dir" and module.inventory(src) != item["inventory"]:
            raise module.Error("Damaged update rollback directory")
        if kind not in ("missing", "file", "dir", "link"):
            raise module.Error("Unknown update snapshot type")
    if data["phase"] == "committed":
        journal.unlink()
        return "Committed update finalized."
    for item in reversed(entries):
        target = Path(item["target"])
        if module.exists(target):
            quarantine = backup / "recovery-current" / uuid.uuid4().hex
            quarantine.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.move(str(target), str(quarantine))
        src = backup / item["snapshot"]
        kind = item["kind"]
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if kind == "file":
            shutil.copy2(src, target)
            module.durable_tree(target)
        elif kind == "dir":
            module.copy_tree(src, target)
        elif kind == "link":
            target.symlink_to(item["link"])
        module.fsync_dir(target.parent)
    data["phase"] = "rolled-back"
    module.atomic_json(backup / "result.json", data)
    journal.unlink()
    module.fsync_dir(manager.root)
    return "Update rolled back; newer files retained in " + str(backup / "recovery-current")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("install_dir", nargs="?", default=str(Path.home() / ".local/share/claude-profile-manager"))
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--skip-shell", action="store_true")
    parser.add_argument("--old-root", action="append", default=[],
                        help="Remove bounded managed PATH blocks from this old installation too.")
    args = parser.parse_args()
    if not args.yes:
        parser.error("Review README, then pass --yes to authorize update and shell repair.")
    module = None
    try:
        destination = Path(args.install_dir).expanduser().absolute()
        module = load_manager(SOURCE, destination)
        destination = module.safe_abs(destination)
        module.SCRIPT = destination / "claude-manager.py"
        if not (destination / "claude-manager.py").is_file():
            raise module.Error("Existing installation not found; use install.sh first")
        manager = module.Manager(destination)
        journal = destination / "update-transaction.json"
        if journal.is_symlink():
            raise module.Error("Update journal must not be a symlink")
        old_roots = [module.safe_abs(p) for p in args.old_root]
        shells = shell_paths(module, manager.home)
        with manager.lock(manager.cfg["profiles"], allow_pending=False, allow_update=True):
            manager.cold()
            allowed = allowed_targets(module, manager, shells)
            if journal.exists():
                if not args.recover:
                    raise module.Error("Interrupted update detected; run update.sh INSTALL_DIR --recover --yes")
                print(rollback(module, manager, journal, allowed))
                return 0
            if args.recover:
                print("No pending update.")
                return 0
            payload = verify_release(module, SOURCE)
            plans = [] if args.skip_shell else shell_plans(module, manager, old_roots)
            # Resolve all paths before modifying anything; never write through symlink parents.
            targets = [destination / rel for rel in PAYLOAD]
            targets += [p for p, _, _ in plans]
            for name in manager.cfg["profiles"]:
                enabled = manager.profile(name)
                if "cli" in enabled:
                    targets.append(destination / "sbin" / ("claude-" + name))
                if "gui" in enabled:
                    targets.append(destination / "Applications" / ("Claude " + name + ".app"))
            for target in targets:
                module.safe_abs(target.parent)
                if target.suffix == ".app":
                    module.safe_abs(target)
            base = module.safe_abs(destination / "update-backups")
            backup = base / (time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
            backup.mkdir(mode=0o700, parents=True)
            if manager.state.exists():
                shutil.copy2(manager.state, backup / "manager.json")
            state_before = module.digest(manager.state) if manager.state.exists() else None
            records = [snapshot(module, p, backup, i) for i, p in enumerate(dict.fromkeys(targets))]
            data = {"format": 1, "phase": "applying", "version": module.VERSION,
                    "backup": str(backup), "entries": records}
            module.atomic_json(backup / "manifest.json", data)
            module.atomic_json(journal, data)
            try:
                for rel, content in payload.items():
                    module.atomic_bytes(destination / rel, content, 0o700 if rel in EXECUTABLES else 0o600)
                for path, content, mode in plans:
                    module.atomic_bytes(path, content, mode)
                # Rebuild owned launchers with installed controller/Python paths.
                for name in manager.cfg["profiles"]:
                    manager.launchers(name, check_path=False)
                if (module.digest(manager.state) if manager.state.exists() else None) != state_before:
                    raise module.Error("Registry changed during update; data was not rewritten")
                data["phase"] = "committed"
                module.atomic_json(journal, data)
                module.atomic_json(backup / "result.json", data)
                journal.unlink()
                module.fsync_dir(destination)
            except BaseException:
                if journal.exists():
                    rollback(module, manager, journal, allowed)
                raise
        print(json.dumps({"version": module.VERSION, "install_dir": str(destination),
                          "backup": str(backup), "shell_files": [str(p) for p, _, _ in plans],
                          "profile_data": "untouched", "restart_shell": bool(plans)}, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as e:
        print("UPDATE ERROR: " + str(e), file=sys.stderr)
        return 1
    except Exception as e:
        # Includes candidate manager.Error, without importing a second incompatible class.
        print("UPDATE ERROR: " + str(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Update interrupted; use --recover --yes if journal remains.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
