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
    # Example: custom-otel-collector-amd64-clickhouse-0_119_0 -> 0_119_0
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
        Tuple[str, str, str]: (layer_name_cleaned, arch_str, layer_version_str_for_naming)
    """
    layer_name = base_name
    layer_version_str_for_naming = ""
    
    # Handle architecture
    arch_str = "x86_64 arm64"  # Default
    if architecture:
        layer_name = f"{layer_name}-{architecture}"
        arch_str = architecture.replace("amd64", "x86_64")
    
    # Add distribution if specified
    if distribution: 
        layer_name = f"{layer_name}-{distribution}"
        print(f"Including distribution ('{distribution}') in layer name")
    
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
    
    # Always add release group (even if 'prod')
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
    runtimes: Optional[str] = None,
    build_tags: Optional[str] = None # Added build_tags parameter
) -> Optional[str]:
    """Publish a new Lambda layer version."""
    print(f"Publishing layer with name: {layer_name}")
    
    # Construct description
    description = f"Build Tags: {build_tags if build_tags else 'N/A'} | MD5: {md5_hash}"
    # Truncate description if it exceeds AWS limit (256 chars)
    if len(description) > 256:
        description = description[:253] + "..."
        print(f"Warning: Truncated layer description due to length limit.", file=sys.stderr)
        
    print(f"Layer Description: {description}")

    runtime_param = f"--compatible-runtimes {runtimes}" if runtimes else ""
    cmd = f"aws lambda publish-layer-version " \
          f"--layer-name {layer_name} " \
          f"--description \"{description}\" " \
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
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1') # New: Always use us-east-1
        table = dynamodb.Table(DYNAMODB_TABLE_NAME)
        
        response = table.put_item(Item=item_to_write)
        
        status_code = response.get('ResponseMetadata', {}).get('HTTPStatusCode')
        if status_code == 200:
            print(f"Successfully wrote metadata for {metadata['layer_arn']} to DynamoDB in us-east-1.")
            return True
        else:
            print(f"DynamoDB put_item failed with status code {status_code}. Response: {response}", file=sys.stderr)
            return False
            
    except ClientError as e:
        print(f"DynamoDB ClientError writing metadata: {e}", file=sys.stderr)
        error_code = e.response.get('Error', {}).get('Code')
        if error_code == 'ResourceNotFoundException':
            print(f"Error: DynamoDB table '{DYNAMODB_TABLE_NAME}' not found in region us-east-1. Please ensure it exists.", file=sys.stderr)
        elif error_code == 'AccessDeniedException':
             print(f"Error: Access denied writing to DynamoDB table '{DYNAMODB_TABLE_NAME}' in us-east-1. Check IAM permissions.", file=sys.stderr)
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


def check_and_repair_dynamodb(args, existing_layer_arn: str, md5_hash: str, layer_version_str: str):
    """Checks if metadata for an existing layer ARN is in DynamoDB and adds it if missing."""
    print(f"Checking DynamoDB for existing layer: {existing_layer_arn}")
    pk = args.distribution
    sk = existing_layer_arn
    
    try:
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        table = dynamodb.Table(DYNAMODB_TABLE_NAME)
        
        response = table.get_item(Key={'pk': pk, 'sk': sk})
        
        if 'Item' not in response:
            print(f"Metadata for {existing_layer_arn} not found in DynamoDB. Repairing...")
            # Construct the metadata dictionary exactly as in the successful publish path
            metadata = {
                'pk': pk,
                'sk': sk,
                'layer_arn': existing_layer_arn,
                'region': args.region,
                'base_name': args.layer_name,
                'architecture': args.architecture,
                'distribution': args.distribution,
                'layer_version_str': layer_version_str,
                'collector_version_input': args.collector_version,
                'md5_hash': md5_hash,
                'publish_timestamp': datetime.now(timezone.utc).isoformat(), # Use current time for repair timestamp
                'compatible_runtimes': set(args.runtimes.split()) if args.runtimes else None
            }
            # Attempt to write the missing record
            write_success = write_metadata_to_dynamodb(metadata)
            if write_success:
                print("Successfully repaired missing DynamoDB record.")
            else:
                print("Warning: Failed to repair missing DynamoDB record.", file=sys.stderr)
        else:
            print(f"Metadata for {existing_layer_arn} already exists in DynamoDB. No repair needed.")
            
    except ClientError as e:
        print(f"DynamoDB ClientError during check/repair for {existing_layer_arn}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"An unexpected error occurred during DynamoDB check/repair: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='AWS Lambda Layer Publisher')
    # Priority: Argument > Environment Variable > Default
    # Required args must come from one of the first two.
    parser.add_argument('--layer-name', 
                        default=os.environ.get('PY_LAYER_NAME'), 
                        required=not os.environ.get('PY_LAYER_NAME'),
                        help='Base layer name (e.g., custom-otel-collector). Env: PY_LAYER_NAME')
    parser.add_argument('--artifact-name', 
                        default=os.environ.get('PY_ARTIFACT_NAME'), 
                        required=not os.environ.get('PY_ARTIFACT_NAME'),
                        help='Path to the layer zip artifact file. Env: PY_ARTIFACT_NAME')
    parser.add_argument('--region', 
                        default=os.environ.get('PY_REGION'), 
                        required=not os.environ.get('PY_REGION'),
                        help='AWS region to publish the layer. Env: PY_REGION')
    parser.add_argument('--architecture', 
                        default=os.environ.get('PY_ARCHITECTURE'), 
                        help='Layer architecture (amd64 or arm64). Env: PY_ARCHITECTURE')
    parser.add_argument('--runtimes', 
                        default=os.environ.get('PY_RUNTIMES'), 
                        help='Space-delimited list of compatible runtimes. Env: PY_RUNTIMES')
    parser.add_argument('--release-group', 
                        default=os.environ.get('PY_RELEASE_GROUP', 'prod'), 
                        help='Release group (dev or prod, default: prod). Env: PY_RELEASE_GROUP')
    parser.add_argument('--layer-version', 
                        default=os.environ.get('PY_LAYER_VERSION'), 
                        help='Specific version override for layer naming. Env: PY_LAYER_VERSION')
    parser.add_argument('--distribution', 
                        default=os.environ.get('PY_DISTRIBUTION', 'default'), 
                        help='Distribution name (default: default). Env: PY_DISTRIBUTION')
    parser.add_argument('--collector-version', 
                        default=os.environ.get('PY_COLLECTOR_VERSION'), 
                        help='Version of the OpenTelemetry collector included. Env: PY_COLLECTOR_VERSION')
    parser.add_argument('--public', 
                        action='store_true',
                        default=os.environ.get('PY_PUBLIC', '').lower() in ('true', 'yes', '1'),
                        help='Make the layer publicly accessible. Env: PY_PUBLIC')
    
    args = parser.parse_args()
    
    # Step 1: Construct layer name
    layer_name, arch_str, layer_version_str = construct_layer_name(
        args.layer_name, 
        args.architecture,
        args.distribution,
        args.layer_version,
        args.collector_version,
        args.release_group
    )
    
    # Step 2: Calculate MD5 hash
    md5_hash = calculate_md5(args.artifact_name)
    
    # Step 3: Check if layer exists using Lambda API
    skip_publish, existing_layer_arn = check_layer_exists(layer_name, md5_hash, args.region)
    
    # Set output for GitHub Actions early
    set_github_output("skip_publish", str(skip_publish).lower())
    
    layer_arn = existing_layer_arn # Use existing ARN if found
    dynamo_write_attempted = False
    dynamo_success = False
    
    # Step 4: Publish layer if needed
    if not skip_publish:
        print("Publishing new layer version...")
        # Read build tags from environment variable
        build_tags_env = os.environ.get('PY_BUILD_TAGS', '') 
        layer_arn = publish_layer(
            layer_name,
            args.artifact_name,
            md5_hash,
            args.region,
            arch_str,
            args.runtimes,
            build_tags=build_tags_env # Pass build tags to publish_layer
        )
        if layer_arn:
            # Step 5: Make layer public only if explicitly requested
            public_success = True
            if args.public:
                public_success = make_layer_public(layer_name, layer_arn, args.region)
            else:
                print("Keeping layer private (default behavior). Use --public to make it publicly accessible.")
            
            if public_success:
                # Step 5.5: Write Metadata for NEW layer to DynamoDB
                print("Preparing metadata for new layer for DynamoDB...")
                metadata = {
                    'pk': args.distribution,
                    'sk': layer_arn,
                    'layer_arn': layer_arn,
                    'region': args.region,
                    'base_name': args.layer_name,
                    'architecture': args.architecture,
                    'distribution': args.distribution,
                    'layer_version_str': layer_version_str,
                    'collector_version_input': args.collector_version,
                    'md5_hash': md5_hash,
                    'publish_timestamp': datetime.now(timezone.utc).isoformat(),
                    # Store as a list instead of a set for DynamoDB List (L) type
                    'compatible_runtimes': args.runtimes.split() if args.runtimes else None 
                }
                dynamo_write_attempted = True
                dynamo_success = write_metadata_to_dynamodb(metadata)
                if not dynamo_success:
                     print("Warning: Layer published and made public, but failed to write metadata to DynamoDB.", file=sys.stderr)
            else:
                print(f"Warning: Layer {layer_arn} was published but could not be made public. Skipping DynamoDB write.", file=sys.stderr)
        else:
             # Handle case where publishing failed
             print(f"Layer publishing failed for {layer_name} in {args.region}. No ARN generated.", file=sys.stderr)
             sys.exit(1) # Exit if publish fails
             
    # --- Logic for skipped publish --- 
    elif skip_publish and existing_layer_arn:
        print(f"Layer with MD5 {md5_hash} already exists: {existing_layer_arn}. Skipping publish.")
        layer_arn = existing_layer_arn # Ensure layer_arn is set to the existing one
        
        # NEW: Check if the metadata for this existing layer is in DynamoDB and repair if needed
        check_and_repair_dynamodb(args, existing_layer_arn, md5_hash, layer_version_str)
        # Note: We don't set dynamo_success here, as the goal was just checking/repairing.
        # The summary will correctly reflect 'Reused existing layer'.
        
    # --- End of skipped publish logic ---
    
    # Step 6: Create summary (only if we have a valid ARN, either new or existing)
    if layer_arn:
        create_github_summary(
            layer_name,
            args.region,
            layer_arn, # Use the ARN (new or existing)
            md5_hash,
            skip_publish, # Pass the result of the initial check
            args.artifact_name,
            args.distribution,
            args.architecture,
            args.collector_version
            # TODO: Pass dynamo_success status to summary if needed?
        )
        # Set layer_arn output if it wasn't set earlier (in case of skip_publish)
        set_github_output("layer_arn", layer_arn) 
    else:
        # This case should ideally not be reached if publishing failed (exited) 
        # or if skip_publish was true but existing_layer_arn was somehow None
        print("Error: No valid layer ARN available to generate summary.", file=sys.stderr)
        # Consider exiting non-zero here if appropriate


if __name__ == "__main__":
    main()
