#!/usr/bin/env python3
"""
lambda_layer_publisher.py

A comprehensive script to handle AWS Lambda layer publishing:
- Constructs layer name based on inputs
- Calculates MD5 hash of layer content
- Checks if an identical layer already exists
- Publishes new layer version if needed
- Makes the layer public
- Outputs a summary of the action
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Optional, Tuple, Union


def run_aws_command(cmd: str) -> Union[Dict, List, str, None]:
    """Run an AWS CLI command and return its output."""
    try:
        result = subprocess.run(
            cmd, shell=True, check=True, 
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
            text=True
        )
        # Try to parse as JSON if possible
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            # Return as text if not JSON
            return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        if "ResourceNotFoundException" in e.stderr:
            return None
        print(f"Error running AWS command: {e}", file=sys.stderr)
        print(f"Command was: {cmd}", file=sys.stderr)
        print(f"Error output: {e.stderr}", file=sys.stderr)
        return None


def calculate_md5(filename: str) -> str:
    """Calculate MD5 hash of a file."""
    print(f"Computing MD5 hash of layer artifact: {filename}")
    hash_md5 = hashlib.md5()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    md5_hash = hash_md5.hexdigest()
    print(f"Layer MD5 hash: {md5_hash}")
    return md5_hash


def construct_layer_name(
    base_name: str,
    architecture: Optional[str] = None,
    distribution: Optional[str] = None,
    version: Optional[str] = None,
    collector_version: Optional[str] = None,
    release_group: str = "prod",
) -> Tuple[str, str]:
    """
    Construct the full layer name according to AWS naming rules.
    
    Returns:
        Tuple[str, str]: (layer_name, architecture_string)
    """
    layer_name = base_name
    
    # Handle architecture
    arch_str = "x86_64 arm64"  # Default
    if architecture:
        layer_name = f"{layer_name}-{architecture}"
        arch_str = architecture.replace("amd64", "x86_64")
    
    # Add distribution if specified and not default
    if distribution and distribution != "default":
        layer_name = f"{layer_name}-{distribution}"
        print(f"Including distribution in layer name: {distribution}")
    
    # Add version in a way that conforms to AWS naming requirements
    layer_version = None
    if version:
        layer_version = version
    elif collector_version:
        # Extract the version number without the 'v' prefix if present
        layer_version = re.sub(r'^v', '', collector_version)
    else:
        # Fallback if version is not available
        github_ref = os.environ.get('GITHUB_REF', '')
        if github_ref:
            layer_version = re.sub(r'.*\/[^0-9\.]*', '', github_ref) or "latest"
        else:
            layer_version = "latest"
    
    # Clean up the version to conform to AWS Lambda layer naming rules
    # Replace dots with underscores and remove any non-alphanumeric characters except - and _
    if layer_version:
        layer_version_cleaned = re.sub(r'[^a-zA-Z0-9_-]', '_', layer_version)
        layer_name = f"{layer_name}-{layer_version_cleaned}"
    
    # Add release group if not prod
    if release_group != "prod":
        layer_name = f"{layer_name}-{release_group}"
    
    # Final cleanup: ensure layer name only contains allowed characters (a-zA-Z0-9-_)
    layer_name_cleaned = re.sub(r'[^a-zA-Z0-9_-]', '_', layer_name)
    
    # Ensure it doesn't start with a number (AWS requirement)
    if re.match(r'^[0-9]', layer_name_cleaned):
        layer_name_cleaned = f"layer-{layer_name_cleaned}"
    
    print(f"Final layer name: {layer_name_cleaned}")
    return layer_name_cleaned, arch_str


def check_layer_exists(layer_name: str, current_md5: str, region: str) -> Tuple[bool, Optional[str]]:
    """
    Check if a Lambda layer with the given name and MD5 hash exists.
    
    Args:
        layer_name: Name of the Lambda layer
        current_md5: MD5 hash of the current layer content
        region: AWS region to check in
        
    Returns:
        tuple: (skip_publish, existing_layer_arn)
            - skip_publish: True if publishing can be skipped
            - existing_layer_arn: ARN of existing layer if found, otherwise None
    """
    print(f"Checking if layer '{layer_name}' already exists in {region}...")
    
    cmd = f"aws lambda list-layer-versions --layer-name {layer_name} " \
          f"--query 'LayerVersions[].[LayerVersionArn, Description]' " \
          f"--output json --region {region}"
          
    existing_layers = run_aws_command(cmd)
    
    if not existing_layers or existing_layers == []:
        print("No existing layers found.")
        return False, None
        
    print(f"Found existing layers, checking for MD5 match...")
    print(f"Current layer MD5: {current_md5}")
    
    # Check for MD5 match in layer descriptions
    matching_layer = None
    for layer_arn, description in existing_layers:
        if description and current_md5 in description:
            matching_layer = layer_arn
            print(f"Found layer with matching MD5 hash: {layer_arn}")
            return True, matching_layer
    
    # No match found, get the latest version
    if existing_layers:
        latest_layer = existing_layers[0][0]
        print(f"No layer with matching MD5 found. Latest version: {latest_layer}")
        return False, latest_layer
        
    return False, None


def publish_layer(
    layer_name: str, 
    layer_file: str, 
    md5_hash: str, 
    region: str, 
    arch: str,
    runtimes: Optional[str] = None
) -> Optional[str]:
    """
    Publish a new Lambda layer version.
    
    Args:
        layer_name: Name of the Lambda layer
        layer_file: Path to the layer zip file
        md5_hash: MD5 hash of the layer content
        region: AWS region to publish to
        arch: Architecture string (x86_64, arm64, or both)
        runtimes: Optional space-delimited list of compatible runtimes
        
    Returns:
        Optional[str]: ARN of the published layer, or None if publishing failed
    """
    print(f"Publishing layer with name: {layer_name}")
    
    runtime_param = f"--compatible-runtimes {runtimes}" if runtimes else ""
    
    cmd = f"aws lambda publish-layer-version " \
          f"--layer-name {layer_name} " \
          f"--description \"MD5: {md5_hash}\" " \
          f"--license-info \"Apache 2.0\" " \
          f"--compatible-architectures {arch} " \
          f"{runtime_param} " \
          f"--zip-file fileb://{layer_file} " \
          f"--query 'LayerVersionArn' " \
          f"--output text " \
          f"--region {region}"
    
    layer_arn = run_aws_command(cmd)
    if layer_arn:
        print(f"Published Layer ARN: {layer_arn}")
        return layer_arn
    return None


def make_layer_public(layer_name: str, layer_arn: str, region: str) -> bool:
    """
    Make a Lambda layer version publicly accessible.
    
    Args:
        layer_name: Name of the Lambda layer
        layer_arn: ARN of the layer version
        region: AWS region
        
    Returns:
        bool: True if the operation was successful, False otherwise
    """
    print(f"Making layer public: {layer_arn}")
    
    if not layer_arn:
        print("No layer ARN found. Cannot make layer public.", file=sys.stderr)
        return False
    
    # Extract layer version from ARN
    # ARN format: arn:aws:lambda:region:account-id:layer:name:version
    version_match = re.search(r':(\d+)$', layer_arn)
    if version_match:
        layer_version = version_match.group(1)
    else:
        print(f"Failed to extract valid version number from ARN: {layer_arn}", file=sys.stderr)
        print("Attempting alternate method to determine layer version...")
        
        # Alternative method - get the version directly
        cmd = f"aws lambda list-layer-versions " \
              f"--layer-name {layer_name} " \
              f"--query \"LayerVersions[?LayerVersionArn=='{layer_arn}'].Version\" " \
              f"--output text " \
              f"--region {region}"
        layer_version = run_aws_command(cmd)
        
        if not layer_version or layer_version == "None":
            print("Failed to determine layer version. Cannot make layer public.", file=sys.stderr)
            return False
    
    print(f"Using layer version: {layer_version}")
    
    # Check if permission already exists
    cmd = f"aws lambda get-layer-version-policy " \
          f"--layer-name {layer_name} " \
          f"--version-number {layer_version} " \
          f"--query 'Policy' " \
          f"--output text " \
          f"--region {region}"
    permission_exists = run_aws_command(cmd)
    
    if permission_exists and permission_exists != "None":
        print("Layer is already public. Skipping permission update.")
        return True
    
    # Add public permission
    print("Setting public permissions on layer...")
    cmd = f"aws lambda add-layer-version-permission " \
          f"--layer-name {layer_name} " \
          f"--version-number {layer_version} " \
          f"--principal \"*\" " \
          f"--statement-id publish " \
          f"--action lambda:GetLayerVersion " \
          f"--region {region}"
    
    result = run_aws_command(cmd)
    if result:
        print("Layer successfully made public.")
        return True
    
    print("Failed to make layer public.", file=sys.stderr)
    return False


def create_github_summary(
    layer_name: str,
    region: str,
    layer_arn: str,
    md5_hash: str,
    skip_publish: bool,
    artifact_name: str,
    distribution: Optional[str] = None,
    architecture: Optional[str] = None,
    collector_version: Optional[str] = None
) -> None:
    """Create a summary for GitHub Actions."""
    github_step_summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if not github_step_summary:
        return
    
    with open(github_step_summary, 'a') as f:
        f.write("## Layer Publishing Summary 📦\n")
        f.write("| Property | Value |\n")
        f.write("| --- | --- |\n")
        f.write(f"| Layer Name | `{layer_name}` |\n")
        f.write(f"| Region | `{region}` |\n")
        f.write(f"| ARN | `{layer_arn}` |\n")
        f.write(f"| Content MD5 | `{md5_hash}` |\n")
        
        if skip_publish:
            f.write("| Status | ♻️ Reused existing layer (identical content) |\n")
        else:
            f.write("| Status | 🆕 Published new layer version |\n")
        
        f.write(f"| Artifact | `{artifact_name}` |\n")
        
        if distribution and distribution != "default":
            f.write(f"| Distribution | `{distribution}` |\n")
        
        if architecture:
            f.write(f"| Architecture | `{architecture}` |\n")
        
        if collector_version:
            f.write(f"| Collector Version | `{collector_version}` |\n")


def set_github_output(name: str, value: str) -> None:
    """Set an output variable for GitHub Actions."""
    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a') as f:
            f.write(f"{name}={value}\n")


def main():
    parser = argparse.ArgumentParser(description='AWS Lambda Layer Publisher')
    parser.add_argument('--layer-name', required=True, help='Base layer name')
    parser.add_argument('--artifact-name', required=True, help='Artifact filename')
    parser.add_argument('--region', required=True, help='AWS region')
    parser.add_argument('--architecture', help='Architecture (amd64 or arm64)')
    parser.add_argument('--runtimes', help='Space-delimited list of compatible runtimes')
    parser.add_argument('--release-group', default='prod', 
                        help='Release group (dev or prod, default: prod)')
    parser.add_argument('--layer-version', help='Layer version to use')
    parser.add_argument('--distribution', default='default', 
                        help='Distribution name (default: default)')
    parser.add_argument('--collector-version', help='Version of the OpenTelemetry collector')
    
    args = parser.parse_args()
    
    # Step 1: Construct layer name
    layer_name, arch_str = construct_layer_name(
        args.layer_name,
        args.architecture,
        args.distribution,
        args.layer_version,
        args.collector_version,
        args.release_group
    )
    
    # Step 2: Calculate MD5 hash
    md5_hash = calculate_md5(args.artifact_name)
    
    # Step 3: Check if layer exists
    skip_publish, existing_layer = check_layer_exists(layer_name, md5_hash, args.region)
    
    # Set output for GitHub Actions
    set_github_output("skip_publish", str(skip_publish).lower())
    
    layer_arn = existing_layer
    
    # Step 4: Publish layer if needed
    if not skip_publish:
        layer_arn = publish_layer(
            layer_name, 
            args.artifact_name, 
            md5_hash, 
            args.region, 
            arch_str,
            args.runtimes
        )
    
    if layer_arn:
        set_github_output("layer_arn", layer_arn)
        
        # Step 5: Make layer public
        make_layer_public(layer_name, layer_arn, args.region)
        
        # Step 6: Create summary
        create_github_summary(
            layer_name,
            args.region,
            layer_arn,
            md5_hash,
            skip_publish,
            args.artifact_name,
            args.distribution,
            args.architecture,
            args.collector_version
        )
    else:
        print("Layer publishing failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main() 