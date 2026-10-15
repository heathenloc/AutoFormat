"""Standard-library bootstrap. Verify the entire bundle before importing it."""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys


def verify_bundle(root):
    manifest_path = root / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "windows-test-bundle/1.0" or not manifest.get("files"):
        raise ValueError("Invalid bundle manifest")
    expected = set()
    for relative, digest in manifest["files"].items():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative:
            raise ValueError("Invalid bundle path")
        target = root / path
        if target.is_symlink() or not target.resolve(strict=True).is_relative_to(root.resolve()):
            raise ValueError("Redirected bundle file")
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("Bundle file changed")
        expected.add(relative)
    entries = list(root.rglob("*"))
    if any(p.is_symlink() for p in entries): raise ValueError("Redirected bundle directory")
    actual = {p.relative_to(root).as_posix() for p in entries if p.is_file()}
    if actual != expected | {"bundle-manifest.json"}: raise ValueError("Unexpected or missing bundle files")
    return manifest


def main():
    root = Path(__file__).resolve().parent
    try: verify_bundle(root)
    except (OSError, ValueError, KeyError, TypeError):
        print("AutoFormat 测试包不完整或文件已变化，请重新解压原测试包。", file=sys.stderr); return 2
    if sys.version_info[:2] != (3, 12) or sys.platform != "win32" or struct.calcsize("P") != 8:
        print("请使用 Windows 64 位 Python 3.12 启动 AutoFormat。", file=sys.stderr); return 2
    if not sys.flags.isolated or not sys.flags.no_site:
        print("请使用 Start-AutoFormat.cmd 启动，或为 Python 添加 -I -S -B 参数。", file=sys.stderr); return 2
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    # Explicit application-local paths. No editable install or source-project dependency.
    sys.path[:0] = [str(root / "apps/api/src"), str(root / "modules/brief_parsing/src"), str(root / "python")]
    try:
        from autoformat.desktop_host import main as run
    except ImportError:
        print("AutoFormat 运行依赖无法加载，请重新解压原测试包并核对 Python 版本。", file=sys.stderr); return 2
    sys.argv.extend(["--root", str(root)])
    run()
    return 0


if __name__ == "__main__": raise SystemExit(main())
