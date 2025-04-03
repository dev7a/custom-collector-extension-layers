#!/usr/bin/env python3
"""
build_extension_layer.py

Builds a custom OpenTelemetry Collector Lambda layer by cloning an upstream
repository, overlaying custom components, managing dependencies based on
configuration, and building the layer package. Version and build tags are
expected to be passed via environment variables from the GitHub workflow.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import yaml  # Import yaml for dependency config loading
import click

# Assuming otel_layer_utils is now under scripts/
from otel_layer_utils.distribution_utils import resolve_build_tags, DistributionError
from otel_layer_utils.ui_utils import (
    header,
    subheader,
    status,
    info,
    detail,
    success,
    error,
    warning,
    spinner,
    property_list,
)

# Default values (used if not overridden by args)
DEFAULT_UPSTREAM_REPO = "open-telemetry/opentelemetry-lambda"
DEFAULT_UPSTREAM_REF = "main"
DEFAULT_DISTRIBUTION = "default"
DEFAULT_ARCHITECTURE = "amd64"
# REMOVED: DEFAULT_FALLBACK_VERSION


def run_command(
    cmd: list, cwd: str = None, env: dict = None, check: bool = True
) -> subprocess.CompletedProcess:
    """Run a shell command and handle potential errors."""
    command_str = " ".join(cmd)

    # Display the command and directory
    status("Command", command_str)
    if cwd:
        detail("Directory", cwd)

    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    # Add a light separator for output
    info("Output", "")

    # Define the function that executes the command
    def execute_command():
        return subprocess.run(
            cmd, cwd=cwd, env=full_env, capture_output=True, text=True
        )

    # Run the command (either directly or with spinner)
    process = execute_command()

    if check and process.returncode != 0:
        error("Command failed", f"Exit code {process.returncode}")

        if process.stderr:
            error("Error detail", process.stderr)

        if process.stdout:
            click.echo(process.stdout)

        raise subprocess.CalledProcessError(
            process.returncode, cmd, output=process.stdout, stderr=process.stderr
        )
    elif process.returncode != 0:
        warning(
            f"Command returned non-zero exit code {process.returncode}",
            "check=False, continuing execution",
        )

        if process.stderr:
            error("Error", process.stderr)
    else:
        # Command succeeded
        success("Command completed successfully")

    return process


def load_component_dependencies(yaml_path: Path) -> dict:
    """Load component dependency mappings from YAML file."""
    if not yaml_path.is_file():
        warning(
            f"Component dependency file not found at {yaml_path}",
            "Cannot add dependencies",
        )
        return {}  # Return empty dict if file doesn't exist

    try:
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)
            if (
                not data
                or "dependencies" not in data
                or not isinstance(data["dependencies"], dict)
            ):
                warning(
                    f"Invalid format in {yaml_path}",
                    "Expected a 'dependencies' dictionary",
                )
                return {}

            success("Loaded dependency mappings", f"from {yaml_path}")
            return data["dependencies"]
    except yaml.YAMLError as e:
        error("Error parsing component dependency YAML file", str(e))
        return {}  # Return empty on error
    except Exception as e:
        error("Unexpected error loading YAML file", str(e))
        return {}


# Renamed for clarity, assumes distributions_data is loaded and passed in
def get_build_tags_list(distribution: str, distributions_data: dict) -> list[str]:
    """Determine the Go build tags list for a named distribution."""
    if not distributions_data:
        error(
            "Distributions data not loaded", f"Cannot resolve tags for '{distribution}'"
        )
        raise DistributionError("Distributions configuration not available.")
    try:
        buildtags_list = resolve_build_tags(distribution, distributions_data)
        return buildtags_list  # Return the list directly
    except DistributionError as e:
        error("Error resolving build tags", f"Distribution '{distribution}': {e}")
        raise  # Re-raise the exception


def add_dependencies(
    collector_dir: Path,
    active_build_tags: list[str],
    dependency_mappings: dict,
    upstream_version: str,
):
    """Add Go dependencies based on active build tags, mappings, and a provided upstream version."""
    if not dependency_mappings:
        info("No dependency mappings loaded", "Skipping dependency addition")
        return
    if not upstream_version:
        # This case should ideally be caught in main() before calling this function
        error("Critical Error", "Upstream version is missing in add_dependencies")
        sys.exit(1)

    modules_to_get = set()  # Use a set to avoid duplicate 'go get' calls

    # Check for hierarchical tag resolution
    has_global_all = "lambdacomponents.all" in active_build_tags

    # Find all subgroup "all" tags like "lambdacomponents.exporter.all"
    all_subgroup_tags = [
        tag
        for tag in active_build_tags
        if tag.endswith(".all") and tag != "lambdacomponents.all"
    ]
    all_subgroup_prefixes = [tag.rsplit(".", 1)[0] + "." for tag in all_subgroup_tags]

    # Handle logging for hierarchical resolution
    if has_global_all:
        status(
            "Using hierarchical resolution",
            "Including all dependencies for 'lambdacomponents.all'",
        )
    if all_subgroup_prefixes:
        status(
            "Using pattern matching",
            f"For subgroup tags: {', '.join(all_subgroup_tags)}",
        )

    # Determine which modules are needed based on active tags
    for dep_tag, modules in dependency_mappings.items():
        should_include = False

        # Direct match with active tag
        if dep_tag in active_build_tags:
            should_include = True
            detail("Including dependency", f"Direct match: {dep_tag}")

        # Global "all" tag includes everything
        elif has_global_all:
            should_include = True
            detail("Including dependency", f"Via global 'all' tag: {dep_tag}")

        # Subgroup "all" tag includes components in that group
        else:
            for prefix in all_subgroup_prefixes:
                if dep_tag.startswith(prefix):
                    should_include = True
                    detail(
                        "Including dependency",
                        f"Via subgroup: {prefix[:-1]} matches {dep_tag}",
                    )
                    break

        # Add dependencies if any matching condition was met
        if should_include:
            if isinstance(modules, list):
                modules_to_get.update(modules)
            elif isinstance(modules, str):
                modules_to_get.add(modules)
            else:
                warning(
                    f"Invalid format for tag '{dep_tag}' in dependency config",
                    "Expected list or string",
                )

    if not modules_to_get:
        info("No custom component dependencies required", "For this distribution")
        return

    subheader("Adding dependencies")
    status("Using version", upstream_version)

    try:
        # Ensure version starts with 'v' if it doesn't already (go get expects it)
        version_tag = (
            upstream_version
            if upstream_version.startswith("v")
            else f"v{upstream_version}"
        )

        # First, check the go.mod file to see what version of the OpenTelemetry SDK it's using
        try:
            with open(str(collector_dir / "go.mod"), "r") as f:
                f.read()
            status("Analyzing", "go.mod file for dependency compatibility")
        except Exception as e:
            warning("Could not read go.mod file", str(e))

        # Run 'go get' for each required module
        added_any = False
        for module_path in modules_to_get:
            dependency = f"{module_path}@{version_tag}"
            status("Adding", dependency)

            try:
                # First try with the exact version for consistency
                run_command(["go", "get", dependency], cwd=str(collector_dir))
                added_any = True
                success(f"Successfully added dependency {dependency}")
            except subprocess.CalledProcessError as e:
                warning(
                    f"Failed to get dependency with exact version: {dependency}",
                    f"Error: {e}",
                )
                warning("Attempting fallback strategies...", "")

                try:
                    # Try with just the module path without version constraint
                    fallback_dep = module_path
                    status(
                        "Attempting fallback",
                        f"go get {fallback_dep} (without version)",
                    )
                    run_command(["go", "get", fallback_dep], cwd=str(collector_dir))
                    added_any = True
                    success(
                        f"Successfully added dependency {fallback_dep} without version constraint"
                    )
                except subprocess.CalledProcessError as e2:
                    error(
                        f"All attempts to add dependency {module_path} failed",
                        f"Last error: {e2}",
                    )
                    # Continue with other dependencies even if this one failed

        # Run 'go mod tidy' once after attempting all 'go get' commands if any were added
        if added_any:
            status("Running", "go mod tidy to clean up dependencies")
            try:
                run_command(["go", "mod", "tidy"], cwd=str(collector_dir))
                success("Dependency management completed")
            except subprocess.CalledProcessError as e:
                error(
                    "Failed running 'go mod tidy'",
                    e.stderr if hasattr(e, "stderr") else str(e),
                )
                # Try to proceed anyway - the build may still work
        else:
            warning("No new dependencies were successfully added")
            detail("Action", "Skipping 'go mod tidy'")

    except subprocess.CalledProcessError as e:
        # Catch errors from go mod tidy
        error("Failed during dependency management", "'go mod tidy'")
        detail("Detail", str(e))
        detail("Output", e.stdout if hasattr(e, "stdout") else "")
        detail("Error", e.stderr if hasattr(e, "stderr") else "")
        sys.exit(1)
    except Exception as e:
        error("An unexpected error occurred adding dependencies")
        detail("Detail", str(e))
        sys.exit(1)


@click.command()
@click.option(
    "-r",
    "--upstream-repo",
    default=DEFAULT_UPSTREAM_REPO,
    help=f"Upstream repository (default: {DEFAULT_UPSTREAM_REPO})",
)
@click.option(
    "-b",
    "--upstream-ref",
    default=DEFAULT_UPSTREAM_REF,
    help=f"Upstream Git reference (branch, tag, SHA) (default: {DEFAULT_UPSTREAM_REF})",
)
@click.option(
    "-d",
    "--distribution",
    default=DEFAULT_DISTRIBUTION,
    help="Distribution name (used for logging)",
)
@click.option(
    "-a",
    "--arch",
    default=DEFAULT_ARCHITECTURE,
    type=click.Choice(["amd64", "arm64"]),
    help=f"Architecture (default: {DEFAULT_ARCHITECTURE})",
)
@click.option(
    "-o",
    "--output-dir",
    help="Output directory for built layer (default: current directory)",
)
@click.option(
    "-k",
    "--keep-temp",
    is_flag=True,
    help="Keep temporary build directory",
)
def main(upstream_repo, upstream_ref, distribution, arch, output_dir, keep_temp):
    """Build Custom OpenTelemetry Collector Lambda Layer."""

    # --- Get Version and Build Tags from Environment (passed by workflow) ---
    upstream_version = os.environ.get("UPSTREAM_VERSION")
    build_tags_string = os.environ.get("BUILD_TAGS_STRING")  # Comma-separated string

    # CRITICAL: Fail if version is not provided by the workflow
    if not upstream_version:
        error(
            "UPSTREAM_VERSION environment variable not set",
            "Cannot determine dependency versions",
        )
        detail("Info", "This variable should be set by the calling GitHub workflow")
        sys.exit(1)

    # Build tags string is needed for the 'make package' env var.
    # The list of tags is needed for dependency resolution.
    # Fail if build tags are not provided (unless distribution is 'default' which might have none)
    active_build_tags = []
    if build_tags_string is not None:  # Allow empty string for 'default' potentially
        active_build_tags = [
            tag for tag in build_tags_string.split(",") if tag
        ]  # Handle empty tags from split
    # We will rely on the workflow passing the correct tags; local resolution is removed for simplicity

    # --- Setup Paths and Load Configs ---
    output_dir = Path(output_dir).resolve() if output_dir else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    custom_repo_path = Path.cwd()
    component_dir = custom_repo_path / "components"
    config_dir = custom_repo_path / "config"
    dependency_yaml_path = config_dir / "component_dependencies.yaml"

    # Load component dependencies config
    dependency_mappings = load_component_dependencies(dependency_yaml_path)

    # Display build configuration using property list
    header("Build configuration")

    # Group important configuration properties
    build_props = {
        "Upstream Repository": upstream_repo,
        "Upstream Ref": upstream_ref,
        "Distribution": distribution,
        "Architecture": arch,
        "Upstream Version": upstream_version,
        "Build Tags": build_tags_string or "[none]",
        "Output Directory": str(output_dir),
    }

    # Less important properties with dimmer styling
    other_props = {
        "Keep Temp Directory": str(keep_temp),
        "Custom Component Dir": str(component_dir),
        "Dependency Config": str(dependency_yaml_path),
    }

    # Display configuration
    property_list(build_props)
    property_list(other_props)

    # --- Build Process ---
    temp_dir = tempfile.mkdtemp()
    temp_dir_path = Path(temp_dir)
    upstream_dir = temp_dir_path / "upstream"

    try:
        info("Temporary Directory", temp_dir)

        # Step 1: Clone upstream repository
        subheader("Clone upstream repository")

        repo_url = f"https://github.com/{upstream_repo}.git"

        def clone_repo():
            return subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    upstream_ref,
                    repo_url,
                    str(upstream_dir),
                ],
                capture_output=True,
                text=True,
            )

        clone_result = spinner("Cloning repository", clone_repo)
        if clone_result.returncode != 0:
            error("Failed to clone repository", clone_result.stderr)
            sys.exit(1)

        success("Repository cloned successfully")

        # Step 2: Copy custom components to the upstream directory
        subheader("Overlay custom components")

        if component_dir.is_dir():
            # Use shutil.copytree for overlay
            shutil.copytree(component_dir, upstream_dir, dirs_exist_ok=True)
            success("Copied components", f"From {component_dir} to {upstream_dir}")
        else:
            warning(
                f"Custom components directory not found at {component_dir}",
                "Proceeding without overlay",
            )

        # Step 3: Add dependencies for custom components (if needed)
        subheader("Add dependencies")

        collector_dir = upstream_dir / "collector"
        if not collector_dir.is_dir():
            error("Collector directory not found", f"In upstream repo: {collector_dir}")
            sys.exit(1)

        # Pass the list of active tags, mappings, and the determined version
        add_dependencies(
            collector_dir, active_build_tags, dependency_mappings, upstream_version
        )

        # Step 4: Build the collector using 'make package'
        subheader("Build collector")

        build_env = {"GOARCH": arch}
        if build_tags_string:  # Use the comma-separated string for the env var
            build_env["BUILDTAGS"] = build_tags_string

        makefile_path = collector_dir / "Makefile"
        if not makefile_path.exists():
            error("Makefile not found", f"At {makefile_path}")
            detail("Detail", "Cannot build using make")
            sys.exit(1)

        def run_make_package():
            return subprocess.run(
                ["make", "package"],
                cwd=str(collector_dir),
                env={**os.environ.copy(), **build_env},
                capture_output=True,
                text=True,
            )

        build_result = spinner("Running make package", run_make_package)
        if build_result.returncode != 0:
            error("Build failed", build_result.stderr)
            if build_result.stdout:
                click.echo(build_result.stdout)
            sys.exit(1)

        success("Build successful")

        # Step 5: Rename and Copy the built layer
        subheader("Prepare output")

        build_output_dir = collector_dir / "build"
        original_filename = f"opentelemetry-collector-layer-{arch}.zip"

        # Always include distribution name in the filename for consistency
        new_filename = f"collector-{arch}-{distribution}.zip"

        original_build_file = build_output_dir / original_filename
        renamed_build_file = (
            build_output_dir / new_filename
        )  # Path for renamed file within build dir

        status("Checking build output", str(original_build_file))
        if not original_build_file.is_file():
            error("Build file not found", f"{original_build_file}")
            detail("Action", "Checking build directory contents")
            try:
                dir_contents = os.listdir(build_output_dir)
                for item in dir_contents:
                    detail("File", item)
            except Exception as ls_err:
                error("Could not list build directory contents", str(ls_err))
            sys.exit(1)

        # Rename the file produced by make
        status("Renaming file", f"{original_filename} to {new_filename}")
        try:
            original_build_file.rename(renamed_build_file)
            success("File renamed successfully")
        except OSError as e:
            error("Error renaming file")
            detail("Detail", str(e))
            sys.exit(1)

        # Copy the RENAMED file to the final output directory
        target_file = output_dir / new_filename  # Final destination uses the new name
        status("Copying layer", f"To {target_file}")
        shutil.copy(renamed_build_file, target_file)

        header("Build successful")
        status("Layer available at", str(target_file))

    except subprocess.CalledProcessError as e:
        header("Build failed")
        error(str(e))
        sys.exit(1)
    except Exception as e:
        header("Build failed")
        error("An unexpected error occurred")
        detail("Detail", str(e))
        sys.exit(1)
    finally:
        # Cleanup temporary directory
        if not keep_temp:
            subheader("Cleaning up")
            status("Removing temp dir", temp_dir)
            shutil.rmtree(temp_dir)
        else:
            info("Keeping temporary directory", temp_dir)


if __name__ == "__main__":
    main()
