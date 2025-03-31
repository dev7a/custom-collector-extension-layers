#!/usr/bin/env python3
"""
build_extension_layer.py

Builds a custom OpenTelemetry Collector Lambda layer by cloning an upstream
repository, overlaying custom components, managing dependencies, and building
the layer package.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Default values
DEFAULT_UPSTREAM_REPO = "open-telemetry/opentelemetry-lambda"
DEFAULT_UPSTREAM_REF = "main"
DEFAULT_DISTRIBUTION = "default"
DEFAULT_ARCHITECTURE = "amd64"


def run_command(cmd: list, cwd: str = None, env: dict = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and handle potential errors."""
    print(f"Running command: {' '.join(cmd)}" + (f" in {cwd}" if cwd else ""))
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
        
    process = subprocess.run(
        cmd, 
        cwd=cwd, 
        env=full_env,
        capture_output=True, 
        text=True
    )
    
    if check and process.returncode != 0:
        print(f"Command failed with exit code {process.returncode}", file=sys.stderr)
        print(f"Stderr: {process.stderr}", file=sys.stderr)
        print(f"Stdout: {process.stdout}", file=sys.stderr)
        raise subprocess.CalledProcessError(process.returncode, cmd, output=process.stdout, stderr=process.stderr)
    elif process.returncode != 0:
         print(f"Command returned non-zero exit code {process.returncode}, but check=False", file=sys.stderr)
         print(f"Stderr: {process.stderr}", file=sys.stderr)
         print(f"Stdout: {process.stdout}", file=sys.stderr)
        
    return process

def get_build_tags(distribution: str, custom_tags_str: str) -> str:
    """Determine the Go build tags based on the distribution."""
    tags_map = {
        "minimal": "lambdacomponents.custom,lambdacomponents.receiver.otlp,lambdacomponents.processor.batch",
        "clickhouse": "lambdacomponents.custom,lambdacomponents.receiver.otlp,lambdacomponents.processor.batch,lambdacomponents.exporter.clickhouse",
        "clickhouse-otlphttp": "lambdacomponents.custom,lambdacomponents.receiver.otlp,lambdacomponents.processor.batch,lambdacomponents.exporter.clickhouse,lambdacomponents.exporter.otlphttp",
        "full": "lambdacomponents.custom,lambdacomponents.all",
        "default": "",
    }

    if distribution == "custom":
        if custom_tags_str:
            tags = custom_tags_str
            # Ensure lambdacomponents.custom is present
            if "lambdacomponents.custom" not in tags:
                tags = f"lambdacomponents.custom,{tags}"
            return tags
        else:
            # Default for custom if no tags are provided
            return "lambdacomponents.custom"
    
    return tags_map.get(distribution, "")

def add_dependencies(collector_dir: Path, build_tags: str):
    """Add Go dependencies based on build tags."""
    if "lambdacomponents.exporter.clickhouse" in build_tags:
        print("Adding ClickHouse exporter dependency...")
        try:
            # Try to detect OpenTelemetry version from go.mod
            otel_version = None
            go_mod_path = collector_dir / "go.mod"
            if go_mod_path.exists():
                with open(go_mod_path, 'r') as f:
                    for line in f:
                        if "go.opentelemetry.io/collector " in line:
                            match = re.search(r'v([0-9]+\.[0-9]+\.[0-9]+)', line)
                            if match:
                                otel_version = f"v{match.group(1)}"
                                break
            
            if not otel_version:
                print("Could not detect OTEL version from go.mod, using default v0.119.0", file=sys.stderr)
                otel_version = "v0.119.0"
                
            print(f"Using OpenTelemetry version: {otel_version}")
            dependency = f"github.com/open-telemetry/opentelemetry-collector-contrib/exporter/clickhouseexporter@{otel_version}"
            run_command(["go", "get", dependency], cwd=str(collector_dir))
            run_command(["go", "mod", "tidy"], cwd=str(collector_dir))
        except subprocess.CalledProcessError as e:
            print(f"Failed to add/tidy ClickHouse dependency: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"An error occurred while adding dependencies: {e}", file=sys.stderr)
            sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='Build Custom OpenTelemetry Collector Lambda Layer.')
    parser.add_argument('-r', '--upstream-repo', default=DEFAULT_UPSTREAM_REPO,
                        help=f'Upstream repository (default: {DEFAULT_UPSTREAM_REPO})')
    parser.add_argument('-b', '--upstream-ref', default=DEFAULT_UPSTREAM_REF,
                        help=f'Upstream Git reference (branch, tag, SHA) (default: {DEFAULT_UPSTREAM_REF})')
    parser.add_argument('-d', '--distribution', default=DEFAULT_DISTRIBUTION,
                        choices=['default', 'minimal', 'clickhouse', 'clickhouse-otlphttp', 'full', 'custom'],
                        help=f'Distribution name (default: {DEFAULT_DISTRIBUTION})')
    parser.add_argument('-a', '--arch', default=DEFAULT_ARCHITECTURE,
                        choices=['amd64', 'arm64'],
                        help=f'Architecture (default: {DEFAULT_ARCHITECTURE})')
    parser.add_argument('-t', '--build-tags', default='',
                        help='Custom build tags (comma-separated, only used with -d custom)')
    parser.add_argument('-o', '--output-dir', 
                        help='Output directory for built layer (default: current directory)')
    parser.add_argument('-k', '--keep-temp', action='store_true',
                        help='Keep temporary build directory')

    args = parser.parse_args()

    # Determine output directory
    output_dir = Path(args.output_dir).resolve() if args.output_dir else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine custom components directory relative to this script
    script_dir = Path(__file__).parent.resolve()
    custom_repo_path = script_dir.parent
    component_dir = custom_repo_path / "components"

    print("Building with the following configuration:")
    print(f"Upstream Repository: {args.upstream_repo}")
    print(f"Upstream Ref: {args.upstream_ref}")
    print(f"Distribution: {args.distribution}")
    print(f"Architecture: {args.arch}")
    print(f"Build Tags: {args.build_tags if args.distribution == 'custom' else 'N/A'}")
    print(f"Output Directory: {output_dir}")
    print(f"Keep Temp Directory: {args.keep_temp}")
    print(f"Custom Component Dir: {component_dir}")

    temp_dir = tempfile.mkdtemp()
    print(f"Created temporary directory: {temp_dir}")
    temp_dir_path = Path(temp_dir)
    upstream_dir = temp_dir_path / "upstream"

    try:
        # Step 1: Clone upstream repository
        print(f"Cloning upstream repository {args.upstream_repo} (ref: {args.upstream_ref})...")
        repo_url = f"https://github.com/{args.upstream_repo}.git"
        run_command(["git", "clone", "--depth", "1", "--branch", args.upstream_ref, repo_url, str(upstream_dir)])
        # No need to checkout separately due to --branch and --depth 1

        # Step 2: Copy custom components to the upstream directory
        print("Overlaying custom components...")
        if component_dir.is_dir():
            shutil.copytree(component_dir, upstream_dir, dirs_exist_ok=True)
            print(f"Copied components from {component_dir} to {upstream_dir}")
        else:
            print(f"Custom components directory not found at {component_dir}, proceeding without overlay.", file=sys.stderr)
            # Decide if this should be fatal based on requirements
            # For now, we allow proceeding without custom components

        # Step 3: Determine build tags
        build_tags = get_build_tags(args.distribution, args.build_tags)
        print(f"Using build tags: '{build_tags}'")

        # Step 4: Add dependencies for custom components (if needed)
        collector_dir = upstream_dir / "collector"
        if not collector_dir.is_dir():
            print(f"Collector directory not found in upstream repo: {collector_dir}", file=sys.stderr)
            sys.exit(1)
            
        add_dependencies(collector_dir, build_tags)

        # Step 5: Build the collector
        print(f"Building the collector for {args.arch} architecture...")
        build_env = {"GOARCH": args.arch}
        if build_tags:
            build_env["BUILDTAGS"] = build_tags
            
        # Check if Makefile exists before running make
        makefile_path = collector_dir / "Makefile"
        if not makefile_path.exists():
            print(f"Makefile not found at {makefile_path}. Cannot build using make.", file=sys.stderr)
            sys.exit(1)
            
        run_command(["make", "package"], cwd=str(collector_dir), env=build_env)

        # Step 6: Rename and Copy the built layer
        build_output_dir = collector_dir / "build"
        original_filename = f"opentelemetry-collector-layer-{args.arch}.zip"
        new_filename = f"custom-otel-collector-layer-{args.arch}.zip" # Our desired final name
        
        original_build_file = build_output_dir / original_filename
        renamed_build_file = build_output_dir / new_filename # Path for renamed file within build dir

        print(f"Checking for build output: {original_build_file}")
        if not original_build_file.is_file():
            print(f"Build file not found: {original_build_file}", file=sys.stderr)
            print("Contents of build directory:", file=sys.stderr)
            try:
                ls_output = run_command(["ls", "-la"], cwd=str(build_output_dir), check=False)
                print(ls_output.stdout, file=sys.stderr)
            except Exception as ls_err:
                print(f"Could not list build directory contents: {ls_err}", file=sys.stderr)
            sys.exit(1)
            
        # Rename the file produced by make
        print(f"Renaming {original_filename} to {new_filename} within build directory...")
        try:
            original_build_file.rename(renamed_build_file)
        except OSError as e:
            print(f"Error renaming file from {original_build_file} to {renamed_build_file}: {e}", file=sys.stderr)
            sys.exit(1)

        # Copy the RENAMED file to the final output directory
        target_file = output_dir / new_filename # Final destination uses the new name
        print(f"Copying renamed layer from {renamed_build_file} to {target_file}")
        shutil.copy(renamed_build_file, target_file)

        print(f"\nBuild complete! Layer available at: {target_file}")

    except subprocess.CalledProcessError as e:
        print(f"\nBuild failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Cleanup temporary directory
        if not args.keep_temp:
            print(f"Cleaning up temporary directory: {temp_dir}")
            shutil.rmtree(temp_dir)
        else:
            print(f"Temporary directory kept at: {temp_dir}")

if __name__ == "__main__":
    # Need to import re for add_dependencies
    import re 
    main() 