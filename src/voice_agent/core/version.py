import subprocess
from pathlib import Path

from voice_agent import __version__
from voice_agent.config.settings import Settings
from voice_agent.models.schemas import VersionResponse

ROOT = Path(__file__).resolve().parents[3]


def _git_value(args: list[str], fallback: str) -> str:
    try:
        return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return fallback


def get_version(settings: Settings) -> VersionResponse:
    return VersionResponse(
        version=__version__,
        commit=_git_value(["git", "rev-parse", "--short", "HEAD"], "unknown"),
        branch=_git_value(["git", "branch", "--show-current"], "unknown"),
        deployed_at=settings.deployed_at,
    )
