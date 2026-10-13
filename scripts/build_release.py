#!/usr/bin/env python3
"""Build a standalone zipapp and checksums using only Python's standard library."""

import argparse
import hashlib
from pathlib import Path
import shutil
import tempfile
import tomllib
import zipapp


ROOT = Path(__file__).resolve().parents[1]


def build(output: Path, interpreter: str = "/usr/bin/env python3") -> Path:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    version = metadata["project"]["version"]
    namespace = {}
    exec((ROOT / "tcar" / "__init__.py").read_text(), namespace)
    if version != namespace["__version__"]:
        raise ValueError("package metadata and application versions disagree")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "tcar.pyz"
    with tempfile.TemporaryDirectory(prefix="tcar-build-") as directory:
        stage = Path(directory)
        shutil.copytree(ROOT / "tcar", stage / "tcar", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(ROOT / "LICENSE", stage / "LICENSE")
        # zipapp's generated main() discards its return value. Preserve CLI errors.
        (stage / "__main__.py").write_text("from tcar.app import main\nraise SystemExit(main())\n")
        zipapp.create_archive(stage, destination, interpreter=interpreter, compressed=True)
    destination.chmod(0o755)
    assets = sorted(path for path in output.iterdir() if path.name == "tcar.pyz" or path.suffix == ".whl" or path.name.endswith(".tar.gz"))
    checksums = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in assets)
    (output / "SHA256SUMS").write_text(checksums)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    print(build(args.output_dir))


if __name__ == "__main__":
    main()
