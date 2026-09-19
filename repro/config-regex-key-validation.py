"""Probe C1: pyproject type validation for the four regex config keys."""
import subprocess
import tempfile
from pathlib import Path

VB = Path.cwd() / ".venv/bin/black"
tmp = Path(tempfile.mkdtemp(prefix="bkcfg"))
(tmp / "a1.py").write_text("x = 1\n", "utf-8")
(tmp / "b2.py").write_text("y = 2\n", "utf-8")
(tmp / "sub").mkdir()
(tmp / "sub" / "c3.py").write_text("z = 3\n", "utf-8")

CASES = [
    'exclude = ["a"]',
    'extend-exclude = ["a"]',
    'force-exclude = ["a"]',
    'include = ["a"]',
    'include = {a = 1}',
]
for case in CASES:
    (tmp / "pyproject.toml").write_text(f"[tool.black]\n{case}\n", "utf-8")
    r = subprocess.run([str(VB), "--no-cache", "-q", "--check", "."], cwd=tmp,
                       capture_output=True, text=True)
    files = [ln.split("/")[-1] for ln in r.stderr.splitlines() if "reformat" in ln]
    print(f"--- [tool.black] {case}")
    print(f"    rc={r.returncode}  stderr={r.stderr.strip().splitlines()[:2]}")
    (tmp / "pyproject.toml").write_text(f"[tool.black]\n{case}\n", "utf-8")
    v = subprocess.run([str(VB), "--no-cache", "-v", "--check", "."], cwd=tmp,
                       capture_output=True, text=True)
    collected = [ln.name for ln in tmp.glob("**/*.py")]
    touched = sorted({ln.split("/")[-1] for ln in v.stderr.splitlines()
                      if "already well formatted" in ln or "reformat" in ln})
    print(f"    files black actually processed: {touched} (of {sorted(collected)})")
