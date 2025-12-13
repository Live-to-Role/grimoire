"""Security utilities for path validation and sanitization."""

from pathlib import Path

from grimoire.config import settings


class PathTraversalError(Exception):
    """Raised when a path traversal attack is detected."""
    pass


def validate_path_in_directory(path: Path | str, allowed_dir: Path | str) -> Path:
    """
    Validate that a path is within an allowed directory.
    
    Args:
        path: The path to validate
        allowed_dir: The directory the path must be within
        
    Returns:
        The resolved path if valid
        
    Raises:
        PathTraversalError: If path is outside allowed directory
    """
    path = Path(path).resolve()
    allowed_dir = Path(allowed_dir).resolve()
    
    try:
        path.relative_to(allowed_dir)
        return path
    except ValueError:
        raise PathTraversalError(
            f"Path '{path}' is outside allowed directory '{allowed_dir}'"
        )


def validate_library_path(path: Path | str) -> Path:
    """Validate that a path is within the library directory."""
    return validate_path_in_directory(path, settings.library_path)


def validate_covers_path(path: Path | str) -> Path:
    """Validate that a path is within the covers directory."""
    return validate_path_in_directory(path, settings.covers_dir)


def validate_data_path(path: Path | str) -> Path:
    """Validate that a path is within the data directory."""
    return validate_path_in_directory(path, settings.data_dir)


def is_safe_path(path: Path | str, allowed_dir: Path | str) -> bool:
    """
    Check if a path is within an allowed directory.
    
    Returns:
        True if path is safe, False otherwise
    """
    try:
        validate_path_in_directory(path, allowed_dir)
        return True
    except PathTraversalError:
        return False
