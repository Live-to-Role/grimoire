"""Facts about how this Grimoire process is deployed.

Grimoire ships two deployments — a Docker stack and a native install — and the
correct answer to "what path do I type here?" is the opposite in each. Error
messages need to know which one they are running in.
"""

from pathlib import Path

# Where the Docker stack bind-mounts the user's libraries. These paths exist
# only inside the container.
CONTAINER_LIBRARY_PATHS = ("/library", "/library2", "/library3")


def in_container() -> bool:
    """Best-effort detection of running inside Docker."""
    if Path("/.dockerenv").exists():
        return True
    try:
        return "docker" in Path("/proc/1/cgroup").read_text()
    except OSError:
        return False


def looks_like_container_library_path(path: str) -> bool:
    """Whether `path` is one of the container mount points (or under one)."""
    normalised = path.replace("\\", "/").rstrip("/").lower() or "/"
    return any(
        normalised == mount or normalised.startswith(f"{mount}/")
        for mount in CONTAINER_LIBRARY_PATHS
    )


def looks_like_windows_path(path: str) -> bool:
    """Whether `path` is a Windows drive path (`C:\\...` / `C:/...`)."""
    return len(path) >= 2 and path[1] == ":" and path[0].isalpha()
