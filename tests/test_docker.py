"""Prova con Docker e LM Studio attivi: pytest -m docker."""

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

ROOT = Path(__file__).resolve().parent.parent


def test_compose_orologio():
    if not (ROOT / ".env").is_file():
        pytest.skip("Serve un file .env valido per la prova Docker.")

    build = subprocess.run(
        ["docker", "compose", "build"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    assert build.returncode == 0, build.stdout + build.stderr

    run = subprocess.run(
        ["docker", "compose", "run", "--rm", "-T", "assistente"],
        cwd=ROOT,
        input="Che ore sono a Tokyo?\nesci\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "[strumento] orologio(" in run.stdout, run.stdout
