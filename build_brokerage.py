#!/usr/bin/env python
"""
Brokerage Build Automation Script

This script automates the process of cloning, building, and deploying LEAN brokerage plugins.
Automatically handles dependencies (e.g., IBAutomater for InteractiveBrokers).

Usage:
    python build_brokerage.py                              # Build all brokerages (skip if already built)
    python build_brokerage.py --rebuild Kraken             # Rebuild specific brokerage
    python build_brokerage.py --rebuild InteractiveBrokers # Rebuild IB (includes IBAutomater)
    python build_brokerage.py --rebuild all                # Rebuild all brokerages
"""

import os
import sys
import subprocess
import shutil
import argparse
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

# ANSI color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

# Brokerage configurations
BROKERAGES = [
    {
        "name": "Kraken",
        "repo_url": "https://github.com/QuantConnect/Lean.Brokerages.Kraken.git",
        "target_dir": "../Lean.Brokerages.Kraken",
        "solution_file": "QuantConnect.KrakenBrokerage.sln",
        "dlls": [
            {
                "src": "QuantConnect.KrakenBrokerage/bin/Debug/QuantConnect.KrakenBrokerage.dll",
                "dst": "Launcher/bin/Debug/QuantConnect.KrakenBrokerage.dll"
            }
        ]
    },
    {
        "name": "InteractiveBrokers",
        "repo_url": "https://github.com/QuantConnect/Lean.Brokerages.InteractiveBrokers.git",
        "target_dir": "../Lean.Brokerages.InteractiveBrokers",
        "solution_file": "QuantConnect.InteractiveBrokersBrokerage.sln",
        "dlls": [
            {
                "src": "QuantConnect.InteractiveBrokersBrokerage/bin/Debug/QuantConnect.Brokerages.InteractiveBrokers.dll",
                "dst": "Launcher/bin/Debug/QuantConnect.Brokerages.InteractiveBrokers.dll"
            },
            {
                "src": "QuantConnect.InteractiveBrokersBrokerage/bin/Debug/CSharpAPI.dll",
                "dst": "Launcher/bin/Debug/CSharpAPI.dll"
            }
        ],
        "dependencies": ["IBAutomater"]
    }
]


def log_info(message: str):
    """Print info message in blue"""
    print(f"{Colors.BLUE}[INFO]{Colors.RESET} {message}")


def log_success(message: str):
    """Print success message in green"""
    print(f"{Colors.GREEN}[SUCCESS]{Colors.RESET} {message}")


def log_skip(message: str):
    """Print skip message in yellow"""
    print(f"{Colors.YELLOW}[SKIP]{Colors.RESET} {message}")


def log_error(message: str):
    """Print error message in red"""
    print(f"{Colors.RED}[ERROR]{Colors.RESET} {message}")


def verify_lean_root() -> bool:
    """
    Verify that the current directory is the LEAN root directory.

    Returns:
        bool: True if current directory is 'Lean', False otherwise
    """
    current_dir = Path.cwd().name

    if current_dir != "Lean":
        log_error(f"Current directory is '{current_dir}', but must be 'Lean'")
        log_error("Brokerage projects depend on relative paths to LEAN project")
        log_error("Please run this script from the LEAN root directory")
        return False

    log_success("Verified: Running from LEAN root directory")
    return True


def clone_repo(repo_url: str, target_dir: str) -> bool:
    """
    Clone a git repository to the target directory.

    Args:
        repo_url: Git repository URL
        target_dir: Target directory path (relative to Lean/)

    Returns:
        bool: True if cloned or already exists, False on error
    """
    target_path = Path(target_dir)

    if target_path.exists():
        log_skip(f"Repository already exists: {target_dir}")
        return True

    log_info(f"Cloning repository: {repo_url}")
    log_info(f"Target directory: {target_dir}")

    try:
        result = subprocess.run(
            ["git", "clone", repo_url, str(target_path)],
            check=True,
            capture_output=True,
            text=True
        )
        log_success(f"Successfully cloned: {target_dir}")
        return True
    except subprocess.CalledProcessError as e:
        log_error(f"Failed to clone repository: {e.stderr}")
        return False


def build_brokerage(brokerage_dir: str, solution_file: str, force: bool = False) -> bool:
    """
    Build a brokerage project.

    Args:
        brokerage_dir: Brokerage directory path
        solution_file: Solution file name
        force: Force rebuild even if already built

    Returns:
        bool: True if built successfully, False on error
    """
    brokerage_path = Path(brokerage_dir)
    solution_path = brokerage_path / solution_file

    if not solution_path.exists():
        log_error(f"Solution file not found: {solution_path}")
        return False

    # Check if already built (unless force rebuild)
    if not force:
        dll_pattern = brokerage_path / "**/bin/Debug/*.dll"
        dll_files = list(brokerage_path.glob("**/bin/Debug/*.dll"))

        if dll_files:
            log_skip(f"Brokerage already built: {brokerage_dir}")
            return True

    log_info(f"Building brokerage: {brokerage_dir}")
    log_info(f"Solution: {solution_file}")

    try:
        result = subprocess.run(
            ["dotnet", "build", str(solution_path)],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(brokerage_path)
        )
        log_success(f"Successfully built: {brokerage_dir}")
        return True
    except subprocess.CalledProcessError as e:
        log_error(f"Build failed: {e.stderr}")
        return False


def build_lean(force: bool = False) -> bool:
    """
    Build the LEAN project.

    Args:
        force: Force rebuild even if already built

    Returns:
        bool: True if built successfully, False on error
    """
    solution_file = "QuantConnect.Lean.sln"
    solution_path = Path(solution_file)

    if not solution_path.exists():
        log_error(f"LEAN solution not found: {solution_file}")
        return False

    # Check if already built (unless force rebuild)
    if not force:
        dll_files = list(Path("Launcher/bin/Debug").glob("*.dll"))
        if dll_files:
            log_skip("LEAN project already built")
            return True

    log_info(f"Building LEAN project: {solution_file}")

    try:
        result = subprocess.run(
            ["dotnet", "build", solution_file],
            check=True,
            capture_output=True,
            text=True
        )
        log_success("Successfully built LEAN project")
        return True
    except subprocess.CalledProcessError as e:
        log_error(f"LEAN build failed: {e.stderr}")
        return False


def copy_dlls(brokerage_dir: str, dll_configs: List[Dict[str, str]], force: bool = False) -> bool:
    """
    Copy DLL files to Launcher/bin/Debug.

    Args:
        brokerage_dir: Brokerage directory path
        dll_configs: List of dicts with 'src' and 'dst' paths
        force: Force copy even if destination exists

    Returns:
        bool: True if all copied successfully, False on error
    """
    brokerage_path = Path(brokerage_dir)
    all_success = True

    for dll_config in dll_configs:
        src = brokerage_path / dll_config["src"]
        dst = Path(dll_config["dst"])

        if not src.exists():
            log_error(f"Source DLL not found: {src}")
            all_success = False
            continue

        # Check if destination exists and is up-to-date (unless force)
        if not force and dst.exists():
            src_mtime = src.stat().st_mtime
            dst_mtime = dst.stat().st_mtime

            if dst_mtime >= src_mtime:
                log_skip(f"DLL already up-to-date: {dst.name}")
                continue

        log_info(f"Copying DLL: {src.name} -> {dst}")

        try:
            # Ensure destination directory exists
            dst.parent.mkdir(parents=True, exist_ok=True)

            # Copy file
            shutil.copy2(str(src), str(dst))
            log_success(f"Successfully copied: {dst.name}")
        except Exception as e:
            log_error(f"Failed to copy {src.name}: {e}")
            all_success = False

    return all_success


def download_ibautomater(force: bool = False) -> bool:
    """
    Download IBAutomater DLLs from NuGet package.

    Args:
        force: Force download even if already exists

    Returns:
        bool: True if download successful, False on error
    """
    target_dir = Path("Launcher/bin/Debug")
    dll_path = target_dir / "QuantConnect.IBAutomater.dll"
    jar_path = target_dir / "IBAutomater.jar"
    sh_path = target_dir / "IBAutomater.sh"

    # Check if already downloaded (unless force)
    if not force and dll_path.exists() and jar_path.exists() and sh_path.exists():
        log_skip("IBAutomater already downloaded")
        return True

    log_info("Downloading IBAutomater from NuGet...")

    temp_dir = Path("temp_ibautomater")
    zip_file = temp_dir / "IBAutomater.zip"

    try:
        # Create temp directory
        temp_dir.mkdir(exist_ok=True)

        # Download NuGet package
        nuget_url = "https://www.nuget.org/api/v2/package/QuantConnect.IBAutomater"
        log_info(f"Downloading from: {nuget_url}")

        urllib.request.urlretrieve(nuget_url, str(zip_file))
        log_success("Downloaded NuGet package")

        # Extract package
        log_info("Extracting package...")
        with zipfile.ZipFile(str(zip_file), 'r') as zip_ref:
            zip_ref.extractall(str(temp_dir))
        log_success("Extracted package")

        # Ensure target directory exists
        target_dir.mkdir(parents=True, exist_ok=True)

        # Copy DLL (try netstandard2.1 first, then netstandard2.0)
        dll_src = temp_dir / "lib" / "netstandard2.1" / "QuantConnect.IBAutomater.dll"
        if not dll_src.exists():
            dll_src = temp_dir / "lib" / "netstandard2.0" / "QuantConnect.IBAutomater.dll"

        if not dll_src.exists():
            log_error("Could not find QuantConnect.IBAutomater.dll in package")
            return False

        shutil.copy2(str(dll_src), str(dll_path))
        log_success(f"Copied {dll_path.name}")

        # Copy JAR file
        jar_src = temp_dir / "contentFiles" / "any" / "any" / "IBAutomater.jar"
        if jar_src.exists():
            shutil.copy2(str(jar_src), str(jar_path))
            log_success(f"Copied {jar_path.name}")
        else:
            log_skip("IBAutomater.jar not found in package")

        # Copy shell script
        sh_src = temp_dir / "contentFiles" / "any" / "any" / "IBAutomater.sh"
        if sh_src.exists():
            shutil.copy2(str(sh_src), str(sh_path))
            log_success(f"Copied {sh_path.name}")
        else:
            log_skip("IBAutomater.sh not found in package")

        # Cleanup temp directory
        shutil.rmtree(str(temp_dir))
        log_success("IBAutomater downloaded and installed successfully")

        return True

    except Exception as e:
        log_error(f"Failed to download IBAutomater: {e}")
        # Cleanup on error
        if temp_dir.exists():
            shutil.rmtree(str(temp_dir))
        return False


def build_all_brokerages(rebuild_target: Optional[str] = None):
    """
    Main build process for all brokerages.

    Args:
        rebuild_target: If specified, only rebuild this brokerage (or 'all')
    """
    print("\n" + "="*60)
    print("  LEAN Brokerage Build Automation")
    print("="*60 + "\n")

    # Step 1: Verify we're in LEAN root directory
    if not verify_lean_root():
        sys.exit(1)

    print()

    # Determine which brokerages to process
    if rebuild_target:
        if rebuild_target.lower() == "all":
            brokerages_to_rebuild = BROKERAGES
            log_info("Rebuilding all brokerages (forced)")
        else:
            brokerages_to_rebuild = [b for b in BROKERAGES if b["name"].lower() == rebuild_target.lower()]
            if not brokerages_to_rebuild:
                log_error(f"Unknown brokerage: {rebuild_target}")
                log_info(f"Available brokerages: {', '.join([b['name'] for b in BROKERAGES])}")
                sys.exit(1)
            log_info(f"Rebuilding brokerage: {rebuild_target} (forced)")

            # Include dependencies
            all_to_rebuild = []
            for brokerage in brokerages_to_rebuild:
                # Add dependencies first
                if "dependencies" in brokerage:
                    for dep_name in brokerage["dependencies"]:
                        dep = next((b for b in BROKERAGES if b["name"] == dep_name), None)
                        if dep and dep not in all_to_rebuild:
                            all_to_rebuild.append(dep)
                # Add the brokerage itself
                if brokerage not in all_to_rebuild:
                    all_to_rebuild.append(brokerage)
            brokerages_to_rebuild = all_to_rebuild
    else:
        brokerages_to_rebuild = None
        # Step 2: Build LEAN (only if not rebuilding specific brokerage)
        log_info("Step 1: Building LEAN project...")
        if not build_lean():
            log_error("Failed to build LEAN project")
            sys.exit(1)
        print()

    # Track built brokerages
    built_brokerages = set()

    # Step 3-5: Process each brokerage
    brokerages_to_process = brokerages_to_rebuild if brokerages_to_rebuild else BROKERAGES

    for i, brokerage in enumerate(brokerages_to_process):
        print(f"{'='*60}")
        print(f"  Brokerage {i+1}/{len(brokerages_to_process)}: {brokerage['name']}")
        print(f"{'='*60}\n")

        force_rebuild = brokerages_to_rebuild and brokerage in brokerages_to_rebuild

        # Check and handle dependencies first
        if "dependencies" in brokerage:
            log_info(f"Checking dependencies: {', '.join(brokerage['dependencies'])}")
            for dep_name in brokerage["dependencies"]:
                if dep_name not in built_brokerages:
                    # Special handling for IBAutomater - download from NuGet instead of building
                    if dep_name == "IBAutomater":
                        log_info("Installing IBAutomater from NuGet...")
                        if not download_ibautomater(force=force_rebuild):
                            log_error("Failed to download IBAutomater")
                            continue
                        built_brokerages.add(dep_name)
                        log_success("IBAutomater installed successfully")
                    else:
                        # Standard dependency - clone and build
                        dep = next((b for b in BROKERAGES if b["name"] == dep_name), None)
                        if dep:
                            log_info(f"Building dependency: {dep_name}")
                            if not clone_repo(dep["repo_url"], dep["target_dir"]):
                                log_error(f"Failed to clone dependency {dep_name}")
                                continue
                            if not build_brokerage(dep["target_dir"], dep["solution_file"], force=force_rebuild):
                                log_error(f"Failed to build dependency {dep_name}")
                                continue
                            if not copy_dlls(dep["target_dir"], dep["dlls"], force=force_rebuild):
                                log_error(f"Failed to copy DLLs for dependency {dep_name}")
                                continue
                            built_brokerages.add(dep_name)
                            log_success(f"Dependency {dep_name} built successfully")
            print()

        # Step 2: Clone repository (skip if rebuilding)
        if not force_rebuild:
            log_info("Step 2: Cloning repository...")
            if not clone_repo(brokerage["repo_url"], brokerage["target_dir"]):
                log_error(f"Failed to clone {brokerage['name']}")
                continue
            print()

        # Step 3: Build brokerage
        log_info("Step 3: Building brokerage...")
        if not build_brokerage(brokerage["target_dir"], brokerage["solution_file"], force=force_rebuild):
            log_error(f"Failed to build {brokerage['name']}")
            continue
        print()

        # Step 4: Copy DLLs
        log_info("Step 4: Copying DLLs...")
        if not copy_dlls(brokerage["target_dir"], brokerage["dlls"], force=force_rebuild):
            log_error(f"Failed to copy DLLs for {brokerage['name']}")
            continue
        print()

        built_brokerages.add(brokerage["name"])

    print("="*60)
    if rebuild_target:
        log_success("Rebuild complete!")
    else:
        log_success("Build process complete!")
    print("="*60 + "\n")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="LEAN Brokerage Build Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python build_brokerage.py                              # Build all (skip if built)
  python build_brokerage.py --rebuild Kraken             # Rebuild Kraken only
  python build_brokerage.py --rebuild InteractiveBrokers # Rebuild IB (includes IBAutomater)
  python build_brokerage.py --rebuild all                # Rebuild all

Available Brokerages:
  - Kraken
  - InteractiveBrokers (automatically downloads IBAutomater from NuGet)
        """
    )

    parser.add_argument(
        "--rebuild",
        type=str,
        metavar="BROKERAGE",
        help="Rebuild specific brokerage (or 'all'). Forces recompile and copy."
    )

    args = parser.parse_args()

    try:
        build_all_brokerages(rebuild_target=args.rebuild)
    except KeyboardInterrupt:
        print("\n")
        log_error("Build interrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    main()
