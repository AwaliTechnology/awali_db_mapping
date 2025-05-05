#!/usr/bin/env python3

import re
import subprocess
import sys
from pathlib import Path

# Handle TOML parsing based on Python version
try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib # Requires: pip install tomli
    except ImportError:
        print("Error: 'tomli' package not found. Please install it for Python < 3.11:")
        print("  pip install tomli")
        sys.exit(1)

PYPROJECT_PATH = Path("pyproject.toml")
VERSION_REGEX = re.compile(
    r"""
    ^
    (?P<major>0|[1-9]\d*)
    \.
    (?P<minor>0|[1-9]\d*)
    \.
    (?P<patch>0|[1-9]\d*)
    (?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?
    (?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?
    $
    """,
    re.VERBOSE,
)


def run_command(command, capture_output=False, check=True, shell=False):
    """Runs a shell command."""
    print(f"Running: {' '.join(command)}")
    try:
        result = subprocess.run(
            command,
            capture_output=capture_output,
            text=True,
            check=check,
            shell=shell # Use shell=True cautiously if needed, but prefer list of args
        )
        return result
    except FileNotFoundError:
        print(f"Error: Command not found: {command[0]}. Is git installed and in PATH?")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {' '.join(command)}")
        print(f"Return code: {e.returncode}")
        if e.stdout:
            print(f"stdout:\n{e.stdout}")
        if e.stderr:
            print(f"stderr:\n{e.stderr}")
        sys.exit(1)


def get_current_version(pyproject_path: Path) -> str:
    """Reads the version from pyproject.toml."""
    if not pyproject_path.is_file():
        print(f"Error: {pyproject_path} not found.")
        sys.exit(1)

    try:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)

        # Check standard [project] table first, then [tool.poetry]
        if "project" in data and "version" in data["project"]:
            version = data["project"]["version"]
        elif "tool" in data and "poetry" in data["tool"] and "version" in data["tool"]["poetry"]:
            version = data["tool"]["poetry"]["version"]
        else:
            print(f"Error: Could not find version field in [project] or [tool.poetry] in {pyproject_path}")
            sys.exit(1)

        if not isinstance(version, str) or not VERSION_REGEX.match(version):
             print(f"Error: Found version '{version}' is not a valid PEP 440 string.")
             sys.exit(1)
        return version

    except tomllib.TOMLDecodeError as e:
        print(f"Error parsing {pyproject_path}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred reading version: {e}")
        sys.exit(1)


def suggest_next_version(version_str: str) -> str | None:
    """Suggests the next patch version."""
    match = VERSION_REGEX.match(version_str)
    if not match or match.group("prerelease") or match.group("buildmetadata"):
        print(f"Warning: Cannot auto-increment complex version '{version_str}'. Please enter manually.")
        return None

    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch"))
    return f"{major}.{minor}.{patch + 1}"


def update_pyproject_version(pyproject_path: Path, current_version: str, new_version: str):
    """Updates the version string in pyproject.toml using regex."""
    print(f"Updating {pyproject_path} from {current_version} to {new_version}...")
    try:
        content = pyproject_path.read_text()
        # Look for version = "..." or version = '...' under [project] or [tool.poetry]
        # This is a bit simplistic but avoids messing up complex TOML structures
        updated_content, count = re.subn(
            rf'(version\s*=\s*["\']){re.escape(current_version)}(["\'])',
            rf'\g<1>{new_version}\g<2>',
            content,
            count=1 # Only replace the first occurrence
        )

        if count == 0:
            print(f"Error: Could not find 'version = \"{current_version}\"' in {pyproject_path} to replace.")
            print("Please check the file format.")
            sys.exit(1)

        pyproject_path.write_text(updated_content)
        print(f"{pyproject_path} updated successfully.")

    except IOError as e:
        print(f"Error writing to {pyproject_path}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred updating version: {e}")
        sys.exit(1)


def main():
    print("--- PyPI Teleport ---")

    # 1. Check for uncommitted changes
    print("Checking git status...")
    status_result = run_command(["git", "status", "--porcelain"], capture_output=True)
    if status_result.stdout.strip():
        print("\nError: Your working directory has uncommitted changes.")
        print("Please commit or stash them before running this script.")
        print("\nGit status output:")
        print(status_result.stdout)
        sys.exit(1)
    print("Git status clean.")

    # 2. Get current branch
    branch_result = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True)
    current_branch = branch_result.stdout.strip()
    print(f"Current git branch: {current_branch}")


    # 3. Get current version
    current_version = get_current_version(PYPROJECT_PATH)
    print(f"Current version in {PYPROJECT_PATH}: {current_version}")

    # 4. Suggest next version
    suggested_version = suggest_next_version(current_version)

    # 5. Prompt user
    prompt_message = f"Enter new version (suggested: {suggested_version}): " if suggested_version else "Enter new version: "
    while True:
        user_input = input(prompt_message).strip()
        if not user_input and suggested_version:
            new_version = suggested_version
            break
        elif user_input:
            if VERSION_REGEX.match(user_input):
                new_version = user_input
                break
            else:
                print(f"Invalid version format: '{user_input}'. Please use format like X.Y.Z (e.g., 0.1.1)")
        else: # No input and no suggestion
             print("No version suggested or entered. Exiting.")
             sys.exit(0)


    if new_version == current_version:
        print("New version is the same as the current version. Exiting.")
        sys.exit(0)

    print(f"Selected version: {new_version}")

    # 6. Confirmation
    confirm = input(f"Proceed with version {new_version}? (Update {PYPROJECT_PATH}, commit, tag v{new_version}, push) [y/N]: ").lower()
    if confirm != 'y':
        print("Operation cancelled.")
        sys.exit(0)

    # 7. Perform actions
    try:
        update_pyproject_version(PYPROJECT_PATH, current_version, new_version)

        commit_message = f"chore: Bump version to v{new_version}"
        tag_name = f"v{new_version}"

        run_command(["git", "add", str(PYPROJECT_PATH)])
        run_command(["git", "commit", "-m", commit_message])
        run_command(["git", "tag", tag_name])
        run_command(["git", "push", "origin", current_branch])
        run_command(["git", "push", "origin", tag_name])

        print("\n--- Success! ---")
        print(f"Version updated to {new_version}")
        print(f"Committed changes to branch '{current_branch}'")
        print(f"Created and pushed tag '{tag_name}'")
        print("GitHub Action should now be triggered to publish to PyPI.")

    except Exception as e:
        # Catch any unexpected errors during the git operations or file update
        print(f"\n--- An error occurred during the process ---")
        print(f"Error details: {e}")
        print("\nPlease check the state of your repository.")
        print("You might need to manually clean up commits or tags.")
        sys.exit(1)


if __name__ == "__main__":
    main()
