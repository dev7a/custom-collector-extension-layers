#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "boto3",
#     "pyyaml",
#     "click",
# ]
# ///
"""
test-distribution-locally.py

A utility script to build and test custom OpenTelemetry Collector distributions locally.
This script emulates the GitHub workflow process but targets only the local AWS region
and uses 'local' as the release group to keep test layers separate from production ones.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import click


def run_command(cmd, cwd=None, env=None, check=True, capture_output=False):
    """Run a shell command and print its output."""
    click.echo(f"Running: {' '.join(cmd)}" + (f" in {cwd}" if cwd else ""))
    
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    
    if capture_output:
        process = subprocess.run(
            cmd,
            cwd=cwd,
            env=full_env,
            text=True,
            check=False,  # Don't check here, we'll handle errors
            capture_output=True
        )
    else:
        process = subprocess.run(
            cmd,
            cwd=cwd,
            env=full_env,
            text=True,
            check=check
        )
    
    return process


def check_aws_credentials():
    """Check if AWS credentials are configured correctly."""
    click.echo("Checking AWS credentials...")
    
    try:
        # Import boto3 (should be available as it's in the script requirements)
        import boto3
        
        # Create a boto3 STS client
        sts_client = boto3.client('sts')
        
        # Call get_caller_identity directly using boto3
        response = sts_client.get_caller_identity()
        
        # Extract account ID from response
        account_id = response.get('Account')
        if account_id:
            click.secho(f"AWS credentials are configured for account: {account_id}", fg="green")
            return True
        else:
            click.secho("AWS credentials are configured but account ID couldn't be determined.", fg="yellow", err=True)
            return False
            
    except ImportError:
        click.secho("boto3 is not installed. Please install it: pip install boto3", fg="red", err=True)
        return False
    except Exception as e:
        click.secho(f"AWS credentials are not configured correctly: {str(e)}", fg="red", err=True)
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
            click.secho("Could not determine AWS region from boto3 session, defaulting to us-east-1", fg="yellow")
            return "us-east-1"
    except Exception as e:
        click.secho(f"Error getting AWS region: {e}", fg="red", err=True)
        click.secho("Defaulting to us-east-1", fg="yellow")
        return "us-east-1"


DISTRIBUTION_CHOICES = ["default", "minimal", "clickhouse", "full"]
ARCHITECTURE_CHOICES = ["amd64", "arm64"]


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option(
    "--distribution", "-d", 
    default="default",
    type=click.Choice(DISTRIBUTION_CHOICES, case_sensitive=False),
    help="The distribution to build."
)
@click.option(
    "--architecture", "-a", 
    default="amd64",
    type=click.Choice(ARCHITECTURE_CHOICES, case_sensitive=False),
    help="The architecture to build for."
)
@click.option(
    "--upstream-repo", "-r", 
    default="open-telemetry/opentelemetry-lambda",
    help="Upstream repository to use."
)
@click.option(
    "--upstream-ref", "-b", 
    default="main",
    help="Upstream Git reference (branch, tag, SHA)."
)
@click.option(
    "--layer-name", "-l", 
    default="otel-ext-layer",
    help="Base name for the Lambda layer."
)
@click.option(
    "--runtimes", 
    default="nodejs18.x nodejs20.x java17 python3.9 python3.10",
    help="Space-delimited list of compatible runtimes."
)
@click.option(
    "--skip-publish", 
    is_flag=True,
    help="Skip the publishing step and only build the layer."
)
@click.option(
    "--verbose", "-v", 
    is_flag=True,
    help="Show more detailed output."
)
@click.option(
    "--public", 
    is_flag=True,
    help="Make the layer publicly accessible."
)
def main(distribution, architecture, upstream_repo, upstream_ref, layer_name, runtimes, skip_publish, verbose, public):
    """Build and test custom OTel Collector distributions locally."""
    
    # Set up paths
    repo_root = Path(__file__).parent.parent.resolve()
    build_dir = repo_root / "build"
    build_dir.mkdir(exist_ok=True)
    
    # Step 1: Build the collector layer
    click.secho(f"Building the {distribution} distribution for {architecture}...", fg="cyan", bold=True)
    
    build_script = repo_root / "scripts" / "build_extension_layer.py"
    build_cmd = [
        sys.executable,
        str(build_script),
        "--upstream-repo", upstream_repo,
        "--upstream-ref", upstream_ref,
        "--distribution", distribution,
        "--arch", architecture,
        "--output-dir", str(build_dir)
    ]
    
    build_result = run_command(build_cmd)
    
    if build_result.returncode != 0:
        click.secho("Build failed. Exiting.", fg="red", err=True)
        sys.exit(1)
    
    layer_file = build_dir / f"collector-{architecture}.zip"
    if not layer_file.exists():
        click.secho(f"Expected layer file not found: {layer_file}", fg="red", err=True)
        sys.exit(1)
    
    click.secho(f"Build successful. Layer file: {layer_file}", fg="green")
    
    if skip_publish:
        click.secho("Skipping publish step as requested.", fg="yellow")
        return
    
    # Check AWS credentials before publishing
    if not check_aws_credentials():
        click.secho("AWS credentials check failed. Skipping publish step.", fg="red", err=True)
        click.secho("To configure AWS credentials, run 'aws configure'", fg="yellow", err=True)
        sys.exit(1)
    
    # Step 2: Publish the layer to AWS Lambda
    click.secho(f"Publishing layer to AWS Lambda...", fg="cyan", bold=True)
    
    # Get the current AWS region
    region = get_aws_region()
    
    # Ensure boto3 is installed
    try:
        import boto3
    except ImportError:
        click.secho("boto3 is required for publishing layers. Installing...", fg="yellow", err=True)
        run_command([sys.executable, "-m", "pip", "install", "boto3"])
        try:
            import boto3
        except ImportError:
            click.secho("Failed to install boto3. Please install it manually: pip install boto3", fg="red", err=True)
            sys.exit(1)
    
    # Prepare environment variables for the publisher script
    publish_env = {
        "PY_LAYER_NAME": layer_name,
        "PY_ARTIFACT_NAME": str(layer_file),
        "PY_REGION": region,
        "PY_ARCHITECTURE": architecture,
        "PY_RUNTIMES": runtimes,
        "PY_RELEASE_GROUP": "local",  # Always use 'local' for testing
        "PY_DISTRIBUTION": distribution,
        "PY_PUBLIC": str(public).lower()  # Convert boolean to 'true' or 'false'
    }
    
    # Print debug info if verbose
    if verbose:
        click.secho("Publishing with environment variables:", fg="blue")
        for key, value in publish_env.items():
            click.echo(f"  {key}={value}")
    
    publisher_script = repo_root / "scripts" / "lambda_layer_publisher.py"
    
    # Run with capture_output in verbose mode to show detailed error messages
    if verbose:
        publish_result = run_command(
            [sys.executable, str(publisher_script)],
            env=publish_env,
            capture_output=True
        )
        if publish_result.returncode != 0:
            click.secho("Publish failed with the following error:", fg="red", err=True)
            click.secho(publish_result.stderr, fg="red", err=True)
            click.echo(publish_result.stdout)
            sys.exit(1)
        else:
            click.echo(publish_result.stdout)
    else:
        # Standard run without capturing output
        publish_result = run_command(
            [sys.executable, str(publisher_script)],
            env=publish_env
        )
        if publish_result.returncode != 0:
            click.secho("Publish failed. Use --verbose for more details.", fg="red", err=True)
            sys.exit(1)
    
    click.secho(f"Successfully published {distribution} distribution to region {region} as a 'local' release.", fg="green", bold=True)
    click.secho("You can now test this layer by attaching it to a Lambda function.", fg="green")


if __name__ == "__main__":
    main() 