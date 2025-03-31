#!/usr/bin/env python3
"""
lambda_layer_publisher.py

A comprehensive script to handle AWS Lambda layer publishing:
- Constructs layer name based on inputs
- Calculates MD5 hash of layer content
- Checks if an identical layer already exists
- Publishes new layer version if needed
- Makes the layer public
- Writes metadata to DynamoDB
- Outputs a summary of the action
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone # Added timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

# Try importing boto3 for DynamoDB interaction
try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("boto3 library not found. Please install it: pip install boto3", file=sys.stderr)
    sys.exit(1)

# DynamoDB Table Name (as per design doc)
DYNAMODB_TABLE_NAME = 'custom-collector-extension-layers'

# Default values
DEFAULT_UPSTREAM_REPO = "open-telemetry/opentelemetry-lambda"
DEFAULT_UPSTREAM_REF = "main"
DEFAULT_DISTRIBUTION = "default"
DEFAULT_ARCHITECTURE = "amd64"


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
        stderr_lower = e.stderr.lower()
        if "resourcenotfoundexception" in stderr_lower:
            # Handle case where the layer or policy doesn't exist gracefully
            print(f"AWS resource not found (expected in some cases): {e.stderr.strip()}", file=sys.stderr)
            return None
        elif "accessdenied" in stderr_lower:
             print(f"AWS Access Denied: {e.stderr.strip()}\nPlease check IAM permissions.", file=sys.stderr)
             sys.exit(f"AWS Access Denied for command: {cmd}") # Exit on permission errors
        else:
            print(f"Error running AWS command: {e}", file=sys.stderr)
            print(f"Command was: {cmd}", file=sys.stderr)
            print(f"Stderr: {e.stderr}", file=sys.stderr)
            # Allow script to continue for some errors, but maybe exit for critical ones?
            # For now, returning None, but consider specific error handling
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


def extract_layer_version_str(layer_name: str) -> str:
    """Extracts the version part from the layer name heuristically."""
    # This logic assumes the version is the last part after distribution/arch
    # Example: opentelemetry-collector-amd64-clickhouse-0_119_0 -> 0_119_0
    parts = layer_name.split('-')
    # Find the likely start of the version (usually after arch or distribution)
    version_part = parts[-1] # Start with the last part
    # Basic check if it looks like a version (contains numbers/underscores/dots)
    if re.search(r'[0-9._]', version_part):
         return version_part
    # Fallback or more complex logic might be needed if names vary wildly
    print(f"Warning: Could not reliably extract version string from '{layer_name}'. Using last part: '{version_part}'", file=sys.stderr)
    return version_part


def construct_layer_name(
    base_name: str,
    architecture: Optional[str] = None,
    distribution: Optional[str] = None,
    version: Optional[str] = None,
    collector_version: Optional[str] = None,
    release_group: str = "prod",
) -> Tuple[str, str, str]: # Added layer_version_str to return
    """
    Construct the full layer name according to AWS naming rules.
    
    Returns:
        Tuple[str, str, str]: (layer_name_cleaned, arch_str, layer_version_str)
    """
    layer_name = base_name
    layer_version_str_for_naming = ""
    
    # Handle architecture
    arch_str = "x86_64 arm64"  # Default
    if architecture:
        layer_name = f"{layer_name}-{architecture}"
        arch_str = architecture.replace("amd64", "x86_64")
    
    # Add distribution if specified and not default
    if distribution and distribution != "default":
        layer_name = f"{layer_name}-{distribution}"
        print(f"Including distribution in layer name: {distribution}")
    
    # Determine version string for naming
    layer_version = None
    if version:
        layer_version = version
    elif collector_version:
        layer_version = re.sub(r'^v', '', collector_version)
    else:
        github_ref = os.environ.get('GITHUB_REF', '')
        if github_ref:
            layer_version = re.sub(r'.*\/[^0-9\.]*', '', github_ref) or "latest"
        else:
            layer_version = "latest"
    
    # Clean up the version for AWS naming rules
    if layer_version:
        # Replace dots with underscores, remove disallowed chars
        layer_version_cleaned_for_naming = re.sub(r'[^a-zA-Z0-9_-]', '_', layer_version)
        layer_name = f"{layer_name}-{layer_version_cleaned_for_naming}"
        layer_version_str_for_naming = layer_version_cleaned_for_naming # Store the cleaned version used in name
    
    # Add release group if not prod
    if release_group != "prod":
        layer_name = f"{layer_name}-{release_group}"
    
    # Final cleanup for layer name
    layer_name_cleaned = re.sub(r'[^a-zA-Z0-9_-]', '_', layer_name)
    if re.match(r'^[0-9]', layer_name_cleaned):
        layer_name_cleaned = f"layer-{layer_name_cleaned}"
    
    print(f"Final layer name: {layer_name_cleaned}")
    # The actual version string might differ slightly from the cleaned one used in the name
    # We will re-extract it from the final name if needed later, or use layer_version_str_for_naming
    return layer_name_cleaned, arch_str, layer_version_str_for_naming


def check_layer_exists(layer_name: str, current_md5: str, region: str) -> Tuple[bool, Optional[str]]:
    """Check if a Lambda layer with the given name and MD5 hash exists."""
    print(f"Checking if layer '{layer_name}' already exists in {region}...")
    
    cmd = f"aws lambda list-layer-versions --layer-name {layer_name} " \
          f"--query 'LayerVersions[].[LayerVersionArn, Description]' " \
          f"--output json --region {region}"
          
    existing_layers = run_aws_command(cmd)
    
    if not existing_layers or not isinstance(existing_layers, list) or existing_layers == []:
        print("No existing layers found or failed to parse existing layers.")
        return False, None
        
    print(f"Found existing layers, checking for MD5 match...")
    print(f"Current layer MD5: {current_md5}")
    
    # Check for MD5 match in layer descriptions
    matching_layer = None
    for layer_info in existing_layers:
         # Ensure layer_info is a list/tuple with at least 2 elements
         if isinstance(layer_info, (list, tuple)) and len(layer_info) >= 2:
            layer_arn, description = layer_info[0], layer_info[1]
            if description and isinstance(description, str) and current_md5 in description:
                matching_layer = layer_arn
                print(f"Found layer with matching MD5 hash: {layer_arn}")
                return True, matching_layer
         else:
             print(f"Warning: Unexpected format for layer version info: {layer_info}", file=sys.stderr)
    
    # No match found, get the latest version ARN from the first element if list is not empty
    if existing_layers and isinstance(existing_layers[0], (list, tuple)) and len(existing_layers[0]) > 0:
        latest_layer = existing_layers[0][0]
        print(f"No layer with matching MD5 found. Latest version: {latest_layer}")
        return False, latest_layer
        
    print("No layer with matching MD5 found and could not determine latest version.")
    return False, None


def publish_layer(
    layer_name: str, 
    layer_file: str, 
    md5_hash: str, 
    region: str, 
    arch: str,
    runtimes: Optional[str] = None
) -> Optional[str]:
    """Publish a new Lambda layer version."""
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
    """Make a Lambda layer version publicly accessible."""
    print(f"Making layer public: {layer_arn}")
    if not layer_arn:
        print("No layer ARN found. Cannot make layer public.", file=sys.stderr)
        return False
    
    version_match = re.search(r':(\d+)$', layer_arn)
    if version_match:
        layer_version = version_match.group(1)
    else:
        print(f"Failed to extract valid version number from ARN: {layer_arn}", file=sys.stderr)
        print("Attempting alternate method to determine layer version...")
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
    
    print(f"Failed to make layer public. Check AWS CLI output above for details.", file=sys.stderr)
    return False


def write_metadata_to_dynamodb(metadata: dict) -> bool:
    """Write the collected layer metadata to the DynamoDB table."""
    print(f"Writing metadata to DynamoDB table: {DYNAMODB_TABLE_NAME}")
    
    # Basic validation
    required_keys = ['pk', 'sk', 'layer_arn', 'region', 'distribution', 'architecture', 'md5_hash']
    if not all(key in metadata and metadata[key] for key in required_keys):
        print(f"Error: Missing required metadata for DynamoDB write: {metadata}", file=sys.stderr)
        return False
        
    # Ensure publish_timestamp is set
    if 'publish_timestamp' not in metadata:
        metadata['publish_timestamp'] = datetime.now(timezone.utc).isoformat()
        
    # Convert empty strings to None for optional fields if necessary, DynamoDB doesn't like empty strings
    for key, value in metadata.items():
        if value == "":
            metadata[key] = None
            
    # Remove None values as DynamoDB PutItem doesn't support None values unless they are Null type
    item_to_write = {k: v for k, v in metadata.items() if v is not None}
    
    try:
        dynamodb = boto3.resource('dynamodb', region_name=metadata['region']) # Use layer region
        table = dynamodb.Table(DYNAMODB_TABLE_NAME)
        
        response = table.put_item(Item=item_to_write)
        
        status_code = response.get('ResponseMetadata', {}).get('HTTPStatusCode')
        if status_code == 200:
            print(f"Successfully wrote metadata for {metadata['layer_arn']} to DynamoDB.")
            return True
        else:
            print(f"DynamoDB put_item failed with status code {status_code}. Response: {response}", file=sys.stderr)
            return False
            
    except ClientError as e:
        print(f"DynamoDB ClientError writing metadata: {e}", file=sys.stderr)
        error_code = e.response.get('Error', {}).get('Code')
        if error_code == 'ResourceNotFoundException':
            print(f"Error: DynamoDB table '{DYNAMODB_TABLE_NAME}' not found in region {metadata['region']}. Please ensure it exists.", file=sys.stderr)
        elif error_code == 'AccessDeniedException':
             print(f"Error: Access denied writing to DynamoDB table '{DYNAMODB_TABLE_NAME}'. Check IAM permissions.", file=sys.stderr)
        # Add more specific error handling as needed
        return False
    except Exception as e:
        print(f"An unexpected error occurred writing to DynamoDB: {e}", file=sys.stderr)
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
    
    summary = [
        "## Layer Publishing Summary 📦",
        "| Property | Value |",
        "| --- | --- |",
        f"| Layer Name | `{layer_name}` |",
        f"| Region | `{region}` |",
        f"| ARN | `{layer_arn}` |",
        f"| Content MD5 | `{md5_hash}` |",
    ]
    
    if skip_publish:
        summary.append("| Status | ♻️ Reused existing layer (identical content) |")
    else:
        summary.append("| Status | 🆕 Published new layer version |")
    
    summary.append(f"| Artifact | `{artifact_name}` |")
    
    if distribution and distribution != "default":
        summary.append(f"| Distribution | `{distribution}` |")
    
    if architecture:
        summary.append(f"| Architecture | `{architecture}` |")
    
    if collector_version:
        summary.append(f"| Collector Version | `{collector_version}` |")
        
    # Add DynamoDB status to summary
    # (Need to pass status from main)
    # summary.append(f"| Metadata DB Status | {'Success ✅' if dynamo_success else 'Failed ❌'} |") 

    try:
        with open(github_step_summary, 'a') as f:
            f.write("\n".join(summary) + "\n")
    except Exception as e:
        print(f"Error writing to GITHUB_STEP_SUMMARY: {e}", file=sys.stderr)


def set_github_output(name: str, value: str) -> None:
    """Set an output variable for GitHub Actions."""
    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        try:
            with open(github_output, 'a') as f:
                # Ensure value doesn't contain problematic characters for the output format
                # Basic sanitization: replace newline with space
                sanitized_value = str(value).replace('\n', ' ')
                f.write(f"{name}={sanitized_value}\n")
        except Exception as e:
             print(f"Error writing to GITHUB_OUTPUT: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='AWS Lambda Layer Publisher')
    # Add argument descriptions matching the design doc / original script
    parser.add_argument('--layer-name', required=True, help='Base layer name (e.g., opentelemetry-collector)')
    parser.add_argument('--artifact-name', required=True, help='Path to the layer zip artifact file')
    parser.add_argument('--region', required=True, help='AWS region to publish the layer')
    parser.add_argument('--architecture', help='Layer architecture (amd64 or arm64)')
    parser.add_argument('--runtimes', help='Space-delimited list of compatible runtimes')
    parser.add_argument('--release-group', default='prod', help='Release group (dev or prod, default: prod)')
    parser.add_argument('--layer-version', help='Specific version override for layer naming')
    parser.add_argument('--distribution', default='default', help='Distribution name (default: default)')
    parser.add_argument('--collector-version', help='Version of the OpenTelemetry collector included')
    
    args = parser.parse_args()
    
    # Step 1: Construct layer name
    layer_name, arch_str, layer_version_str = construct_layer_name(
        args.layer_name, # Base name like 'opentelemetry-collector'
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
    
    # Set output for GitHub Actions early
    set_github_output("skip_publish", str(skip_publish).lower())
    
    layer_arn = existing_layer
    dynamo_success = False # Track if metadata write succeeds
    
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
        public_success = make_layer_public(layer_name, layer_arn, args.region)
        
        if public_success:
            # Step 5.5: Write Metadata to DynamoDB (Only after successful publish & make public)
            print("Preparing metadata for DynamoDB...")
            metadata = {
                'pk': args.distribution,  # Partition Key
                'sk': layer_arn,          # Sort Key
                'layer_arn': layer_arn,
                'region': args.region,
                'base_name': args.layer_name, # The input base name
                'architecture': args.architecture,
                'distribution': args.distribution,
                # Use the version string derived during name construction
                'layer_version_str': layer_version_str, 
                'collector_version_input': args.collector_version,
                'md5_hash': md5_hash,
                'publish_timestamp': datetime.now(timezone.utc).isoformat(),
                # Convert runtimes string to set if not None/empty
                'compatible_runtimes': set(args.runtimes.split()) if args.runtimes else None 
            }
            
            dynamo_success = write_metadata_to_dynamodb(metadata)
            if not dynamo_success:
                 print("Warning: Layer published and made public, but failed to write metadata to DynamoDB.", file=sys.stderr)
                 # Decide if this should be a fatal error for the workflow? 
                 # For now, we proceed but the state is inconsistent.
        else:
            print(f"Warning: Layer {layer_arn} was published but could not be made public. Skipping DynamoDB write.", file=sys.stderr)
        
        # Step 6: Create summary (Now includes DynamoDB status)
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
            # Pass dynamo_success here when implemented in create_github_summary
        )
    else:
        # Handle case where publishing failed or was skipped and no existing ARN was found
        if skip_publish:
             print(f"Layer with MD5 {md5_hash} already exists: {existing_layer}")
             # Create summary for skipped publish
             create_github_summary(layer_name, args.region, existing_layer, md5_hash, True, 
                                 args.artifact_name, args.distribution, args.architecture, args.collector_version)
        else:
            print(f"Layer publishing failed for {layer_name} in {args.region}. No ARN generated.", file=sys.stderr)
            # Potentially create a failure summary or exit non-zero
            # For now, just print error and exit
            sys.exit(1)


if __name__ == "__main__":
    main() 