#!/usr/bin/env python3
import tomllib, pathlib, sys
proj = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"
data = tomllib.loads(proj.read_text())
reqs = data["project"]["dependencies"]
(pathlib.Path(__file__).parents[1] / "requirements.txt").write_text("\n".join(reqs) + "\n")
print("requirements.txt regenerated from pyproject.toml")
