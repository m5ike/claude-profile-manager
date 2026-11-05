#!/usr/bin/env python3
"""Claude Profile Manager. Python 3.9+, POSIX, GUI launch requires macOS."""
import argparse
import contextlib
import copy
import errno
import fcntl
import hashlib
import json
import os
import plistlib
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path

VERSION = "1.3.0"
SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parent
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
COMPONENTS = ("settings", "skills", "plugins", "history")
CLI_ITEMS = {
    "settings": ("settings.json", "CLAUDE.md", "rules", "agents", "commands", "output-styles"),
    "skills": ("skills", "commands"),
    "plugins": ("plugins",),
    "history": ("projects", "history.jsonl", "todos", "tasks", "session-env",
                "file-history", "plans"),
}
RESET_SESSION = {
    "remoteMcpServersConfig": [], "enabledMcpTools": {}, "bridgeSessionIds": [],
    "sessionPermissionUpdates": [], "alwaysAllowedReasons": [],
    "permissionMode": "default", "chromePermissionMode": "ask_permission",
    "bypassChosenInApp": False, "remoteControlAutoEligible": False,
}


# Other AI coding CLIs with a documented per-user state directory override.
# Sources (checked 2026-11): developers.openai.com/codex (CODEX_HOME, cli_auth_credentials_store,
# CODEX_API_KEY); geminicli.com/docs/cli/enterprise + get-started/authentication (GEMINI_CLI_HOME);
# docs.github.com/copilot/reference/copilot-cli-reference/cli-config-dir-reference + authenticate
# (COPILOT_HOME, COPILOT_CACHE_HOME, token precedence); opencode.ai/docs/config + troubleshooting
# (XDG config/data/state/cache dirs, verified with `opencode debug paths`).
TOOLS = {
    "codex": {
        "title": "OpenAI Codex CLI", "binary": "codex", "packages": ("@openai/codex",),
        "register": True,
        # Codex ignores OPENAI_API_KEY for login, but API-key env vars must never silently
        # replace the profile's ChatGPT login.
        "auth_env": ("CODEX_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL"),
    },
    "gemini": {
        "title": "Google Gemini CLI", "binary": "gemini", "packages": ("@google/gemini-cli",),
        "register": True,
        "auth_env": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
                     "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_PROJECT_ID", "GOOGLE_CLOUD_LOCATION",
                     "GOOGLE_GENAI_USE_VERTEXAI"),
    },
    "copilot": {
        "title": "GitHub Copilot CLI", "binary": "copilot", "packages": ("@github/copilot",),
        "register": True,
        # Documented precedence: these env tokens override the account stored by /login.
        "auth_env": ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"),
    },
    "opencode": {
        "title": "opencode", "binary": "opencode", "packages": ("opencode-ai",),
        "register": False,  # State is split over four XDG roots; only managed layout.
        "auth_env": ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG_CONTENT",
                     "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                     "GOOGLE_GENERATIVE_AI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY",
                     "XAI_API_KEY", "MISTRAL_API_KEY", "DEEPSEEK_API_KEY"),
    },
}

# Migration classes. "credentials" (logins, tokens, saved permissions) are copied only with
# --credentials; "ephemeral" (logs, temp, caches) is never copied; "history" also covers any
# SQLite database; everything else is "settings". Exclusion lists rather than allowlists, because
# vendors add new configuration files more often than new credential stores.
TOOL_MIGRATION = {
    "codex": {
        "credentials": ("auth.json",),
        "history": ("sessions", "archived_sessions", "history.jsonl", "memories"),
        "ephemeral": ("log", "logs", "tmp", ".tmp", "cache", ".cache"),
    },
    "gemini": {
        "credentials": (".gemini/oauth_creds.json", ".gemini/google_accounts.json",
                        ".gemini/mcp-oauth-tokens.json", ".gemini/mcp-oauth-tokens-v2.json",
                        ".gemini/.env"),
        "history": (".gemini/tmp", ".gemini/history"),
        "ephemeral": (".gemini/logs", ".gemini/cache"),
    },
    "copilot": {
        "credentials": ("config.json", "providers.json", "permissions-config.json",
                        "mcp-oauth-config", "mcp-secrets"),
        "history": ("session-state", "session-store.db", "command-history-state"),
        "ephemeral": ("logs", "ide"),
    },
    "opencode": {
        "credentials": ("data/opencode/auth.json", "data/opencode/mcp-auth.json"),
        "history": ("data", "state"),
        "ephemeral": ("data/opencode/log",),
    },
}
TOOL_COMPONENTS = ("settings", "history")


class Error(Exception):
    pass


def exists(p):
    return p.exists() or p.is_symlink()


def fail(message):
    raise Error(message)


def read_json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as e:
        raise Error(f"Cannot read JSON {p}: {e}") from e


def object_json(p, default=None):
    if not exists(p):
        return copy.deepcopy(default if default is not None else {})
    d = read_json(p)
    if not isinstance(d, dict):
        fail(f"Expected JSON object: {p}")
    return d


def atomic_bytes(p, data, mode=0o600):
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".cm-write-", dir=str(p.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), mode)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, p)
        fsync_dir(p.parent)
    finally:
        if os.path.lexists(name):
            os.unlink(name)


def atomic_json(p, value):
    atomic_bytes(p, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def fsync_dir(p):
    fd = os.open(str(p), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def digest(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_abs(p):
    p = Path(os.path.abspath(os.path.expanduser(str(p))))
    if any(ord(c) < 32 for c in str(p)):
        fail("Control characters are not allowed in managed paths")
    # Do not silently traverse symlinks in managed roots or their ancestors.
    for ancestor in [p, *p.parents]:
        if ancestor.is_symlink():
            fail(f"Symlink in managed root path: {ancestor}")
    return p


def child(root, relative):
    rel = Path(relative)
    if not relative or rel.is_absolute() or ".." in rel.parts:
        fail(f"Unsafe relative path: {relative!r}")
    p = root / rel
    for ancestor in [p.parent, *p.parent.parents]:
        if ancestor == root.parent:
            break
        if ancestor.is_symlink():
            fail(f"Refusing to traverse symlink: {ancestor}")
    return p


def inventory(root):
    """No link traversal; regular files/dirs/symlinks only, stable file digest."""
    out = {}
    if not root.is_dir() or root.is_symlink():
        fail(f"Expected real directory: {root}")
    def walk_error(e):
        raise e
    for base, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        for name in sorted(dirs + files):
            p = Path(base) / name
            rel = p.relative_to(root).as_posix()
            s = p.lstat()
            if stat.S_ISLNK(s.st_mode):
                out[rel] = {"type": "link", "target": os.readlink(p)}
            elif stat.S_ISDIR(s.st_mode):
                out[rel] = {"type": "dir"}
            elif stat.S_ISREG(s.st_mode):
                before = (s.st_size, s.st_mtime_ns, s.st_ino)
                h = digest(p)
                after = p.stat()
                if before != (after.st_size, after.st_mtime_ns, after.st_ino):
                    fail(f"File changed while hashing: {p}")
                out[rel] = {"type": "file", "sha256": h, "size": s.st_size}
            else:
                fail(f"Unsupported socket/device/FIFO: {p}")
    return out


def copy_tree(src, dst):
    if exists(dst):
        fail(f"Copy destination already exists: {dst}")
    before = inventory(src)
    shutil.copytree(src, dst, symlinks=True, copy_function=shutil.copy2)
    if inventory(src) != before or inventory(dst) != before:
        fail(f"Copy verification failed or source changed: {src}")
    durable_tree(dst)


def durable_tree(path):
    """Ensure regular file contents are flushed before publishing a staged tree."""
    if path.is_symlink():
        return
    if path.is_file():
        with path.open("rb") as f:
            os.fsync(f.fileno())
        return
    for base, dirs, files in os.walk(path, topdown=False, followlinks=False):
        for name in files:
            p = Path(base) / name
            if not p.is_symlink():
                durable_tree(p)
        fsync_dir(Path(base))


def equal(a, b):
    if a.is_symlink() or b.is_symlink():
        return a.is_symlink() and b.is_symlink() and os.readlink(a) == os.readlink(b)
    if a.is_file() and b.is_file():
        return digest(a) == digest(b)
    return False


def rewrite_value(value, mappings):
    if isinstance(value, str):
        for old, new in sorted(mappings.items(), key=lambda kv: -len(kv[0])):
            if value == old or value.startswith(old.rstrip("/") + "/"):
                return new.rstrip("/") + value[len(old.rstrip("/")):]
        return value
    if isinstance(value, list):
        return [rewrite_value(x, mappings) for x in value]
    if isinstance(value, dict):
        return {rewrite_value(k, mappings): rewrite_value(v, mappings) for k, v in value.items()}
    return value


def rewrite_tree(root, mappings):
    """Only exact/path-prefix strings, not shell scripts, opaque databases or substrings."""
    if not mappings:
        return
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(base) / d).is_symlink()]
        for name in files:
            p = Path(base) / name
            if p.is_symlink():
                raw = os.readlink(p)
                new = rewrite_value(raw, mappings)
                if new != raw:
                    p.unlink()
                    p.symlink_to(new)
            elif p.suffix == ".json":
                value = read_json(p)
                new = rewrite_value(value, mappings)
                if value != new:
                    atomic_json(p, new)
            elif p.suffix == ".jsonl":
                lines = p.read_text(encoding="utf-8").splitlines()
                values = [json.loads(line) for line in lines if line.strip()]
                updated = [rewrite_value(v, mappings) for v in values]
                if values != updated:
                    atomic_bytes(p, ("\n".join(json.dumps(v, ensure_ascii=False)
                                                for v in updated) + "\n").encode())


def overlay(src, dst, conflict):
    """Conflict-aware recursive merge; divergent transcript never silently truncated."""
    if not exists(dst):
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            dst.symlink_to(os.readlink(src))
        elif src.is_dir():
            copy_tree(src, dst)
        elif src.is_file():
            shutil.copy2(src, dst)
            if not equal(src, dst):
                fail(f"File copy verification failed: {src}")
        else:
            fail(f"Unsupported input: {src}")
        return
    if (src.is_dir() and not src.is_symlink() and
            dst.is_dir() and not dst.is_symlink()):
        for p in sorted(src.iterdir()):
            overlay(p, dst / p.name, conflict)
        return
    if equal(src, dst) or conflict == "keep":
        return
    if conflict == "error":
        fail(f"Conflict: {dst}. Use --conflict keep or replace explicitly.")
    # replace means explicit source wins; never an implicit JSON recursive merge.
    if dst.is_dir() and not dst.is_symlink():
        shutil.rmtree(dst)
    else:
        dst.unlink()
    overlay(src, dst, "error")


class Manager:
    def __init__(self, root=ROOT, home=None):
        self.root = safe_abs(root)
        self.home = safe_abs(home or Path.home())
        self.state = self.root / "manager.json"
        self.journal = self.root / "transaction.json"
        if self.state.is_symlink() or self.journal.is_symlink():
            fail("Manager state/journal must not be symlinks")
        self.cfg = object_json(self.state, {
            "version": 1, "binary": "", "gui_app": "/Applications/Claude.app",
            "profiles": {},
        })
        if self.cfg.get("version") != 1 or not isinstance(self.cfg.get("profiles"), dict):
            fail("Unknown manager.json schema")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def save(self):
        atomic_json(self.state, self.cfg)

    def name(self, name):
        if not NAME_RE.fullmatch(name) or name.startswith("gui-"):
            fail("Name must be 1-32 lowercase ASCII characters, start with a letter; "
                 "letters, digits, _ and - only; gui- prefix is reserved.")
        return name

    def profile(self, name):
        self.name(name)
        if name not in self.cfg["profiles"]:
            fail(f"Unknown profile: {name}")
        p = self.cfg["profiles"][name]
        if not isinstance(p, dict):
            fail(f"Invalid profile configuration: {name}")
        kind = p.get("kind", "both")
        if kind not in ("cli", "gui", "both"):
            fail(f"Invalid profile type: {name}")
        enabled = ("cli", "gui") if kind == "both" else (kind,)
        if any(not isinstance(p.get(k), str) for k in enabled):
            fail(f"Missing root for profile type {kind}: {name}")
        return {k: safe_abs(p[k]) for k in enabled}

    @contextlib.contextmanager
    def lock(self, names=(), shared=False, allow_pending=False, allow_update=False):
        handles = []
        try:
            # Global lock serializes mutations and the brief launcher handoff.
            lockdir = safe_abs(self.root / "locks")
            lockdir.mkdir(mode=0o700, exist_ok=True)
            for key in ["manager", *["profile-" + n for n in sorted(set(names))]]:
                f = (lockdir / (key + ".lock")).open("a+")
                handles.append(f)
                mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
                try:
                    fcntl.flock(f, mode | fcntl.LOCK_NB)
                except BlockingIOError:
                    fail(f"Profile/manager is busy: {key}")
            if self.journal.exists() and not allow_pending:
                fail("Interrupted transaction detected. Run: recover")
            if (self.root / "update-transaction.json").exists() and not allow_update and not allow_pending:
                fail("Interrupted update detected. Run update.sh INSTALL_DIR --recover --yes")
            yield handles
        finally:
            for f in reversed(handles):
                f.close()

    def processes(self):
        try:
            p = subprocess.run(["ps", "-axo", "pid=,args="], capture_output=True,
                               text=True, check=True)
        except (OSError, subprocess.SubprocessError) as e:
            raise Error(f"Cannot inspect running processes: {e}") from e
        result = []
        gui = str(Path(self.cfg["gui_app"]) / "Contents/MacOS/Claude")
        binary = self.cfg.get("binary")
        for line in p.stdout.splitlines():
            fields = line.strip().split(None, 1)
            if len(fields) != 2:
                continue
            pid, cmd = int(fields[0]), fields[1]
            if pid == os.getpid():
                continue
            # Conservative: any unwrapped Claude CLI/GUI writer blocks cold operations.
            main_gui = (cmd == gui or cmd.startswith(gui + " ") or
                        bool(re.search(r"/Contents/MacOS/Claude(?:\s|$)", cmd)))
            cli = bool(re.search(r"(?:^|/)claude(?:\s|$)", cmd))
            cli = cli or "@anthropic-ai/claude-code/cli.js" in cmd
            cli = cli or bool(binary and (cmd == binary or cmd.startswith(binary + " ")))
            if main_gui or cli:
                result.append((pid, cmd, main_gui))
        return result

    def cold(self):
        running = self.processes()
        if running:
            fail("Close all Claude GUI/CLI/editor sessions before data operations. PIDs: " +
                 ", ".join(str(p[0]) for p in running))

    def validate_roots(self, name, cli=None, gui=None):
        roots = [safe_abs(p) for p in (cli, gui) if p is not None]
        if not roots:
            fail("A profile must enable CLI, GUI, or both")
        forbidden = [self.home, self.root, self.root / "backups",
                     self.root / "exports", self.root / "locks"]
        for r in roots:
            if r in forbidden or str(r) == "/" or any(f in r.parents for f in forbidden[2:]):
                fail(f"Unsafe managed root: {r}")
            if r in self.root.parents or r in self.home.parents:
                fail(f"Managed root is an ancestor of home/installation: {r}")
        all_roots = roots[:] + self.all_tool_roots()
        for n in self.cfg["profiles"]:
            if n != name:
                all_roots.extend(self.profile(n).values())
        for i, a in enumerate(all_roots):
            for b in all_roots[i + 1:]:
                if a == b or a in b.parents or b in a.parents:
                    fail(f"Overlapping profile roots: {a}, {b}")

    def create(self, name, cli=None, gui=None, existing=False, kind="both"):
        self.name(name)
        if name in self.cfg["profiles"]:
            fail(f"Profile already exists: {name}")
        if kind not in ("cli", "gui", "both"):
            fail("Type must be cli, gui or both")
        if (kind == "cli" and gui is not None) or (kind == "gui" and cli is not None):
            fail("A disabled profile type cannot have an explicit directory")
        cli = safe_abs(cli or self.root / "data" / f"claude-{name}") if kind != "gui" else None
        gui = safe_abs(gui or self.home / "Library/Application Support" / f"Claude-{name}") if kind != "cli" else None
        self.validate_roots(name, cli, gui)
        roots = {k: p for k, p in (("cli", cli), ("gui", gui)) if p is not None}
        if not existing and any(exists(p) for p in roots.values()):
            fail("Directory exists; use register to adopt it without copying/modifying contents.")
        for p in roots.values():
            if exists(p) and not p.is_dir():
                fail(f"Not a directory: {p}")
        self.cfg["profiles"][name] = {**{k: str(v) for k, v in roots.items()},
                                      "kind": kind, "projects": []}
        self.save()
        # Config first: an interrupted mkdir can be repeated safely with mkdir -p.
        for p in roots.values():
            p.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self.cfg["profiles"][name]

    def scope_roots(self, name, scope):
        p = self.profile(name)
        if scope != "both" and scope not in p:
            fail(f"Profile {name} has no {scope.upper()} configuration")
        return {k: v for k, v in p.items() if scope == "both" or k == scope}

    def set_type(self, name, kind):
        current = self.profile(name)
        if kind not in ("cli", "gui", "both"):
            fail("Type must be cli, gui or both")
        old = copy.deepcopy(self.cfg["profiles"][name])
        disabled = dict(old.get("disabled_roots", {}))
        wanted = ("cli", "gui") if kind == "both" else (kind,)
        defaults = {"cli": self.root / "data" / f"claude-{name}",
                    "gui": self.home / "Library/Application Support" / f"Claude-{name}"}
        roots = {k: current[k] if k in current else safe_abs(disabled.get(k, defaults[k]))
                 for k in wanted}
        self.validate_roots(name, roots.get("cli"), roots.get("gui"))
        for k, p in current.items():
            if k not in wanted:
                disabled[k] = str(p)
        for k, p in roots.items():
            if k not in current and exists(p) and disabled.get(k) != str(p):
                fail(f"New root already exists; register it explicitly instead: {p}")
            if exists(p) and not p.is_dir():
                fail(f"Root is not a directory: {p}")
            disabled.pop(k, None)
        snapshot = self.backup(name, "both")
        new = {k: v for k, v in old.items() if k not in ("cli", "gui", "kind", "disabled_roots")}
        new.update({k: str(p) for k, p in roots.items()})
        new.update(kind=kind, disabled_roots=disabled)
        for p in roots.values():
            p.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.cfg["profiles"][name] = new
        try:
            self.save()
        except BaseException:
            self.cfg["profiles"][name] = old
            raise
        return {"profile": name, "kind": kind, "backup": str(snapshot),
                "disabled_roots_preserved": disabled}

    def backup(self, name, scope="both"):
        roots = self.scope_roots(name, scope)
        base = safe_abs(self.root / "backups")
        base.mkdir(mode=0o700, exist_ok=True)
        out = base / (time.strftime("%Y%m%d-%H%M%S-") + name + "-" + uuid.uuid4().hex[:8])
        out.mkdir(mode=0o700)
        manifest = {"format": 1, "profile": name, "created": time.time(),
                    "complete": False, "roots": {}, "files": {}}
        atomic_json(out / "manifest.json", manifest)
        for kind, src in roots.items():
            if not src.is_dir():
                fail(f"Missing profile directory: {src}")
            dst = out / kind
            copy_tree(src, dst)
            manifest["roots"][kind] = str(src)
            manifest["files"][kind] = inventory(dst)
        # Standard ~/.claude.json lives alongside ~/.claude, unlike custom config dirs.
        if "cli" in roots and roots["cli"] == self.home / ".claude":
            adjacent = self.home / ".claude.json"
            if exists(adjacent):
                if adjacent.is_symlink() or not adjacent.is_file():
                    fail("Adjacent ~/.claude.json must be a regular file")
                extra = out / "default-home-state"
                extra.mkdir()
                shutil.copy2(adjacent, extra / ".claude.json")
                manifest["files"]["default-home-state"] = inventory(extra)
        manifest["complete"] = True
        atomic_json(out / "manifest.json", manifest)
        self.verify(out)
        return out

    def verify(self, backup):
        backup = safe_abs(backup)
        m = object_json(backup / "manifest.json")
        if (m.get("format") != 1 or m.get("complete") is not True or
                not isinstance(m.get("files"), dict) or not m["files"] or
                not isinstance(m.get("roots"), dict)):
            fail("Invalid/incomplete backup manifest")
        if not set(m["roots"]) <= {"cli", "gui"} or not set(m["files"]) <= {
                "cli", "gui", "default-home-state"}:
            fail("Unexpected backup scope")
        if set(m["files"]) - {"default-home-state"} != set(m["roots"]):
            fail("Backup scope/manifest mismatch")
        expected = {"manifest.json", *m["files"].keys()}
        if {p.name for p in backup.iterdir()} != expected:
            fail("Unexpected/missing files in backup root")
        for kind, records in m["files"].items():
            if inventory(backup / kind) != records:
                fail(f"Backup integrity mismatch: {kind}")
        return m

    def transaction(self, replacements):
        """Stage on target filesystem; durable journal before any rename; retain old trees."""
        if self.journal.exists():
            fail("Pending transaction; recover first")
        tx = uuid.uuid4().hex
        entries = []
        for target, stage in replacements:
            target = safe_abs(target)
            remove_only = stage is None
            stage = (target.parent / (".cm-stage-" + uuid.uuid4().hex) if remove_only
                     else safe_abs(stage))
            if not remove_only:
                durable_tree(stage)
            if target.parent != stage.parent:
                fail("Transaction staging must be on target filesystem")
            old = target.parent / (".cm-old-" + tx + "-" + target.name)
            if exists(old):
                fail("Transaction old path already exists")
            entries.append({"target": str(target), "stage": str(stage), "old": str(old),
                            "existed": exists(target), "remove_only": remove_only})
        journal = {"format": 1, "id": tx, "phase": "applying", "entries": entries}
        atomic_json(self.journal, journal)
        try:
            for e in entries:
                target, stage, old = (Path(e[k]) for k in ("target", "stage", "old"))
                if e["existed"]:
                    os.replace(target, old)
                    fsync_dir(target.parent)
                if not e["remove_only"]:
                    os.replace(stage, target)
                fsync_dir(target.parent)
            journal["phase"] = "committed"
            atomic_json(self.journal, journal)
            self.finish_transaction(journal)
        except BaseException:
            # Includes Ctrl-C: rollback unless commit already became durable.
            if self.journal.exists():
                self.recover()
            raise

    def finish_transaction(self, journal):
        receipts = self.root / "receipts"
        receipts.mkdir(mode=0o700, exist_ok=True)
        atomic_json(receipts / (journal["id"] + ".json"), journal)
        self.journal.unlink()
        fsync_dir(self.root)
        # Old directories intentionally retained. No automatic destructive GC.

    def recover(self):
        if not self.journal.exists():
            return "No pending transaction."
        j = object_json(self.journal)
        if (j.get("format") != 1 or not re.fullmatch(r"[0-9a-f]{32}", j.get("id", "")) or
                j.get("phase") not in ("applying", "committed") or
                not isinstance(j.get("entries"), list)):
            fail("Unknown journal schema; manual recovery required")
        allowed = {str(p) for n in self.cfg["profiles"] for p in self.profile(n).values()}
        allowed |= {str(p) for p in self.all_tool_roots()}
        if str(self.home / ".claude") in allowed:
            allowed.add(str(self.home / ".claude.json"))
        for e in j["entries"]:
            t, s, o = (safe_abs(e[k]) for k in ("target", "stage", "old"))
            if (str(t) not in allowed or s.parent != t.parent or o.parent != t.parent or
                    not s.name.startswith(".cm-stage-") or
                    o.name != ".cm-old-" + j["id"] + "-" + t.name or
                    not isinstance(e.get("existed"), bool) or
                    not isinstance(e.get("remove_only", False), bool)):
                fail("Unsafe transaction journal; manual recovery required")
        if j["phase"] == "committed":
            self.finish_transaction(j)
            return "Committed transaction finalized; old data retained."
        for e in reversed(j["entries"]):
            t, s, o = (Path(e[k]) for k in ("target", "stage", "old"))
            if o.exists():
                if exists(t):
                    os.replace(t, t.parent / (".cm-recovered-" + uuid.uuid4().hex))
                os.replace(o, t)
                fsync_dir(t.parent)
            elif not e["existed"] and exists(t) and not exists(s):
                os.replace(t, t.parent / (".cm-recovered-" + uuid.uuid4().hex))
                fsync_dir(t.parent)
            # Stage kept for forensic inspection; no deletion of user data.
        j["phase"] = "rolled-back"
        receipts = self.root / "receipts"
        receipts.mkdir(mode=0o700, exist_ok=True)
        atomic_json(receipts / (j["id"] + ".json"), j)
        self.journal.unlink()
        fsync_dir(self.root)
        return "Rolled back. Staged/new data retained in .cm-* directories."

    def stage(self, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        p = target.parent / (".cm-stage-" + uuid.uuid4().hex)
        if target.exists():
            copy_tree(target, p)
        else:
            p.mkdir(mode=0o700)
        return p

    def restore(self, name, backup, scope):
        m = self.verify(backup)
        roots = self.scope_roots(name, scope)
        if not set(roots) <= set(m["roots"]):
            fail("Backup does not contain requested scope")
        for kind, target in roots.items():
            if m["roots"][kind] != str(target):
                fail("Exact restore requires original root paths. Use migrate/import for a different profile.")
        current = self.backup(name, scope)
        replacements = []
        for kind, target in roots.items():
            stage = target.parent / (".cm-stage-" + uuid.uuid4().hex)
            copy_tree(Path(backup) / kind, stage)
            # Restore is an exact snapshot: do not rebase opaque account databases.
            replacements.append((target, stage))
        if ("cli" in roots and roots["cli"] == self.home / ".claude" and
                "default-home-state" in m["files"]):
            target = self.home / ".claude.json"
            stage = self.home / (".cm-stage-" + uuid.uuid4().hex)
            shutil.copy2(Path(backup) / "default-home-state/.claude.json", stage)
            replacements.append((target, stage))
        elif "cli" in roots and roots["cli"] == self.home / ".claude":
            # Snapshot explicitly had no adjacent state file.
            if exists(self.home / ".claude.json"):
                replacements.append((self.home / ".claude.json", None))
        self.cold()
        self.transaction(replacements)
        return current

    def gui_index(self, root):
        base = root / "claude-code-sessions"
        if not exists(base):
            fail(f"GUI session index missing: {base}. Sign in, open Code once, then quit.")
        if base.is_symlink():
            fail("GUI session index must not be a symlink")
        candidates = [p for p in base.glob("*/*") if p.is_dir() and not p.is_symlink()]
        if len(candidates) != 1:
            fail("Ambiguous/unknown GUI account/org index; expected exactly one account/org.")
        idx = safe_abs(candidates[0])
        for f in idx.glob("local_*.json"):
            if f.is_symlink():
                fail(f"GUI metadata symlink refused: {f}")
            d = object_json(f)
            if d.get("sessionId") != f.stem:
                fail(f"GUI session ID/filename mismatch: {f}")
            if not isinstance(d.get("cwd"), str):
                fail(f"Unsupported GUI session without cwd: {f}")
        return idx

    def merge_gui_history(self, source, stage, target, conflict, mappings, with_workspaces):
        src_idx, dst_idx = self.gui_index(source), self.gui_index(stage)
        migrated = []
        warnings = []
        for f in src_idx.glob("local_*.json"):
            data = rewrite_value(object_json(f), mappings)
            cli_id = data.get("cliSessionId")
            if cli_id:
                if not isinstance(cli_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", cli_id):
                    fail("Invalid GUI cliSessionId")
                shared = safe_abs(self.home / ".claude/projects")
                transcripts = list(shared.glob("*/" + cli_id + ".jsonl"))
                if len(transcripts) != 1 or transcripts[0].is_symlink():
                    fail(f"GUI backing transcript {cli_id} is missing/ambiguous in ~/.claude/projects. "
                         "Migrate CLI history into a registered default profile first.")
            else:
                warnings.append(f"{f.stem}: no cliSessionId; backing transcript cannot be verified.")
            if exists(dst_idx / f.name):
                own = object_json(dst_idx / f.name)
                # Account-bound permissions are preserved only from target, never source.
                for key, default in RESET_SESSION.items():
                    data[key] = own.get(key, default)
            else:
                data.update(copy.deepcopy(RESET_SESSION))
            for key in ("cwd", "originCwd", "worktreePath"):
                value = data.get(key)
                if value and isinstance(value, str):
                    probe = Path(rewrite_value(value, {str(target): str(stage)}))
                    if not probe.exists():
                        fail(f"Missing GUI workspace {key}={value}; copy/map the project first.")
            if data.get("worktreeName") or data.get("worktreePath"):
                if not with_workspaces:
                    fail("Managed GUI worktree requires --workspaces and a valid v2 registry.")
            cwd = data["cwd"]
            for rel in ("scratch-workspaces", "scratch"):
                if cwd.startswith(str(source / rel) + "/"):
                    fail("Unmapped GUI scratch workspace")
            out = dst_idx / f.name
            if exists(out) and object_json(out) != data:
                if conflict == "error":
                    fail(f"GUI session conflict: {f.name}")
                if conflict == "keep":
                    continue
            atomic_json(out, data)
            migrated.append(data)
        # Preserve unrelated archive entries and recompute known cards' archive flags.
        archive = object_json(dst_idx / "archived-sessions.idx", {"v": 1, "archived": []})
        if archive.get("v", 1) != 1 or not isinstance(archive.get("archived"), list):
            fail("Unsupported GUI archive index")
        archived = set(archive["archived"])
        for f in dst_idx.glob("local_*.json"):
            d = object_json(f)
            (archived.add if d.get("isArchived") else archived.discard)(f.stem)
        archive["archived"] = sorted(archived)
        atomic_json(dst_idx / "archived-sessions.idx", archive)
        worktree_sessions = [d for d in migrated if d.get("worktreeName") or d.get("worktreePath")]
        if worktree_sessions:
            self.merge_worktrees(source, stage, mappings, worktree_sessions, dst_idx, conflict)
        return warnings

    def merge_worktrees(self, source, stage, mappings, sessions, index, conflict):
        src = rewrite_value(object_json(source / "git-worktrees.json"), mappings)
        dst = object_json(stage / "git-worktrees.json",
                          {"schemaVersion": 2, "worktrees": {}, "originUrls": {}, "originPins": {}})
        for data in (src, dst):
            if data.get("schemaVersion") != 2:
                fail("Unsupported GUI worktree registry; only schemaVersion 2 is supported.")
            for key in ("worktrees", "originUrls", "originPins"):
                if not isinstance(data.get(key, {}), dict):
                    fail("Invalid GUI worktree registry map: " + key)
                data.setdefault(key, {})
        all_sessions = [object_json(f) for f in index.glob("local_*.json")]
        used = {}
        for d in all_sessions:
            if not d.get("isArchived") and (d.get("worktreeName") or d.get("worktreePath")):
                cwd = d.get("cwd")
                if cwd in used and used[cwd] != d["sessionId"]:
                    fail("Two active GUI sessions claim the same worktree.")
                used[cwd] = d["sessionId"]
        for d in sessions:
            name, sid, cwd = d.get("worktreeName"), d["sessionId"], d["cwd"]
            entry = src["worktrees"].get(name)
            if (not isinstance(entry, dict) or entry.get("name") != name or
                    entry.get("path") != cwd or entry.get("leasedBy") not in (None, sid)):
                fail(f"No matching source worktree lease for {sid}")
            # Never rewrite .git pointers or invoke checkout, clean, reset or worktree remove.
            try:
                check = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"],
                                       text=True, capture_output=True, timeout=5, check=True)
            except (OSError, subprocess.SubprocessError) as e:
                raise Error(f"Worktree is not a valid local Git checkout: {cwd}") from e
            if Path(check.stdout.strip()).resolve() != Path(cwd).resolve():
                fail("Worktree top-level path mismatch")
            old = dst["worktrees"].get(name)
            if old is not None and old != entry:
                if conflict != "replace" or old.get("leasedBy") not in (None, sid):
                    fail("Conflicting target worktree registration; originals preserved.")
            entry = copy.deepcopy(entry)
            entry["leasedBy"] = sid
            dst["worktrees"][name] = entry
        # Carry source origin metadata only under explicit --workspaces consent.
        for key in ("originUrls", "originPins"):
            for k, value in src[key].items():
                if k in dst[key] and dst[key][k] != value:
                    fail(f"Conflicting worktree {key}: {k}")
                dst[key][k] = value
        # Do not import source orphan-GC countdowns.
        atomic_json(stage / "git-worktrees.json", dst)

    def migrate(self, src_name, dst_name, scope, components, conflict="error",
                credentials=False, dry_run=True, mappings=None, workspaces=False):
        if src_name == dst_name:
            fail("Source and target must differ")
        self.profile(dst_name)
        if self.cfg["profiles"][dst_name].get("read_only"):
            fail("Target is read-only")
        srcs, dsts = self.scope_roots(src_name, scope), self.scope_roots(dst_name, scope)
        if set(srcs) != set(dsts):
            fail("Profile types differ; select an explicitly shared --scope cli or gui")
        if not components or not set(components) <= set(COMPONENTS):
            fail("Choose components: " + ", ".join(COMPONENTS))
        mappings = dict(mappings or {})
        source_all, target_all = self.profile(src_name), self.profile(dst_name)
        mappings.update({str(source_all[k]): str(target_all[k])
                         for k in set(source_all) & set(target_all)})
        report = {"source": src_name, "target": dst_name, "scope": scope,
                  "components": components, "conflict": conflict,
                  "credentials": credentials, "dry_run": dry_run, "warnings": []}
        if "plugins" in components and "settings" not in components:
            report["warnings"].append("Plugin enablement in settings.json is not selected; "
                                      "include settings to migrate enabledPlugins too.")
        if credentials:
            report["warnings"].append("CLI credential file copied; macOS Keychain is NOT exported.")
            if "gui" in dsts:
                fail("GUI cross-profile credential migration is refused. Sign in separately; "
                     "exact GUI snapshots can be restored only to their original paths.")
        if "gui" in dsts and ("skills" in components or "plugins" in components):
            report["warnings"].append("GUI Customize skills/plugins are account-bound; "
                                      "only CLI-local skills/plugins migrate with scope cli/both.")
        stages = []
        extra_stages = []
        original_src = {k: inventory(p) for k, p in srcs.items()}
        original_dst = {k: inventory(p) for k, p in dsts.items()}
        try:
            for kind, dst in dsts.items():
                stage = self.stage(dst)
                stages.append((dst, stage))
                src = srcs[kind]
                if kind == "cli":
                    selected = []
                    for component in components:
                        selected.extend(CLI_ITEMS[component])
                    if credentials:
                        selected.append(".credentials.json")
                    # NEVER copy .claude.json across accounts automatically.
                    for rel in selected:
                        path = child(src, rel)
                        if exists(path):
                            overlay(path, child(stage, rel), conflict)
                    if "settings" in components:
                        # Portable user MCP definitions, never oauthAccount/trust/onboarding.
                        state_file = Path(self.cfg["profiles"][src_name].get(
                            "state_file", self.home / ".claude.json" if src == self.home / ".claude"
                            else src / ".claude.json"))
                        state_src = object_json(state_file)
                        if "mcpServers" in state_src:
                            default_target = dst == self.home / ".claude"
                            target_state_file = (self.home / ".claude.json" if default_target
                                                 else stage / ".claude.json")
                            state_target = object_json(target_state_file)
                            new_mcp = rewrite_value(state_src["mcpServers"], mappings)
                            if ("mcpServers" in state_target and
                                    state_target["mcpServers"] != new_mcp and conflict == "error"):
                                fail("CLI personal MCP settings conflict")
                            if "mcpServers" not in state_target or conflict != "keep":
                                state_target["mcpServers"] = new_mcp
                                if default_target:
                                    file_stage = self.home / (".cm-stage-" + uuid.uuid4().hex)
                                    atomic_json(file_stage, state_target)
                                    extra_stages.append((target_state_file, file_stage))
                                else:
                                    atomic_json(stage / ".claude.json", state_target)
                    rewrite_tree(stage, mappings)
                    self.rekey_projects(stage, mappings)
                else:
                    if "settings" in components:
                        a = object_json(src / "claude_desktop_config.json")
                        b = object_json(stage / "claude_desktop_config.json")
                        # Explicit portable keys only. Epitaxy preferences/account state not copied.
                        for key in ("mcpServers",):
                            if key in a:
                                if key in b and b[key] != a[key] and conflict == "error":
                                    fail(f"GUI settings conflict: {key}")
                                if key not in b or conflict != "keep":
                                    b[key] = rewrite_value(a[key], mappings)
                        atomic_json(stage / "claude_desktop_config.json", b)
                    if "history" in components:
                        if ("cli" not in source_all or "cli" not in target_all or
                                source_all["cli"] != target_all["cli"]):
                            report["warnings"].append(
                                "GUI uses shared ~/.claude/projects on some versions; "
                                "GUI index migration alone does not relocate that backing store. "
                                "Verify resume on installed Desktop; CLI-to-GUI synthesis unsupported.")
                        if workspaces:
                            for rel in ("scratch-workspaces", "scratch"):
                                if exists(src / rel):
                                    overlay(src / rel, stage / rel, conflict)
                        report["warnings"].extend(
                            self.merge_gui_history(src, stage, dst, conflict, mappings, workspaces))
            for kind, src in srcs.items():
                if inventory(src) != original_src[kind]:
                    fail("Source changed during migration; aborting.")
            for kind, dst in dsts.items():
                if inventory(dst) != original_dst[kind]:
                    fail("Target changed during migration; aborting.")
            if dry_run:
                report["changes"] = {
                    k: sum(1 for p in set(original_dst[k]) | set(inventory_cache)
                           if original_dst[k].get(p) != inventory_cache.get(p))
                    for k, (_, stage) in zip(dsts, stages)
                    for inventory_cache in [inventory(stage)]
                }
                return report
            # Backup immediately before committing; new target data remains recoverable too.
            report["backup"] = str(self.backup(dst_name, scope))
            self.cold()
            for kind, src in srcs.items():
                if inventory(src) != original_src[kind]:
                    fail("Source changed before commit; originals preserved.")
            for kind, dst in dsts.items():
                if inventory(dst) != original_dst[kind]:
                    fail("Target changed before commit; originals preserved.")
            self.transaction(stages + extra_stages)
            return report
        finally:
            for _, stage in stages:
                if exists(stage) and not self.journal.exists():
                    shutil.rmtree(stage)
            for _, stage in extra_stages:
                if exists(stage) and not self.journal.exists():
                    stage.unlink()

    def rekey_projects(self, stage, mappings):
        projects = stage / "projects"
        if not projects.is_dir() or projects.is_symlink():
            return
        for old, new in mappings.items():
            encode = lambda p: re.sub(r"[^A-Za-z0-9]", "-", p)
            a, b = projects / encode(old), projects / encode(new)
            if a == b or not exists(a):
                continue
            if exists(b):
                overlay(a, b, "error")
                shutil.rmtree(a)
            else:
                a.rename(b)

    def migrate_backup(self, backup, target, scope, components, conflict="error",
                       dry_run=True, mappings=None, workspaces=False):
        manifest = self.verify(backup)
        if not set(self.scope_roots(target, scope)) <= set(manifest["roots"]):
            fail("Backup does not contain requested migration scope")
        temporary = "backup-source-" + uuid.uuid4().hex[:8]
        self.cfg["profiles"][temporary] = {
            **{k: str(Path(backup) / k) for k in self.scope_roots(target, scope)},
            "kind": "both" if len(self.scope_roots(target, scope)) == 2 else
                    next(iter(self.scope_roots(target, scope))), "read_only": True,
        }
        if "default-home-state" in manifest["files"]:
            self.cfg["profiles"][temporary]["state_file"] = str(
                Path(backup) / "default-home-state/.claude.json")
        mappings = dict(mappings or {})
        for kind in self.scope_roots(target, scope):
            mappings[manifest["roots"][kind]] = str(self.profile(target)[kind])
        try:
            return self.migrate(temporary, target, scope, components, conflict,
                                False, dry_run, mappings, workspaces)
        finally:
            del self.cfg["profiles"][temporary]

    def find_binary(self):
        value = self.cfg.get("binary") or shutil.which("claude")
        if not value:
            fail("Claude CLI not found. Configure: set-binary /absolute/path/to/claude")
        p = Path(value).expanduser()
        if not p.is_absolute() or not p.is_file() or not os.access(p, os.X_OK):
            fail(f"Not an executable absolute Claude path: {p}")
        if p.resolve() == SCRIPT or p.resolve().name == "claude-manager.py":
            fail("Recursive wrapper detected; set the REAL Claude executable.")
        return p

    def launch_cli(self, name, args):
        paths = self.scope_roots(name, "cli")
        if self.cfg["profiles"][name].get("read_only"):
            fail("Cannot launch a read-only source profile")
        binary = self.find_binary()
        with self.lock([name], shared=True) as handles:
            # Keep only per-profile shared lock across exec, release manager lock.
            profile_lock = handles[-1]
            os.set_inheritable(profile_lock.fileno(), True)
            handles[0].close()
            env = dict(os.environ, CLAUDE_CONFIG_DIR=str(paths["cli"]))
            # Inherited API credentials otherwise silently override the selected account.
            allowed = self.cfg["profiles"][name].get("inherit_auth_env", False)
            if not allowed:
                for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
                            "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK",
                            "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
                    env.pop(key, None)
            try:
                # No pipes: stdin/stdout/stderr, TTY, signals and exit status stay native.
                os.execve(str(binary), [str(binary), *args], env)
            except OSError as e:
                print(f"Claude launch failed ({name}): {e}", file=sys.stderr)
                return 127 if e.errno == errno.ENOENT else 126

    def launch_gui(self, name):
        if sys.platform != "darwin":
            fail("GUI launch is supported only on macOS.")
        paths = self.scope_roots(name, "gui")
        if self.cfg["profiles"][name].get("read_only"):
            fail("Cannot launch a read-only source profile")
        with self.lock([name]):
            running = [p for p in self.processes() if p[2]]
            marker = "--user-data-dir=" + str(paths["gui"])
            for pid, cmd, gui in running:
                if gui and (marker in cmd and
                            (cmd.endswith(marker) or marker + " --" in cmd)):
                    print(f"Claude {name} is already running (PID {pid}).")
                    return 0
            if running:
                fail("Another Claude Desktop process is active. Quit it before GUI profile switching; "
                     "this also avoids routing login callbacks to the wrong instance.")
            app = Path(self.cfg["gui_app"])
            if not (app / "Contents/MacOS/Claude").is_file():
                fail(f"Claude.app not found: {app}")
            command = ["/usr/bin/open", "-n", "-a", str(app), "--args", marker]
            env = dict(os.environ)
            if "cli" in self.profile(name):
                env["CLAUDE_CONFIG_DIR"] = str(self.profile(name)["cli"])
            else:
                env.pop("CLAUDE_CONFIG_DIR", None)
            subprocess.run(command, env=env, check=True)
            # open returns before Electron is ready; wait to close duplicate-launch race.
            for _ in range(80):
                for pid, cmd, gui in self.processes():
                    if gui and marker in cmd:
                        print(f"Started Claude {name} (PID {pid}).")
                        return 0
                time.sleep(0.1)
            fail("open returned, but the profile process was not confirmed within 8 seconds. "
                 "Do not launch again blindly; inspect Claude/processes first.")

    def launchers(self, name, check_path=True):
        enabled = self.profile(name)
        path_status = (self.path_setup() if check_path and "cli" in enabled else
                       {"not_required": True} if "cli" not in enabled else {"checked_by_updater": True})
        result = {"path_status": path_status}
        if "cli" in enabled:
            result["cli"] = self.cli_launcher(name)
        if "gui" in enabled:
            result["gui"] = self.gui_launcher(name)
        return result

    def cli_launcher(self, name):
        bindir = safe_abs(self.root / "sbin")
        bindir.mkdir(mode=0o700, exist_ok=True)
        link = bindir / f"claude-{name}"
        if exists(link):
            if not link.is_symlink() or link.resolve() != SCRIPT:
                fail(f"Refusing to overwrite launcher: {link}")
        else:
            link.symlink_to(os.path.relpath(SCRIPT, bindir))
        return str(link)

    def gui_launcher(self, name):
        apps = safe_abs(self.root / "Applications")
        apps.mkdir(mode=0o700, exist_ok=True)
        app = safe_abs(apps / f"Claude {name}.app")
        if exists(app):
            marker = app / "Contents/cm-owner.json"
            if not marker.is_file() or object_json(marker) != {"root": str(self.root), "name": name}:
                fail(f"Refusing to overwrite unowned app: {app}")
        contents = safe_abs(app / "Contents")
        safe_abs(contents / "MacOS").mkdir(mode=0o700, parents=True, exist_ok=True)
        python = str(Path(sys.executable).resolve())
        launcher = "#!/bin/sh\nexport CM_GUI_LAUNCHER=1\nexec " + shlex.quote(python)
        launcher += " " + shlex.quote(str(SCRIPT))
        launcher += " gui " + shlex.quote(name) + "\n"
        atomic_bytes(contents / "MacOS/launcher", launcher.encode(), 0o700)
        info = {"CFBundleName": f"Claude {name}", "CFBundleDisplayName": f"Claude {name}",
                "CFBundleIdentifier": "local.claudeprofiles.p" + hashlib.sha256(name.encode()).hexdigest()[:16],
                "CFBundleExecutable": "launcher", "CFBundlePackageType": "APPL",
                "CFBundleVersion": VERSION, "CFBundleShortVersionString": VERSION,
                "LSUIElement": True}
        atomic_bytes(contents / "Info.plist", plistlib.dumps(info))
        atomic_json(contents / "cm-owner.json", {"root": str(self.root), "name": name})
        return str(app)

    def path_setup(self, write=False):
        bindir = str(self.root / "sbin")
        shellrc = self.home / (".zshrc" if "zsh" in os.environ.get("SHELL", "/bin/zsh")
                               else ".profile")
        begin = "# BEGIN CLAUDE PROFILE MANAGER " + str(self.root)
        end = "# END CLAUDE PROFILE MANAGER " + str(self.root)
        if shellrc.is_symlink():
            fail("Shell rc is a symlink; edit it manually.")
        old = shellrc.read_text() if shellrc.exists() else ""
        present = begin in old and end in old
        if (begin in old) != (end in old):
            fail("Incomplete managed PATH block; inspect shell startup file manually.")
        on_path = bindir in os.environ.get("PATH", "").split(os.pathsep)
        report = {"file": str(shellrc), "managed_block": present, "in_current_PATH": on_path}
        if write and not present:
            backup = safe_abs(self.root / "shell-backups")
            backup.mkdir(mode=0o700, exist_ok=True)
            if shellrc.exists():
                shutil.copy2(shellrc, backup / (shellrc.name + "." + uuid.uuid4().hex))
            quoted = shlex.quote(bindir)
            block = (f"\n{begin}\ncase \":$PATH:\" in\n  *:{quoted}:*) ;;\n"
                     f"  *) export PATH={quoted}:\"$PATH\" ;;\nesac\n{end}\n")
            atomic_bytes(shellrc, (old + block).encode(),
                         stat.S_IMODE(shellrc.stat().st_mode) if shellrc.exists() else 0o600)
            report["managed_block"] = True
            report["restart_shell"] = True
        return report

    def export(self, backup, output):
        manifest = copy.deepcopy(self.verify(backup))
        return self.portable_archive(backup, output, manifest, manifest["files"], manifest["roots"])

    def portable_archive(self, backup, output, manifest, files_by_kind, roots_by_kind):
        """Write manifest + payload dirs as .tar.gz; absolute in-tree links become relative."""
        portable_links = {}
        for kind, files in files_by_kind.items():
            for rel, info in files.items():
                if info["type"] != "link":
                    continue
                target = info["target"]
                if os.path.isabs(target):
                    original = roots_by_kind.get(kind)
                    if not original:
                        fail("Unportable absolute symlink in auxiliary state")
                    try:
                        within = Path(os.path.normpath(target)).relative_to(original)
                    except ValueError:
                        fail(f"External plugin/project link cannot be exported safely: {kind}/{rel}")
                    dest = Path(backup) / kind / within
                else:
                    dest = Path(os.path.normpath(str(Path(backup) / kind / rel / ".." / target)))
                payload = Path(backup) / kind
                if payload not in dest.parents and payload != dest:
                    fail(f"External relative symlink cannot be exported safely: {kind}/{rel}")
                portable = os.path.relpath(dest, (Path(backup) / kind / rel).parent)
                portable_links[f"{kind}/{rel}"] = portable
                info["target"] = portable
        output = safe_abs(output)
        if exists(output) or exists(Path(str(output) + ".sha256")):
            fail("Export destination already exists")
        if Path(backup) in output.parents:
            fail("Do not write an export inside its verified backup")
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".cm-export-", dir=output.parent)
        os.close(fd)
        try:
            with tarfile.open(tmp, "w:gz", dereference=False) as tar:
                payload = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()
                member = tarfile.TarInfo("manifest.json")
                member.size, member.mode = len(payload), 0o600
                import io
                tar.addfile(member, io.BytesIO(payload))
                def filter_member(member):
                    if member.name in portable_links:
                        member.linkname = portable_links[member.name]
                    return member
                for p in sorted(Path(backup).iterdir()):
                    if p.name != "manifest.json":
                        tar.add(p, arcname=p.name, recursive=True, filter=filter_member)
            os.chmod(tmp, 0o600)
            os.replace(tmp, output)
            atomic_bytes(Path(str(output) + ".sha256"),
                         (digest(output) + "  " + output.name + "\n").encode())
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return output

    def import_archive(self, archive, expected_sha256, max_bytes=20 * 1024**3):
        return self.extract_archive(archive, expected_sha256, "backups",
                                    {"manifest.json", "cli", "gui", "default-home-state"},
                                    self.verify, max_bytes)

    def extract_archive(self, archive, expected_sha256, folder, tops, verify, max_bytes=20 * 1024**3):
        archive = safe_abs(archive)
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            fail("Provide trusted --sha256 (64 lowercase hex characters).")
        if digest(archive) != expected_sha256:
            fail("Archive SHA-256 mismatch")
        base = safe_abs(self.root / folder)
        base.mkdir(mode=0o700, exist_ok=True)
        dst = Path(tempfile.mkdtemp(prefix="import-", dir=base))
        total = 0
        seen = set()
        try:
            with tarfile.open(archive, "r:gz") as tar:
                for member in tar:
                    rel = Path(member.name)
                    if (rel.is_absolute() or ".." in rel.parts or not rel.parts or
                            member.name in seen or rel.parts[0] not in tops):
                        fail(f"Unsafe/duplicate archive path: {member.name}")
                    seen.add(member.name)
                    if len(seen) > 200000:
                        fail("Archive contains too many entries")
                    target = child(dst, member.name)
                    if member.isdir():
                        target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    elif member.isfile():
                        total += member.size
                        if member.size < 0 or total > max_bytes or len(seen) > 200000:
                            fail("Archive exceeds extraction limits")
                        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                        if exists(target):
                            fail("Archive file/directory collision")
                        data = tar.extractfile(member)
                        if data is None:
                            fail("Unreadable archive member")
                        with data, target.open("xb") as out:
                            shutil.copyfileobj(data, out)
                        os.chmod(target, (member.mode & 0o700) or 0o600)
                    elif member.issym():
                        # Relative links confined to their own payload tree only.
                        link = Path(member.linkname)
                        resolved = (target.parent / link).resolve()
                        payload = dst / rel.parts[0]
                        if (link.is_absolute() or
                                (payload not in resolved.parents and payload != resolved) or
                                exists(target)):
                            fail(f"External/unsafe archive symlink: {member.name}")
                        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                        target.symlink_to(member.linkname)
                    else:
                        fail("Hardlinks, devices and FIFOs are refused in imports")
            verify(dst)
            return dst
        except BaseException:
            shutil.rmtree(dst)
            raise

    def project_copy(self, name, source, dest, dry_run=True):
        self.profile(name)
        src, dst = safe_abs(source), safe_abs(dest)
        if not src.is_dir() or exists(dst):
            fail("Source must exist and destination must not exist")
        if src in dst.parents or dst in src.parents:
            fail("Nested project copy refused")
        if (src / ".git").is_file():
            fail("Linked Git worktree/submodule cannot be copied as standalone repo. "
                 "Use a normal checkout; this command never edits Git lease/registry files.")
        if (src / ".git/worktrees").is_dir() and any((src / ".git/worktrees").iterdir()):
            fail("Repository owns linked worktrees; blind copying their registrations is unsafe.")
        if (src / ".git/objects/info/alternates").exists():
            fail("Git repository uses external object alternates; make a self-contained clone first.")
        if (src / ".git").is_dir():
            git_config = subprocess.run(["git", "-C", str(src), "config", "--local", "--get",
                                         "core.worktree"], capture_output=True, text=True)
            if git_config.returncode not in (0, 1):
                fail("Cannot inspect repository core.worktree")
            if git_config.stdout.strip():
                fail("Repository has explicit core.worktree; manual conversion is required.")
        inv = inventory(src)
        for rel, info in inv.items():
            if rel.endswith("/.git") and info["type"] == "file":
                fail("Nested linked submodule/worktree .git pointer found: " + rel)
            if info["type"] == "link":
                resolved = (src / rel).resolve()
                if resolved != src and src not in resolved.parents:
                    fail(f"External project symlink: {rel}. Copy its target separately.")
            if rel.endswith(".lock") and (rel.startswith(".git/") or rel == ".git/index.lock"):
                fail("Git lock found; stop writers before copying")
        report = {"source": str(src), "target": str(dst), "files": len(inv), "dry_run": dry_run}
        if dry_run:
            return report
        dst.parent.mkdir(parents=True, exist_ok=True)
        stage = dst.parent / (".cm-project-" + uuid.uuid4().hex)
        try:
            copy_tree(src, stage)
            # Absolute internal links must not continue pointing to the original project.
            for rel, info in inv.items():
                if info["type"] == "link" and os.path.isabs(info["target"]):
                    target = (src / rel).resolve().relative_to(src)
                    link = stage / rel
                    link.unlink()
                    link.symlink_to(os.path.relpath(stage / target, link.parent))
            durable_tree(stage)
            # Atomic no-overwrite reservation before replacing our own empty placeholder.
            dst.mkdir()
            try:
                os.replace(stage, dst)
            except BaseException:
                dst.rmdir()
                raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        items = self.cfg["profiles"][name].setdefault("projects", [])
        if str(dst) not in items:
            items.append(str(dst))
            self.save()
        return report

    def edit_settings(self, name, scope):
        if scope not in ("cli", "gui"):
            fail("Edit one settings file at a time: cli or gui")
        root = self.scope_roots(name, scope)[scope]
        before = inventory(root)
        backup = self.backup(name, scope)
        stage = self.stage(root)
        filename = "settings.json" if scope == "cli" else "claude_desktop_config.json"
        try:
            path = stage / filename
            if path.is_symlink():
                fail("Settings file is a symlink; refusing to edit its target.")
            if not path.exists():
                atomic_json(path, {})
            editor = shlex.split(os.environ.get("EDITOR", "nano"))
            if not editor:
                fail("EDITOR is empty")
            subprocess.run([*editor, str(path)], check=True)
            object_json(path)
            self.cold()
            if inventory(root) != before:
                fail("Original settings/profile changed while editor was open")
            self.transaction([(root, stage)])
            return {"backup": str(backup), "settings": str(root / filename)}
        finally:
            if stage.exists() and not self.journal.exists():
                shutil.rmtree(stage)

    # ----- Other AI coding CLIs (Codex, Gemini, Copilot, opencode) -----

    def tool_spec(self, tool):
        if tool not in TOOLS:
            fail(f"Unknown tool: {tool}. Supported: {', '.join(TOOLS)}")
        return TOOLS[tool]

    def tool_registry(self, tool=None):
        reg = self.cfg.get("tools", {})
        if not isinstance(reg, dict):
            fail("Invalid tools registry in manager.json")
        if tool is None:
            return reg
        self.tool_spec(tool)
        entry = reg.get(tool, {})
        if not isinstance(entry, dict) or not isinstance(entry.get("profiles", {}), dict):
            fail(f"Invalid registry for tool {tool}")
        return entry

    def tool_profile(self, tool, name):
        self.name(name)
        p = self.tool_registry(tool).get("profiles", {}).get(name)
        if not isinstance(p, dict) or not isinstance(p.get("root"), str):
            fail(f"Unknown {tool} profile: {name}")
        return p

    def tool_root(self, tool, name):
        return safe_abs(self.tool_profile(tool, name)["root"])

    def tool_cache(self, tool, name):
        # Caches stay outside the profile root, so backups do not carry disposable data.
        return safe_abs(self.root / "cache" / f"{tool}-{name}")

    def all_tool_roots(self, skip=None):
        out = []
        for tool in TOOLS:
            for n, p in self.tool_registry(tool).get("profiles", {}).items():
                if (tool, n) != skip and isinstance(p, dict) and isinstance(p.get("root"), str):
                    out.append(safe_abs(p["root"]))
        return out

    def validate_tool_root(self, tool, name, root):
        forbidden = [self.home, self.root, self.root / "backups", self.root / "tool-backups",
                     self.root / "exports", self.root / "locks", self.root / "cache"]
        if root in forbidden or str(root) == "/" or any(f in root.parents for f in forbidden[2:]):
            fail(f"Unsafe managed root: {root}")
        if root in self.root.parents or root in self.home.parents:
            fail(f"Managed root is an ancestor of home/installation: {root}")
        others = self.all_tool_roots(skip=(tool, name))
        for n in self.cfg["profiles"]:
            others.extend(self.profile(n).values())
        for o in others:
            if o == root or o in root.parents or root in o.parents:
                fail(f"Overlapping profile roots: {root}, {o}")

    def tool_env(self, tool, name):
        """Environment overrides that point the tool at this profile only."""
        root = self.tool_root(tool, name)
        if tool == "codex":
            return {"CODEX_HOME": str(root)}
        if tool == "gemini":
            # Gemini CLI creates/uses GEMINI_CLI_HOME/.gemini.
            return {"GEMINI_CLI_HOME": str(root)}
        if tool == "copilot":
            return {"COPILOT_HOME": str(root),
                    "COPILOT_CACHE_HOME": str(self.tool_cache(tool, name))}
        return {"XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CACHE_HOME": str(self.tool_cache(tool, name))}

    def tool_create(self, tool, name, directory=None, existing=False):
        spec = self.tool_spec(tool)
        self.name(name)
        if name in self.tool_registry(tool).get("profiles", {}):
            fail(f"{tool} profile already exists: {name}")
        if existing:
            if not spec["register"]:
                fail(f"{spec['title']} keeps state in several XDG roots; create a managed profile instead.")
            if not directory:
                fail("Registering requires --dir with the existing state directory")
        root = safe_abs(directory or self.root / "tools" / tool / name)
        self.validate_tool_root(tool, name, root)
        if existing:
            if not root.is_dir():
                fail(f"Not an existing directory: {root}")
            if tool == "gemini" and not (root / ".gemini").is_dir():
                fail("GEMINI_CLI_HOME must contain a .gemini directory; ~ itself cannot be registered.")
        elif exists(root):
            fail("Directory exists; use tool-register to adopt it without modifying contents.")
        tools = self.cfg.setdefault("tools", {})
        entry = tools.setdefault(tool, {"binary": "", "profiles": {}})
        entry.setdefault("profiles", {})[name] = {"root": str(root), "inherit_auth_env": False,
                                                  "registered": bool(existing)}
        self.save()
        if not existing:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if tool == "codex":
                # Keep the ChatGPT login in this profile instead of the shared OS keyring.
                atomic_bytes(root / "config.toml",
                             b"# Created by Claude Profile Manager: per-profile file login.\n"
                             b'cli_auth_credentials_store = "file"\n')
            elif tool == "gemini":
                (root / ".gemini").mkdir(mode=0o700, exist_ok=True)
            elif tool == "opencode":
                for sub in ("config", "data", "state"):
                    (root / sub).mkdir(mode=0o700, exist_ok=True)
        return {"tool": tool, "profile": name, **entry["profiles"][name]}

    def tool_unregister(self, tool, name):
        root = self.tool_root(tool, name)
        del self.cfg["tools"][tool]["profiles"][name]
        self.save()
        return {"tool": tool, "profile": name, "data_retained": str(root)}

    def find_tool_binary(self, tool):
        spec = self.tool_spec(tool)
        value = self.tool_registry(tool).get("binary") or shutil.which(spec["binary"])
        if not value:
            fail(f"{spec['title']} not found. Configure: tool-set-binary {tool} /absolute/path")
        p = Path(value).expanduser()
        if not p.is_absolute() or not p.is_file() or not os.access(p, os.X_OK):
            fail(f"Not an executable absolute {tool} path: {p}")
        if p.resolve() == SCRIPT or p.resolve().name == "claude-manager.py":
            fail(f"Recursive wrapper detected; set the REAL {tool} executable.")
        return p

    def tool_set_binary(self, tool, path):
        entry = self.cfg.setdefault("tools", {}).setdefault(tool, {"binary": "", "profiles": {}})
        old = entry.get("binary", "")
        entry["binary"] = str(Path(path).expanduser().absolute())
        try:
            self.find_tool_binary(tool)
        except BaseException:
            entry["binary"] = old
            raise
        self.save()
        return {"tool": tool, "binary": entry["binary"]}

    def tool_processes(self, tool):
        spec = self.tool_spec(tool)
        try:
            p = subprocess.run(["ps", "-axo", "pid=,args="], capture_output=True,
                               text=True, check=True)
        except (OSError, subprocess.SubprocessError) as e:
            raise Error(f"Cannot inspect running processes: {e}") from e
        binary = self.tool_registry(tool).get("binary")
        pattern = re.compile(r"(?:^|/)" + re.escape(spec["binary"]) + r"(?:\s|$)")
        result = []
        for line in p.stdout.splitlines():
            fields = line.strip().split(None, 1)
            if len(fields) != 2 or int(fields[0]) == os.getpid():
                continue
            cmd = fields[1]
            if (pattern.search(cmd) or any(pkg in cmd for pkg in spec["packages"]) or
                    (binary and (cmd == binary or cmd.startswith(binary + " ")))):
                result.append((int(fields[0]), cmd))
        return result

    def tool_cold(self, tool):
        running = self.tool_processes(tool)
        if running:
            fail(f"Close all {self.tool_spec(tool)['title']} sessions before data operations. PIDs: " +
                 ", ".join(str(p[0]) for p in running))

    def tool_lock_name(self, tool, name):
        return f"{tool}.{name}"  # Dot cannot occur in Claude profile names: no lock collisions.

    def launch_tool(self, tool, name, args):
        binary = self.find_tool_binary(tool)
        profile = self.tool_profile(tool, name)
        root = self.tool_root(tool, name)
        if not root.is_dir():
            fail(f"Missing profile directory: {root}")
        with self.lock([self.tool_lock_name(tool, name)], shared=True) as handles:
            profile_lock = handles[-1]
            os.set_inheritable(profile_lock.fileno(), True)
            handles[0].close()
            env = dict(os.environ)
            if not profile.get("inherit_auth_env", False):
                for key in self.tool_spec(tool)["auth_env"]:
                    env.pop(key, None)
            env.update(self.tool_env(tool, name))
            for key in ("XDG_CACHE_HOME", "COPILOT_CACHE_HOME"):
                if key in env and env[key].startswith(str(self.root / "cache")):
                    Path(env[key]).mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                os.execve(str(binary), [str(binary), *args], env)
            except OSError as e:
                print(f"{tool} launch failed ({name}): {e}", file=sys.stderr)
                return 127 if e.errno == errno.ENOENT else 126

    def tool_launcher(self, tool, name):
        self.tool_profile(tool, name)
        bindir = safe_abs(self.root / "sbin")
        bindir.mkdir(mode=0o700, exist_ok=True)
        link = bindir / f"{tool}-{name}"
        if exists(link):
            if not link.is_symlink() or link.resolve() != SCRIPT:
                fail(f"Refusing to overwrite launcher: {link}")
        else:
            link.symlink_to(os.path.relpath(SCRIPT, bindir))
        return {"launcher": str(link), "path_status": self.path_setup()}

    def tool_backup(self, tool, name):
        root = self.tool_root(tool, name)
        if not root.is_dir():
            fail(f"Missing profile directory: {root}")
        base = safe_abs(self.root / "tool-backups")
        base.mkdir(mode=0o700, exist_ok=True)
        out = base / (time.strftime("%Y%m%d-%H%M%S-") + f"{tool}-{name}-" + uuid.uuid4().hex[:8])
        out.mkdir(mode=0o700)
        manifest = {"format": "tool-1", "tool": tool, "profile": name, "root": str(root),
                    "created": time.time(), "complete": False, "files": {}}
        atomic_json(out / "manifest.json", manifest)
        copy_tree(root, out / "data")
        manifest["files"] = inventory(out / "data")
        manifest["complete"] = True
        atomic_json(out / "manifest.json", manifest)
        self.tool_verify(out)
        return out

    def tool_verify(self, backup):
        backup = safe_abs(backup)
        m = object_json(backup / "manifest.json")
        if (m.get("format") != "tool-1" or m.get("complete") is not True or
                m.get("tool") not in TOOLS or not isinstance(m.get("files"), dict) or
                not isinstance(m.get("root"), str)):
            fail("Invalid/incomplete tool backup manifest")
        if {p.name for p in backup.iterdir()} != {"manifest.json", "data"}:
            fail("Unexpected/missing files in backup root")
        if inventory(backup / "data") != m["files"]:
            fail("Backup integrity mismatch")
        return m

    def tool_restore(self, tool, name, backup):
        m = self.tool_verify(backup)
        root = self.tool_root(tool, name)
        if m["tool"] != tool or m["root"] != str(root):
            fail("Exact restore requires the same tool and original root path.")
        current = self.tool_backup(tool, name)
        stage = root.parent / (".cm-stage-" + uuid.uuid4().hex)
        copy_tree(Path(backup) / "data", stage)
        self.tool_cold(tool)
        self.transaction([(root, stage)])
        return current

    def tool_classify(self, tool, rel):
        rules = TOOL_MIGRATION[tool]
        def under(prefixes):
            return any(rel == p or rel.startswith(p + "/") for p in prefixes)
        if under(rules["credentials"]):
            return "credentials"
        if under(rules["ephemeral"]):
            return "ephemeral"
        if under(rules["history"]) or re.search(r"\.(sqlite3?|db)(-wal|-shm|-journal)?$", rel):
            return "history"
        return "settings"

    def tool_plan(self, tool, src, components, credentials):
        """Files and symlinks (never followed) to copy, with their migration class."""
        plan = {}
        for base, dirs, files in os.walk(src, followlinks=False):
            b = Path(base)
            entries = files + [d for d in dirs if (b / d).is_symlink()]
            dirs[:] = sorted(d for d in dirs if not (b / d).is_symlink())
            for n in entries:
                p = b / n
                if not (p.is_symlink() or p.is_file()):
                    fail(f"Unsupported file type in profile: {p}")
                rel = p.relative_to(src).as_posix()
                kind = self.tool_classify(tool, rel)
                if kind in components or (kind == "credentials" and credentials):
                    plan[rel] = kind
        return dict(sorted(plan.items()))

    def tool_migrate(self, tool, source, target, components, conflict="error",
                     credentials=False, dry_run=True, from_backup=False):
        self.tool_spec(tool)
        components = [c for c in components if c]
        if not components or set(components) - set(TOOL_COMPONENTS):
            fail("Components must be a non-empty subset of: " + ",".join(TOOL_COMPONENTS))
        if conflict not in ("error", "keep", "replace"):
            fail("Conflict must be error, keep or replace")
        if from_backup:
            manifest = self.tool_verify(source)
            if manifest["tool"] != tool:
                fail(f"Backup belongs to {manifest['tool']}, not {tool}")
            src = safe_abs(source) / "data"
            label = str(safe_abs(source))
        else:
            if source == target:
                fail("Source and target must differ")
            src = self.tool_root(tool, source)
            label = source
        dst = self.tool_root(tool, target)
        if not src.is_dir() or not dst.is_dir():
            fail("Source and target profile directories must exist")
        plan = self.tool_plan(tool, src, components, credentials)
        conflicts = [rel for rel in plan if exists(dst / rel) and not equal(src / rel, dst / rel)]
        if conflicts and conflict == "error":
            fail(f"{len(conflicts)} conflict(s), e.g. {', '.join(conflicts[:5])}. "
                 "Use --conflict keep or replace explicitly.")
        self.tool_cold(tool)
        auth_line = None
        if tool == "codex" and (dst / "config.toml").is_file():
            for line in (dst / "config.toml").read_text(encoding="utf-8").splitlines():
                if re.match(r"\s*cli_auth_credentials_store\s*=", line):
                    auth_line = line.strip()
        stage = self.stage(dst)
        try:
            for rel in plan:
                overlay(src / rel, stage / rel, conflict)
            if auth_line and (stage / "config.toml").is_file():
                # The target keeps its own credential store, whatever the source used.
                lines = [l for l in (stage / "config.toml").read_text(encoding="utf-8").splitlines()
                         if not re.match(r"\s*cli_auth_credentials_store\s*=", l)]
                atomic_bytes(stage / "config.toml", ("\n".join([auth_line, *lines]) + "\n").encode())
            counts = {}
            for kind in plan.values():
                counts[kind] = counts.get(kind, 0) + 1
            report = {"tool": tool, "source": label, "target": target, "dry_run": dry_run,
                      "components": components, "credentials_copied": credentials,
                      "conflict_policy": conflict, "files": len(plan), "by_class": counts,
                      "conflicts": conflicts[:100], "conflict_count": len(conflicts),
                      "kept_target_auth_store": bool(auth_line)}
            if dry_run:
                return report
            report["target_backup"] = str(self.tool_backup(tool, target))
            self.tool_cold(tool)
            self.transaction([(dst, stage)])
            return report
        finally:
            if stage.exists() and not self.journal.exists():
                shutil.rmtree(stage)

    def tool_export(self, backup, output):
        manifest = copy.deepcopy(self.tool_verify(backup))
        return self.portable_archive(backup, output, manifest, {"data": manifest["files"]},
                                     {"data": manifest["root"]})

    def tool_import(self, archive, expected_sha256):
        return self.extract_archive(archive, expected_sha256, "tool-backups",
                                    {"manifest.json", "data"}, self.tool_verify)

    def tool_list(self):
        out = {}
        for tool, spec in TOOLS.items():
            entry = self.tool_registry(tool)
            try:
                binary, error = str(self.find_tool_binary(tool)), None
            except Error as e:
                binary, error = None, str(e)
            profiles = {}
            for n, p in sorted(entry.get("profiles", {}).items()):
                link = self.root / "sbin" / f"{tool}-{n}"
                profiles[n] = {**p, "env": self.tool_env(tool, n),
                               "launcher": str(link) if link.is_symlink() else None}
            out[tool] = {"title": spec["title"], "binary": binary, "binary_error": error,
                         "configured_binary": entry.get("binary", ""),
                         "can_register": spec["register"], "auth_env": list(spec["auth_env"]),
                         "profiles": profiles}
        return out

    def doctor(self):
        issues = []
        for tool in TOOLS:
            try:
                profiles = self.tool_registry(tool).get("profiles", {})
                for n in profiles:
                    root = self.tool_root(tool, n)
                    if not root.is_dir():
                        issues.append(f"{tool}/{n}: missing directory {root}")
                if profiles:
                    self.find_tool_binary(tool)
            except Error as e:
                issues.append(str(e))
        for n in self.cfg["profiles"]:
            try:
                p = self.profile(n)
                self.validate_roots(n, p.get("cli"), p.get("gui"))
                for root in p.values():
                    if not root.is_dir():
                        issues.append(f"{n}: missing directory {root}")
            except Error as e:
                issues.append(str(e))
        binary = None
        if any("cli" in self.profile(n) for n in self.cfg["profiles"]):
            try:
                binary = str(self.find_binary())
            except Error as e:
                issues.append(str(e))
        if self.journal.exists():
            issues.append("Pending transaction: run recover")
        if (self.root / "update-transaction.json").exists():
            issues.append("Pending update: run update.sh INSTALL_DIR --recover --yes")
        needs_cli = any("cli" in self.profile(n) for n in self.cfg["profiles"])
        return {"version": VERSION, "python": sys.version.split()[0],
                "platform": sys.platform, "root": str(self.root), "binary": binary,
                "path": self.path_setup() if needs_cli else {"not_required": True}, "issues": issues}


def confirm(args, message):
    if not getattr(args, "yes", False):
        fail(message + " Re-run with --yes after reviewing the dry-run.")


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="command")
    sub.add_parser("list")
    sub.add_parser("doctor")
    sub.add_parser("recover")
    for verb in ("create", "register"):
        s = sub.add_parser(verb)
        s.add_argument("name")
        s.add_argument("--cli-dir")
        s.add_argument("--gui-dir")
        s.add_argument("--type", "--kind", dest="kind", choices=("cli", "gui", "both"), default="both")
        s.add_argument("--yes", action="store_true")
    s = sub.add_parser("set-binary")
    s.add_argument("path")
    s = sub.add_parser("set-type")
    s.add_argument("name")
    s.add_argument("kind", choices=("cli", "gui", "both"))
    s.add_argument("--yes", action="store_true")
    s = sub.add_parser("set-gui-app")
    s.add_argument("path")
    s = sub.add_parser("auth-env")
    s.add_argument("name")
    s.add_argument("mode", choices=("inherit", "clean"))
    s = sub.add_parser("launchers")
    s.add_argument("name")
    s = sub.add_parser("path")
    s.add_argument("--write", action="store_true")
    s.add_argument("--yes", action="store_true")
    for verb in ("backup", "restore"):
        s = sub.add_parser(verb)
        s.add_argument("name")
        if verb == "restore":
            s.add_argument("backup")
            s.add_argument("--yes", action="store_true")
        s.add_argument("--scope", choices=("cli", "gui", "both"), default="both")
    s = sub.add_parser("verify")
    s.add_argument("backup")
    s = sub.add_parser("export")
    s.add_argument("backup")
    s.add_argument("output")
    s = sub.add_parser("import")
    s.add_argument("archive")
    s.add_argument("--sha256", required=True)
    for verb in ("migrate", "migrate-backup"):
        s = sub.add_parser(verb)
        s.add_argument("source", help="Profile name, or verified backup directory")
        s.add_argument("target")
        s.add_argument("--scope", choices=("cli", "gui", "both"), default="both")
        s.add_argument("--components", default="settings,skills,plugins,history")
        s.add_argument("--conflict", choices=("error", "keep", "replace"), default="error")
        if verb == "migrate":
            s.add_argument("--credentials", action="store_true")
        s.add_argument("--workspaces", action="store_true")
        s.add_argument("--map", action="append", default=[], metavar="OLD=NEW")
        s.add_argument("--apply", action="store_true", help="Default is a staged dry-run.")
        s.add_argument("--yes", action="store_true")
    s = sub.add_parser("project-copy")
    s.add_argument("name")
    s.add_argument("source")
    s.add_argument("target")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--yes", action="store_true")
    s = sub.add_parser("project-add")
    s.add_argument("name")
    s.add_argument("path")
    s = sub.add_parser("edit-settings")
    s.add_argument("name")
    s.add_argument("--scope", choices=("cli", "gui"), default="cli")
    s.add_argument("--yes", action="store_true")
    tools = tuple(TOOLS)
    s = sub.add_parser("tool-list")
    for verb in ("tool-create", "tool-register"):
        s = sub.add_parser(verb)
        s.add_argument("tool", choices=tools)
        s.add_argument("name")
        s.add_argument("--dir", required=(verb == "tool-register"))
        s.add_argument("--yes", action="store_true")
    s = sub.add_parser("tool-unregister")
    s.add_argument("tool", choices=tools)
    s.add_argument("name")
    s.add_argument("--yes", action="store_true")
    s = sub.add_parser("tool-set-binary")
    s.add_argument("tool", choices=tools)
    s.add_argument("path")
    s = sub.add_parser("tool-auth-env")
    s.add_argument("tool", choices=tools)
    s.add_argument("name")
    s.add_argument("mode", choices=("inherit", "clean"))
    for verb in ("tool-launchers", "tool-backup"):
        s = sub.add_parser(verb)
        s.add_argument("tool", choices=tools)
        s.add_argument("name")
    s = sub.add_parser("tool-verify")
    s.add_argument("backup")
    s = sub.add_parser("tool-restore")
    s.add_argument("tool", choices=tools)
    s.add_argument("name")
    s.add_argument("backup")
    s.add_argument("--yes", action="store_true")
    s = sub.add_parser("tool-migrate")
    s.add_argument("tool", choices=tools)
    s.add_argument("source", help="Source profile name")
    s.add_argument("target")
    s = sub.add_parser("tool-migrate-backup")
    s.add_argument("backup", help="Verified or imported tool backup directory")
    s.add_argument("target")
    for s in (sub.choices["tool-migrate"], sub.choices["tool-migrate-backup"]):
        s.add_argument("--components", default="settings",
                       help="Comma list of " + ",".join(TOOL_COMPONENTS))
        s.add_argument("--conflict", choices=("error", "keep", "replace"), default="error")
        s.add_argument("--credentials", action="store_true",
                       help="Also copy logins, tokens and saved permissions")
        s.add_argument("--apply", action="store_true", help="Default is a staged dry-run.")
        s.add_argument("--yes", action="store_true")
    s = sub.add_parser("tool-export")
    s.add_argument("backup")
    s.add_argument("output")
    s = sub.add_parser("tool-import")
    s.add_argument("archive")
    s.add_argument("--sha256", required=True)
    s = sub.add_parser("tool-run")
    s.add_argument("tool", choices=tools)
    s.add_argument("name")
    s.add_argument("args", nargs=argparse.REMAINDER)
    for verb in ("gui", "cli"):
        s = sub.add_parser(verb)
        s.add_argument("name")
        if verb == "cli":
            s.add_argument("args", nargs=argparse.REMAINDER)
    return p


def dispatch_tool(m, a):
    command = a.command
    if command == "tool-run":
        return m.launch_tool(a.tool, a.name, a.args)
    if command == "tool-verify":
        with m.lock(allow_pending=True):
            manifest = m.tool_verify(Path(a.backup))
            return {"valid": True, "tool": manifest["tool"], "profile": manifest["profile"],
                    "entries": len(manifest["files"])}
    if command == "tool-list":
        with m.lock(allow_pending=True):
            return m.tool_list()
    if command == "tool-export":
        with m.lock():
            return {"archive": str(m.tool_export(Path(a.backup), Path(a.output)))}
    if command == "tool-import":
        with m.lock():
            return {"backup": str(m.tool_import(Path(a.archive), a.sha256))}
    if command in ("tool-migrate", "tool-migrate-backup"):
        if a.apply:
            confirm(a, "Migration commits profile changes.")
        if command == "tool-migrate-backup":
            tool = m.tool_verify(Path(a.backup))["tool"]
            names, source = [m.tool_lock_name(tool, a.target)], safe_abs(a.backup)
        else:
            tool, source = a.tool, a.source
            names = [m.tool_lock_name(tool, a.target), m.tool_lock_name(tool, a.source)]
        with m.lock(names):
            return m.tool_migrate(tool, source, a.target, a.components.split(","), a.conflict,
                                  a.credentials, not a.apply, command == "tool-migrate-backup")
    names = [m.tool_lock_name(a.tool, a.name)] if getattr(a, "name", None) else []
    with m.lock(names):
        if command in ("tool-create", "tool-register"):
            confirm(a, "Creating/registering a profile changes manager state.")
            return m.tool_create(a.tool, a.name, a.dir, command == "tool-register")
        if command == "tool-unregister":
            confirm(a, "Unregistering keeps the data directory but removes the profile from the registry.")
            return m.tool_unregister(a.tool, a.name)
        if command == "tool-set-binary":
            return m.tool_set_binary(a.tool, a.path)
        if command == "tool-auth-env":
            m.tool_profile(a.tool, a.name)["inherit_auth_env"] = a.mode == "inherit"
            m.save()
            return {"tool": a.tool, "profile": a.name, "inherit_auth_env": a.mode == "inherit"}
        if command == "tool-launchers":
            return m.tool_launcher(a.tool, a.name)
        if command == "tool-backup":
            m.tool_cold(a.tool)
            return {"backup": str(m.tool_backup(a.tool, a.name))}
        if command == "tool-restore":
            confirm(a, "Exact restore replaces the profile directory.")
            m.tool_cold(a.tool)
            return {"pre_restore_backup": str(m.tool_restore(a.tool, a.name, Path(a.backup)))}
    fail("Unknown command")


def dispatch(m, a):
    command = a.command
    if command and command.startswith("tool-"):
        return dispatch_tool(m, a)
    if command == "cli":
        return m.launch_cli(a.name, a.args)
    if command == "gui":
        return m.launch_gui(a.name)
    names = [getattr(a, key) for key in ("name", "source", "target")
             if getattr(a, key, None) in m.cfg["profiles"]]
    data_commands = ("backup", "restore", "migrate", "migrate-backup", "edit-settings",
                     "project-copy", "recover", "register", "set-type")
    if command not in data_commands:
        names = []
    elif command == "recover":
        names = list(m.cfg["profiles"])
    with m.lock(names, allow_pending=(command in ("recover", "doctor", "list", "verify"))):
        if command in data_commands:
            m.cold()
        if command == "list":
            return m.cfg
        if command == "doctor":
            return m.doctor()
        if command == "recover":
            return m.recover()
        if command in ("create", "register"):
            confirm(a, "Creating/registering a profile changes manager state.")
            return m.create(a.name, a.cli_dir, a.gui_dir, command == "register", a.kind)
        if command == "set-type":
            confirm(a, "Changing profile type preserves disabled data and backs up active roots.")
            return m.set_type(a.name, a.kind)
        if command == "set-binary":
            old = m.cfg.get("binary")
            m.cfg["binary"] = str(Path(a.path).expanduser().absolute())
            try:
                m.find_binary()
            except BaseException:
                m.cfg["binary"] = old
                raise
            m.save()
            return {"binary": m.cfg["binary"]}
        if command == "set-gui-app":
            p = safe_abs(a.path)
            if not (p / "Contents/MacOS/Claude").is_file():
                fail("Not a Claude.app bundle")
            m.cfg["gui_app"] = str(p)
            m.save()
            return {"gui_app": str(p)}
        if command == "auth-env":
            m.scope_roots(a.name, "cli")
            m.cfg["profiles"][a.name]["inherit_auth_env"] = a.mode == "inherit"
            m.save()
            return {"inherit_auth_env": a.mode == "inherit"}
        if command == "launchers":
            return m.launchers(a.name)
        if command == "path":
            if a.write:
                confirm(a, "This edits your shell startup file with a backup.")
            return m.path_setup(a.write)
        if command == "backup":
            return {"backup": str(m.backup(a.name, a.scope))}
        if command == "verify":
            manifest = m.verify(Path(a.backup))
            return {"valid": True, "profile": manifest["profile"],
                    "scopes": list(manifest["roots"]),
                    "entries": sum(len(x) for x in manifest["files"].values())}
        if command == "restore":
            confirm(a, "Exact restore replaces selected profile roots.")
            return {"pre_restore_backup": str(m.restore(a.name, Path(a.backup), a.scope))}
        if command == "export":
            return {"archive": str(m.export(Path(a.backup), Path(a.output)))}
        if command == "import":
            return {"backup": str(m.import_archive(Path(a.archive), a.sha256))}
        if command in ("migrate", "migrate-backup"):
            if a.apply:
                confirm(a, "Migration commits profile changes.")
            mappings = {}
            for value in a.map:
                if "=" not in value:
                    fail("--map must be OLD=NEW")
                old, new = value.split("=", 1)
                if not old.startswith("/") or not new.startswith("/") or old == "/":
                    fail("Mappings must be absolute, non-root paths")
                mappings[old.rstrip("/")] = new.rstrip("/")
            if command == "migrate-backup":
                return m.migrate_backup(safe_abs(a.source), a.target, a.scope,
                                        a.components.split(","), a.conflict, not a.apply,
                                        mappings, a.workspaces)
            return m.migrate(a.source, a.target, a.scope, a.components.split(","),
                             a.conflict, a.credentials, not a.apply, mappings, a.workspaces)
        if command == "project-copy":
            if a.apply:
                confirm(a, "This copies the project including local uncommitted files.")
            return m.project_copy(a.name, a.source, a.target, not a.apply)
        if command == "project-add":
            m.profile(a.name)
            path = safe_abs(a.path)
            if not path.is_dir():
                fail("Project must be an existing directory")
            items = m.cfg["profiles"][a.name].setdefault("projects", [])
            if str(path) not in items:
                items.append(str(path))
                m.save()
            return {"projects": items}
        if command == "edit-settings":
            confirm(a, "This opens a staged settings file in EDITOR and commits valid JSON on exit.")
            return m.edit_settings(a.name, a.scope)
    fail("Unknown command")


def output(value):
    if value is not None:
        print(json.dumps(value, indent=2, ensure_ascii=False))


def menu(m):
    if not sys.stdin.isatty():
        fail("Administration requires a terminal. Use --help for non-interactive commands.")
    options = {
        "1": ("List profiles", ["list"]),
        "2": ("Create profile + launchers", None),
        "3": ("Register existing directories", None),
        "4": ("Configure real Claude CLI binary", None),
        "5": ("Launch CLI", None),
        "6": ("Launch GUI", None),
        "7": ("Backup", None),
        "8": ("Verify/restore backup", None),
        "9": ("Migrate components (dry-run first)", None),
        "10": ("Copy project (dry-run first)", None),
        "11": ("Export backup / import archive", None),
        "12": ("Install/check shell PATH", None),
        "13": ("Generate launchers", None),
        "14": ("Diagnostics / recover interrupted transaction", None),
        "15": ("Register project directory", None),
        "16": ("Edit CLI / GUI settings (backup + editor + validation)", None),
        "17": ("Change profile type (CLI / GUI / both; preserve disabled data)", None),
        "18": ("Other AI CLIs: Codex / Gemini / Copilot / opencode", None),
    }
    def ask(label):
        return input(label + ": ").strip()
    def yes(label):
        return ask(label + " [type YES]") == "YES"
    def scope():
        return ask("Scope cli/gui/both [both]") or "both"
    def run(args):
        # Refresh config between operations; only controller's registry is read.
        nonlocal m
        m = Manager(m.root, m.home)
        result = dispatch(m, parser().parse_args(args))
        output(result)
        return result
    while True:
        print("\nClaude Profile Manager " + VERSION + "\n")
        for key, (label, _) in options.items():
            print(f"{key:>2}. {label}")
        print(" 0. Exit")
        try:
            choice = ask("Select")
            if choice == "0":
                return 0
            if choice == "1":
                run(["list"])
            elif choice == "2":
                n = ask("Profile name")
                kind = ask("Type cli/gui/both [both]") or "both"
                if yes("Create"):
                    run(["create", n, "--type", kind, "--yes"])
                    run(["launchers", n])
            elif choice == "3":
                n = ask("Name")
                kind = ask("Type cli/gui/both [both]") or "both"
                args = ["register", n, "--type", kind]
                if kind in ("cli", "both"):
                    args += ["--cli-dir", ask("Absolute CLI directory")]
                if kind in ("gui", "both"):
                    args += ["--gui-dir", ask("Absolute GUI directory")]
                if yes("Register these paths, without copying credentials"):
                    run(args + ["--yes"])
            elif choice == "4":
                run(["set-binary", ask("Absolute real Claude binary path")])
            elif choice in ("5", "6"):
                # CLI exec replaces the manager; it does not leave a second shell behind.
                run(["cli" if choice == "5" else "gui", ask("Name")])
            elif choice == "7":
                run(["backup", ask("Name"), "--scope", scope()])
            elif choice == "8":
                b = ask("Backup directory")
                run(["verify", b])
                if yes("Restore verified snapshot to its original profile paths"):
                    run(["restore", ask("Name"), b, "--scope", scope(), "--yes"])
            elif choice == "9":
                args = ["migrate", ask("Source profile"), ask("Target profile"),
                        "--scope", scope(), "--components",
                        ask("Components [settings,skills,plugins,history]") or
                        "settings,skills,plugins,history",
                        "--conflict", ask("Conflict error/keep/replace [error]") or "error"]
                if yes("Also copy ordinary scratch workspaces (not managed Git worktrees)"):
                    args.append("--workspaces")
                while True:
                    mapping = ask("Optional OLD=NEW mapping, empty to finish")
                    if not mapping:
                        break
                    args += ["--map", mapping]
                run(args)
                if yes("Commit this migration; a target backup will be created"):
                    run(args + ["--apply", "--yes"])
            elif choice == "10":
                args = ["project-copy", ask("Target profile"), ask("Source folder"),
                        ask("New destination folder")]
                run(args)
                if yes("Copy now"):
                    run(args + ["--apply", "--yes"])
            elif choice == "11":
                action = ask("export/import/migrate-backup")
                if action == "export":
                    run(["export", ask("Backup directory"), ask("New archive .tar.gz path")])
                elif action == "import":
                    run(["import", ask("Archive path"), "--sha256", ask("Trusted SHA256")])
                elif action == "migrate-backup":
                    args = ["migrate-backup", ask("Verified/imported backup directory"),
                            ask("Target profile"), "--scope", scope(),
                            "--components", ask("Components [settings,skills,plugins,history]")
                            or "settings,skills,plugins,history"]
                    run(args)
                    if yes("Commit backup migration with an automatic target backup"):
                        run(args + ["--apply", "--yes"])
            elif choice == "12":
                run(["path"])
                if yes("Add managed PATH block; preserve rc backup"):
                    run(["path", "--write", "--yes"])
            elif choice == "13":
                run(["launchers", ask("Name")])
            elif choice == "14":
                run(["doctor"])
                if m.journal.exists() and yes("Recover interrupted transaction"):
                    run(["recover"])
            elif choice == "15":
                run(["project-add", ask("Name"), ask("Project path")])
            elif choice == "16":
                name = ask("Name")
                selected_scope = ask("cli/gui [cli]") or "cli"
                if yes("Open EDITOR and commit valid JSON after saving"):
                    run(["edit-settings", name, "--scope", selected_scope, "--yes"])
            elif choice == "17":
                n, kind = ask("Name"), ask("New type cli/gui/both")
                if yes("Back up active roots and change type without deleting data"):
                    run(["set-type", n, kind, "--yes"])
            elif choice == "18":
                tool = ask("Tool " + "/".join(TOOLS))
                action = ask("list/create/register/launchers/run/backup")
                if action == "list":
                    run(["tool-list"])
                elif action in ("create", "register"):
                    n = ask("Profile name")
                    args = ["tool-" + action, tool, n]
                    d = ask("Directory" + (" (empty = default)" if action == "create" else ""))
                    if d:
                        args += ["--dir", d]
                    if yes("Save profile"):
                        run(args + ["--yes"])
                        run(["tool-launchers", tool, n])
                elif action in ("launchers", "backup"):
                    run(["tool-" + action, tool, ask("Profile name")])
                elif action == "run":
                    run(["tool-run", tool, ask("Profile name")])
            else:
                print("Unknown selection.")
        except (Error, OSError, ValueError, subprocess.SubprocessError) as e:
            print("ERROR: " + str(e), file=sys.stderr)
        except (EOFError, KeyboardInterrupt):
            print("\nAdministration closed.", file=sys.stderr)
            return 130


def main(argv=None):
    os.umask(0o077)
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        m = Manager()
        invoked = Path(sys.argv[0]).name
        # Symlink basename, not resolved script name, chooses the profile.
        if invoked.startswith("claude-") and invoked != "claude-manager.py":
            return m.launch_cli(invoked[len("claude-"):], argv)
        for tool in TOOLS:
            if invoked.startswith(tool + "-"):
                return m.launch_tool(tool, invoked[len(tool) + 1:], argv)
        if not argv:
            return menu(m)
        a = parser().parse_args(argv)
        result = dispatch(m, a)
        if isinstance(result, int):
            return result
        output(result)
        return 0
    except KeyboardInterrupt:
        print("Interrupted; run recover if a transaction is pending.", file=sys.stderr)
        return 130
    except (Error, OSError, ValueError, subprocess.SubprocessError) as e:
        print("ERROR: " + str(e), file=sys.stderr)
        if os.environ.get("CM_GUI_LAUNCHER") == "1" and sys.platform == "darwin":
            message = json.dumps(str(e), ensure_ascii=False)
            try:
                subprocess.run(["/usr/bin/osascript", "-e",
                                'display alert "Claude Profile Manager" message ' + message +
                                ' as critical buttons {"OK"} default button "OK"'],
                               capture_output=True, timeout=30)
            except (OSError, subprocess.SubprocessError):
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
