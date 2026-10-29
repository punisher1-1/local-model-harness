import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_image_copies_every_local_module_it_imports():
    copied = {name for line in (ROOT / "Dockerfile").read_text().splitlines()
              if line.startswith("COPY ") and "--from" not in line
              for name in re.findall(r"\b(\w+)\.py\b", line)}
    local = {p.stem for p in ROOT.glob("*.py")}
    missing = set()
    for name in copied:
        for node in ast.walk(ast.parse((ROOT / f"{name}.py").read_text())):
            if isinstance(node, ast.Import):
                missing |= {a.name.split(".")[0] for a in node.names} & local - copied
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                missing |= {node.module.split(".")[0]} & local - copied
    assert not missing, f"Dockerfile does not copy: {sorted(missing)}"
