"""Build a reviewed Windows test directory and ZIP from explicit runtime inputs.

Requires installed Python 3.12, Node 24, .NET 10 and LibreOffice on the target.
Never copy a virtualenv, .env, repository, task store or original Brief project.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import shutil
import sys
import tomllib
from xml.etree import ElementTree
import zipfile
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
IGNORED = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".env", ".env.*", "node_modules", ".git")


def copy_tree(source, target):
    if not source.is_dir(): raise ValueError(f"Missing runtime directory: {source.name}")
    shutil.copytree(source, target, ignore=IGNORED)


def vendor_python(target):
    pending = [("autoformat-api", set()), ("brief-parser", set())]
    visited, inventories = {}, []
    while pending:
        name, extras = pending.pop()
        name = canonicalize_name(name)
        previous = visited.get(name)
        if previous is not None and extras <= previous: continue
        visited[name] = (previous or set()) | extras
        distribution = metadata.distribution(name)
        # Editable distribution metadata may predate current project changes.
        local_project = {"autoformat-api": ROOT / "apps/api/pyproject.toml",
                         "brief-parser": ROOT / "modules/brief_parsing/pyproject.toml"}.get(name)
        requirements = (tomllib.loads(local_project.read_text(encoding="utf-8"))["project"]["dependencies"]
                        if local_project else distribution.requires or [])
        for raw in requirements:
            requirement = Requirement(raw)
            if requirement.marker and not any(requirement.marker.evaluate({"extra": extra}) for extra in extras | {""}): continue
            dependency = metadata.distribution(requirement.name)
            if dependency.version not in requirement.specifier: raise ValueError(f"Dependency version mismatch: {requirement.name}")
            pending.append((requirement.name, set(requirement.extras)))
        if previous is not None: continue
        inventories.append({"name": name, "version": distribution.version})
        if name in {"autoformat-api", "brief-parser"}: continue
        base = Path(distribution.locate_file("")).resolve()
        for entry in distribution.files or []:
            if ".." in entry.parts or "__pycache__" in entry.parts or entry.suffix in {".pyc", ".pyo", ".pth"} or entry.name in {"direct_url.json", "RECORD", ".env"} or entry.name.startswith(".env."): continue
            source = Path(distribution.locate_file(entry)).resolve(strict=True)
            if not source.is_relative_to(base): raise ValueError("Dependency file escapes its installation")
            destination = target / str(entry)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and destination.read_bytes() != source.read_bytes(): raise ValueError("Dependency file collision")
            shutil.copyfile(source, destination)
    return sorted(inventories, key=lambda value: value["name"])


def vendor_node(source, destination):
    visited = {}
    def install(name, origin):
        package = next((directory / "node_modules" / name for directory in [origin, *origin.parents]
                        if (directory / "node_modules" / name / "package.json").is_file()), None)
        if package is None: return False
        package = package.resolve(strict=True)
        data = json.loads((package / "package.json").read_text(encoding="utf-8"))
        if name in visited:
            if visited[name] != data["version"]: raise ValueError("Node dependency version collision")
            return True
        visited[name] = data["version"]
        copy_tree(package, destination / name)
        for key in data.get("dependencies", {}):
            if not install(key, package): raise ValueError("Missing required Node dependency")
        for key in data.get("optionalDependencies", {}): install(key, package)
        return True
    if not install("pdfjs-dist", source): raise ValueError("Build/install the web dependencies first")
    return visited


def vendor_dotnet_notices(target):
    project = ROOT / "services/docx_engine/AutoFormat.DocxEditor"
    assets = json.loads((project / "obj/project.assets.json").read_text(encoding="utf-8"))
    deployed = json.loads((project / "bin/Debug/net10.0/AutoFormat.DocxEditor.deps.json").read_text(encoding="utf-8"))
    inventories = []
    for name, library in deployed["libraries"].items():
        if library["type"] != "package": continue
        relative = assets["libraries"][name]["path"]
        source = next((Path(folder) / relative for folder in assets["packageFolders"]
                       if (Path(folder) / relative).is_dir()), None)
        if source is None: raise ValueError("Missing editor package metadata")
        nuspec = next(source.glob("*.nuspec"))
        fields = {element.tag.rsplit("}", 1)[-1]: element for element in ElementTree.parse(nuspec).iter()}
        license_field = fields["license"]
        if license_field.attrib.get("type") != "expression" or license_field.text != "MIT":
            raise ValueError("Review the changed editor dependency license before bundling")
        destination = target / name
        destination.mkdir(parents=True)
        for path in source.iterdir():
            if path.is_file() and (path.suffix == ".nuspec" or any(term in path.name.lower() for term in ("license", "notice", "readme"))):
                shutil.copyfile(path, destination / path.name)
        (destination / "LICENSE.txt").write_text("MIT License\n\n" + fields["copyright"].text + "\n\n" +
            "Permission is hereby granted, free of charge, to any person obtaining a copy "
            "of this software and associated documentation files (the \"Software\"), to deal "
            "in the Software without restriction, including without limitation the rights "
            "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell "
            "copies of the Software, and to permit persons to whom the Software is "
            "furnished to do so, subject to the following conditions:\n\n"
            "The above copyright notice and this permission notice shall be included in "
            "all copies or substantial portions of the Software.\n\n"
            "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR "
            "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, "
            "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE "
            "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER "
            "LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING "
            "FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER "
            "DEALINGS IN THE SOFTWARE.\n", encoding="utf-8")
        inventories.append({"package": name, "license": "MIT"})
    return inventories


def build(output):
    output = output.resolve()
    if not output.is_relative_to(ROOT / "runtime/releases") or output == ROOT / "runtime/releases":
        raise ValueError("The bundle must be a new directory under runtime/releases")
    if output.exists() or output.with_suffix(".zip").exists(): raise ValueError("Refusing to overwrite an existing bundle")
    output.mkdir(parents=True)
    # Failures leave a non-launchable staging directory for diagnosis; no manifest means no runnable bundle.
    for relative in ("apps/api/src/autoformat", "modules/brief_parsing/src/brief_parser",
                     "modules/brief_parsing/prompts", "modules/brief_parsing/domain_packs", "contracts", "apps/web/dist",
                     "services/docx_engine/AutoFormat.DocxEditor/bin/Debug/net10.0"):
        copy_tree(ROOT / relative, output / relative)
    for relative in ("scripts/pdf_text_index.mjs", "modules/brief_parsing/SOURCE_SNAPSHOT.json", "modules/brief_parsing/LOCAL_CHANGES.json"):
        destination = output / relative; destination.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / relative, destination)
    for name in ("launch.py", "Start-AutoFormat.cmd", "config.example.json", "README.md"):
        shutil.copyfile(ROOT / "desktop" / name, output / name)
    config_path = output / "config.example.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["editor_sha256"] = hashlib.sha256((output / config["editor_dll"]).read_bytes()).hexdigest()
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    inventories = vendor_python(output / "python")
    node_packages = vendor_node(ROOT / "apps/web", output / "apps/web/node_modules")
    dotnet_packages = vendor_dotnet_notices(output / "third-party/dotnet")
    manifest = {"schema_version": "windows-test-bundle/1.0", "application_version": "0.1.0-test",
        "created_at": datetime.now(timezone.utc).isoformat(), "platform": "win-amd64", "python": "3.12",
        "external_runtimes": ["Python 3.12", "Node.js 24", ".NET 10", "LibreOffice with pinned executable"],
        "python_distributions": inventories, "node_packages": node_packages, "dotnet_packages": dotnet_packages,
        "files": {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(output.rglob("*")) if p.is_file()}}
    (output / "bundle-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with zipfile.ZipFile(output.with_suffix(".zip"), "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob("*")):
            if path.is_file(): archive.write(path, Path(output.name) / path.relative_to(output))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "runtime/releases" / ("AutoFormat-test-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
    arguments = parser.parse_args()
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12) or platform.machine().upper() not in {"AMD64", "X86_64"}:
        parser.error("Build with Windows AMD64 Python 3.12")
    try: print(build(arguments.output))
    except (OSError, ValueError, metadata.PackageNotFoundError) as error: parser.error(str(error))
