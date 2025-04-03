#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "boto3",
#     "pyyaml",
#     "click",
#     "yaspin",
# ]
# ///
"""
test-distribution-locally.py

A utility script to build and test custom OpenTelemetry Collector distributions locally.
This script emulates the refactored GitHub workflow process:
1. Clones upstream repo temporarily.
2. Determines upstream version using 'make set-otelcol-version'.
3. Determines build tags using distribution_utils directly.
4. Calls 'build_extension_layer.py' with version and tags in env.
5. Optionally calls 'lambda_layer_publisher.py' with necessary info.

Features:
- External commands (git, make) use spinners and only show output on failure
- Python scripts show full output for debugging
- Environment variables from child processes are captured using GitHub Actions simulation
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
import re
import shutil  # Needed for cleanup
import click

# Import distribution utilities from the scripts directory
from scripts.otel_layer_utils.distribution_utils import (
    load_distributions,
    DistributionError,
    resolve_build_tags,
)
from scripts.otel_layer_utils.ui_utils import (
    header,
    subheader,
    status,
    info,
    detail,
    success,
    error,
    warning,
    spinner,
    format_table,
    StepTracker,
    set_verbose_mode,
    debug,
)


def is_python_script(cmd):
    """Check if the command is a Python script."""
    if len(cmd) < 2:
        return False
    # Check if the command is running python and a script
    return (cmd[0].endswith("python") or cmd[0].endswith("python3")) and cmd[
        1
    ].endswith(".py")


def run_command(
    cmd,
    cwd=None,
    env=None,
    check=True,
    capture_output=False,
    capture_github_env=False,
    use_spinner=False,
):
    """Run a shell command and print its output. Optionally capture GitHub environment variables.

    Args:
        cmd: Command to run as a list of strings
        cwd: Working directory for the command
        env: Environment variables to add
        check: Whether to raise an exception on non-zero exit
        capture_output: Whether to capture stdout/stderr instead of streaming
        capture_github_env: Whether to capture GitHub environment variables using temp files
        use_spinner: Use a spinner instead of showing output (for external commands)
    """
    # Determine command type for presentation
    is_python = is_python_script(cmd)
    display_cmd = " ".join(cmd)

    # Always show what command we're running
    status("Command", display_cmd)
    if cwd:
        detail("Directory", cwd)

    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    # Create temporary files for GitHub environment variables if requested
    github_env_file = None
    github_output_file = None
    if capture_github_env:
        # Create a temporary file to capture GitHub environment variables
        github_env_file = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        github_env_path = github_env_file.name
        github_env_file.close()  # Close it so the subprocess can write to it

        # Create a temporary file for GitHub outputs (newer GitHub Actions approach)
        github_output_file = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        github_output_path = github_output_file.name
        github_output_file.close()  # Close it so the subprocess can write to it

        # Set GitHub environment file paths
        full_env.update(
            {"GITHUB_ENV": github_env_path, "GITHUB_OUTPUT": github_output_path}
        )

    # Always capture output for spinner mode or if explicitly requested
    should_capture = capture_output or use_spinner

    # Define a function to run the command so we can use our spinner utility
    def execute_command():
        return subprocess.run(
            cmd,
            cwd=cwd,
            env=full_env,
            text=True,
            check=False,  # Don't check here, we'll handle errors
            capture_output=should_capture,
        )

    # Start spinner if requested (external commands only)
    if use_spinner and not is_python:
        spinner_text = f"Running {cmd[0].split('/')[-1]}"
        process = spinner(spinner_text, execute_command)
    else:
        # If not capturing output and not using spinner, just add a light separator
        if not should_capture:
            info("Output", "")
        process = execute_command()

    # If command failed and we used a spinner, show the output
    failed = process.returncode != 0
    if failed and use_spinner:
        warning("Command failed! Output:", "")
        if process.stdout and len(process.stdout.strip()) > 0:
            click.echo(process.stdout)

        if process.stderr and len(process.stderr.strip()) > 0:
            error("Error", process.stderr)
    # If we captured output (and either didn't use spinner or command failed)
    elif should_capture and (not use_spinner or failed):
        if process.stdout and (failed or len(process.stdout.strip()) > 0):
            click.echo(process.stdout)

        if process.stderr and len(process.stderr.strip()) > 0:
            error("Error", process.stderr)

    # If command succeeded and we used a spinner, show success message
    if not failed and use_spinner:
        success(f"{cmd[0].split('/')[-1]} completed successfully")

    # Manual check if needed
    if check and failed:
        if not should_capture:  # Avoid double printing error
            error("Command failed", f"Exit code {process.returncode}")
        raise subprocess.CalledProcessError(
            process.returncode,
            cmd,
            output=process.stdout if should_capture else None,
            stderr=process.stderr if should_capture else None,
        )

    # Parse GitHub env variables if requested
    github_env_vars = {}
    if capture_github_env:
        # Read from both GITHUB_ENV and GITHUB_OUTPUT files
        for file_path, file_type in [
            (github_env_path, "GITHUB_ENV"),
            (github_output_path, "GITHUB_OUTPUT"),
        ]:
            try:
                if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                    with open(file_path, "r") as f:
                        for line in f:
                            line = line.strip()
                            if line and "=" in line:
                                key, value = line.split("=", 1)
                                github_env_vars[key] = value
                                if value.strip():  # Only log non-empty values
                                    info("Captured", f"{file_type}: {key}={value}")
            except Exception as e:
                warning(f"Error parsing {file_type} file: {e}")
            finally:
                # Clean up the temporary file
                try:
                    if os.path.exists(file_path):
                        os.unlink(file_path)
                except Exception as e:
                    warning(f"Error removing temporary {file_type} file: {e}")

    if capture_github_env:
        return process, github_env_vars
    else:
        return process


def check_aws_credentials():
    """Check if AWS credentials are configured correctly."""
    try:
        # Import boto3 (should be available as it's in the script requirements)
        import boto3

        # Create a boto3 STS client
        sts_client = boto3.client("sts")

        # Call get_caller_identity directly using boto3
        response = sts_client.get_caller_identity()

        # Extract account ID from response
        account_id = response.get("Account")
        if account_id:
            success("AWS credentials are configured", f"Account: {account_id}")
            return True
        else:
            warning(
                "AWS credentials are configured but account ID couldn't be determined."
            )
            return False

    except ImportError:
        error("boto3 is not installed", "Please install it: pip install boto3")
        return False
    except Exception as e:
        error("AWS credentials are not configured correctly", str(e))
        return False


def get_aws_region():
    """Get the current AWS region from boto3 session."""
    try:
        import boto3

        # Get the region from the default session
        session = boto3.session.Session()
        region = session.region_name

        if region:
            return region
        else:
            # Don't fallback, require configuration
            error("Could not determine AWS region from boto3 session.")
            detail(
                "Hint", "Configure region via AWS_REGION env var or 'aws configure'."
            )
            sys.exit(1)
    except Exception as e:
        error("Error getting AWS region", str(e))
        sys.exit(1)


# Load distribution choices strictly from config - Fail Fast
header("Loading distributions")
DISTRIBUTION_CHOICES = []
_distributions_data = {}  # Initialize empty dict
try:
    _repo_root_for_choices = Path().cwd()
    _dist_yaml_path = _repo_root_for_choices / "config" / "distributions.yaml"
    # Attempt to load distributions data
    _distributions_data = load_distributions(_dist_yaml_path)
    # If successful, populate choices
    DISTRIBUTION_CHOICES = sorted(list(_distributions_data.keys()))
    success("Loaded distribution choices", ", ".join(DISTRIBUTION_CHOICES))
    # Fail fast if loaded data is empty or invalid
    if not DISTRIBUTION_CHOICES or not _distributions_data:
        raise ValueError(
            "Distributions config file loaded but appears empty or invalid."
        )

except ImportError:
    error(
        "Fatal Error: Could not import distribution_utils",
        "Check project structure and dependencies.",
    )
    sys.exit(1)
except FileNotFoundError:
    error(f"Fatal Error: Distributions config file not found at {_dist_yaml_path}")
    sys.exit(1)
except Exception as e:
    # Catch other errors during loading/parsing (e.g., YAMLError, ValueError)
    error(
        f"Fatal Error: Could not load distributions from config file {_dist_yaml_path}",
        str(e),
    )
    sys.exit(1)
# No need for the separate check below, the try/except handles failures


ARCHITECTURE_CHOICES = ["amd64", "arm64"]


@click.command(
    context_settings=dict(
        help_option_names=["-h", "--help"],
        max_content_width=120,  # Wider help text
    )
)
@click.option(
    "--distribution",
    "-d",
    default="default",  # Keep default for CLI convenience, but resolution must succeed
    type=click.Choice(DISTRIBUTION_CHOICES, case_sensitive=False),
    help="The distribution to build.",
)
@click.option(
    "--architecture",
    "-a",
    default="amd64",
    type=click.Choice(ARCHITECTURE_CHOICES, case_sensitive=False),
    help="The architecture to build for.",
)
@click.option(
    "--upstream-repo",
    "-r",
    default="open-telemetry/opentelemetry-lambda",
    help="Upstream repository to use.",
)
@click.option(
    "--upstream-ref",
    "-b",
    default="main",
    help="Upstream Git reference (branch, tag, SHA).",
)
@click.option(
    "--layer-name",
    "-l",
    default="otel-ext-layer",
    help="Base name for the Lambda layer.",
)
@click.option(
    "--runtimes",
    default="nodejs18.x nodejs20.x java17 python3.9 python3.10",
    help="Space-delimited list of compatible runtimes.",
)
@click.option(
    "--skip-publish",
    is_flag=True,
    help="Skip the publishing step and only build the layer.",
)
@click.option("--verbose", "-v", is_flag=True, help="Show more detailed output.")
@click.option("--public", is_flag=True, help="Make the layer publicly accessible.")
@click.option(
    "--keep-temp",
    is_flag=True,
    help="Keep temporary directories (e.g., upstream clone).",
)
def main(
    distribution,
    architecture,
    upstream_repo,
    upstream_ref,
    layer_name,
    runtimes,
    skip_publish,
    verbose,
    public,
    keep_temp,
):
    """Build and test custom OTel Collector distributions locally."""

    # Enable verbose mode if requested
    set_verbose_mode(verbose)

    # Set up paths
    repo_root = Path(__file__).parent.parent.resolve()
    build_dir = repo_root / "build"
    build_dir.mkdir(exist_ok=True)
    scripts_dir = repo_root / "tools" / "scripts"  # Scripts are in tools/scripts

    temp_upstream_dir = None  # Initialize
    upstream_version = None
    build_tags_string = None

    # Show a summary of selected build options as a table
    headers = ["Option", "Value"]
    rows = [
        ["Distribution", distribution],
        ["Architecture", architecture],
        ["Upstream", f"{upstream_repo}@{upstream_ref}"],
        ["Layer Name", layer_name],
        ["Runtimes", runtimes],
        ["Publish", "No" if skip_publish else "Yes"],
        ["Public Access", "Yes" if public else "No"],
    ]
    format_table(headers, rows, title="Build Configuration")

    # Setup a step tracker for the main build process
    build_steps = [
        "Clone upstream repository",
        "Determine upstream version",
        "Resolve build tags",
        "Build extension layer",
        "Publish layer (if enabled)",
    ]
    tracker = StepTracker(build_steps, title="Build Process Steps")

    try:
        # --- Step 0: Prepare Environment (Corresponds to 'prepare-environment' job) ---
        header("Prepare environment")

        # --- Sub-step: Clone Upstream Repo ---
        subheader("Cloning repository")
        tracker.start_step(0)  # Start the clone step
        temp_upstream_dir = tempfile.mkdtemp(prefix="otel-upstream-")
        temp_upstream_path = Path(temp_upstream_dir)
        status("Target repo", f"{upstream_repo}@{upstream_ref}")
        info("Temp directory", temp_upstream_dir)
        repo_url = f"https://github.com/{upstream_repo}.git"
        run_command(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                upstream_ref,
                repo_url,
                str(temp_upstream_path),
            ],
            use_spinner=True,
        )
        tracker.complete_step(0, "Repository cloned successfully")

        # Determine Version
        upstream_collector_dir = temp_upstream_path / "collector"
        upstream_makefile = upstream_collector_dir / "Makefile"
        upstream_version_file = upstream_collector_dir / "VERSION"
        upstream_version = None

        if not upstream_makefile.exists():
            error("Makefile not found", f"{upstream_makefile}")
            detail("Detail", "Cannot determine version via make")
            tracker.fail_step(1, "Makefile not found")
            sys.exit(1)

        subheader("Determining version")
        tracker.start_step(1)
        debug(f"Looking for Makefile at {upstream_makefile}")
        run_command(
            ["make", "set-otelcol-version"],
            cwd=str(upstream_collector_dir),
            use_spinner=True,
        )

        if not upstream_version_file.is_file():
            error("VERSION file not created", f"{upstream_version_file}")
            tracker.fail_step(1, "VERSION file not created")
            sys.exit(1)

        with open(upstream_version_file, "r") as vf:
            upstream_version = vf.read().strip()

        if not upstream_version:
            error("VERSION file is empty", f"{upstream_version_file}")
            tracker.fail_step(1, "VERSION file is empty")
            sys.exit(1)
        success("Determined Upstream Version", upstream_version)
        tracker.complete_step(1, f"Version: {upstream_version}")

        # --- Sub-step: Determine Build Tags String (Locally) ---
        subheader("Determining build tags")
        tracker.start_step(2)
        build_tags_string = ""
        try:
            # _distributions_data was loaded above when setting choices
            if not _distributions_data:  # Check if loading failed earlier
                error("Cannot resolve build tags", "Distributions data failed to load")
                tracker.fail_step(2, "Distributions data failed to load")
                sys.exit(1)
            buildtags_list = resolve_build_tags(distribution, _distributions_data)
            build_tags_string = ",".join(filter(None, buildtags_list))
            success("Determined build tags", build_tags_string)
            tracker.complete_step(2, f"Tags: {build_tags_string}")
        except DistributionError as e:
            error(
                f"Error resolving build tags for distribution '{distribution}'", str(e)
            )
            tracker.fail_step(2, str(e))
            sys.exit(1)
        except Exception as e:
            error("An unexpected error occurred resolving build tags", str(e))
            tracker.fail_step(2, str(e))
            sys.exit(1)

        # --- Step 1: Build Collector Layer (Corresponds to 'build-layer' job) ---
        header(f"Build layer ({architecture})")

        build_script = scripts_dir / "build_extension_layer.py"
        subheader("Running build script")
        build_cmd = [
            sys.executable,
            str(build_script),
            "--upstream-repo",
            upstream_repo,
            "--upstream-ref",
            upstream_ref,
            # Distribution is mainly for logging now, tags drive the build
            "--distribution",
            distribution,
            "--arch",
            architecture,
            "--output-dir",
            str(build_dir),
            # Pass version and tags as command line arguments
            "--upstream-version",
            upstream_version,
            "--build-tags",
            build_tags_string,
        ]

        # Run build script (don't capture output by default, let it stream)
        run_command(build_cmd)

        layer_file = build_dir / f"collector-{architecture}-{distribution}.zip"
        if not layer_file.exists():
            error("Expected layer file not found after build", f"{layer_file}")
            sys.exit(1)

        success("Build successful", f"{layer_file}")

        if skip_publish:
            info("Skipping publish step", "Publishing not requested")
            return

        # Check AWS credentials before publishing
        # --- Step 2: Publish Layer (Corresponds to 'release-layer' job using reusable workflow) ---
        header(f"Publish layer ({architecture})")

        # --- Sub-step: Check AWS Credentials ---
        subheader("Checking AWS credentials")
        if not check_aws_credentials():
            error("AWS credentials check failed", "Skipping publish step")
            detail("Hint", "Run 'aws configure' or set AWS environment variables")
            sys.exit(1)

        # --- Sub-step: Get AWS Region ---
        subheader("Determining AWS region")
        region = get_aws_region()
        success("Target AWS Region", region)

        # --- Sub-step: Prepare Publish Environment ---
        subheader("Preparing for publish")

        # Print debug info if verbose
        if verbose:
            info("Debug info", "Publishing with parameters:")
            detail("Layer name", layer_name)
            detail("Artifact", str(layer_file))
            detail("Region", region)
            detail("Architecture", architecture)
            detail("Runtimes", runtimes)
            detail("Release group", "local")
            detail("Distribution", distribution)
            detail("Collector version", upstream_version)
            detail("Build tags", build_tags_string)
            detail("Make public", str(public).lower())

        # --- Sub-step: Execute Publish Script ---
        subheader("Publishing layer")
        publisher_script = scripts_dir / "lambda_layer_publisher.py"

        # Build command with all arguments including build-tags
        publish_cmd = [
            sys.executable,
            str(publisher_script),
            "--layer-name",
            layer_name,
            "--artifact-name",
            str(layer_file),
            "--region",
            region,
            "--architecture",
            architecture,
            "--runtimes",
            runtimes,
            "--release-group",
            "local",  # Always use 'local' for testing
            "--distribution",
            distribution,
            "--collector-version",
            upstream_version,
            "--make-public",
            str(public).lower(),
            "--build-tags",
            build_tags_string,
        ]

        publish_result, github_env = run_command(
            publish_cmd,
            capture_github_env=True,
            capture_output=True,  # Capture output to parse ARN if needed
        )

        # Display layer information from GitHub environment variables or stdout
        layer_arn = github_env.get("layer_arn")
        if not layer_arn:
            # Fallback: Try to extract from stdout
            arn_match = re.search(
                r"Published Layer ARN: (arn:aws:lambda:[^:]+:[^:]+:layer:[^:]+:[0-9]+)",
                publish_result.stdout,
            )
            if arn_match:
                layer_arn = arn_match.group(1)

        if layer_arn:
            subheader("Layer published")
            status("Layer ARN", layer_arn)
        else:
            warning("Publish step completed, but could not determine final Layer ARN")

        success(
            f"Published {distribution} distribution to region {region} as a 'local' release"
        )
        info(
            "Next steps",
            "You can now test this layer by attaching it to a Lambda function",
        )

    except subprocess.CalledProcessError:
        # Error message should have been printed by run_command
        error("An error occurred during execution")
        sys.exit(1)
    except Exception as e:
        error("An unexpected error occurred", str(e))
        sys.exit(1)
    finally:  # Correct indentation relative to try
        # Cleanup temporary upstream directory (Correct indentation relative to finally)
        if temp_upstream_dir and Path(temp_upstream_dir).exists():
            if keep_temp:
                info("Keeping temporary upstream clone", temp_upstream_dir)
            else:
                subheader("Cleaning up")
                status("Removing temporary upstream clone", temp_upstream_dir)
                shutil.rmtree(temp_upstream_dir)


if __name__ == "__main__":
    main()
