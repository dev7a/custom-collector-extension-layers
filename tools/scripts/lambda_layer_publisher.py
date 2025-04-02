#!/usr/bin/env python3
"""
lambda_layer_publisher.py

A comprehensive script to handle AWS Lambda layer publishing:
- Constructs layer name based on inputs
- Calculates MD5 hash of layer content
- Checks if an identical layer already exists
- Publishes new layer version if needed
- Makes the layer public if requested
- Writes metadata to DynamoDB
- Outputs a summary of the action
"""

import argparse
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from typing import Optional, Tuple


# Import UI utilities
from otel_layer_utils.ui_utils import (
    header, subheader, status, info, detail, 
    success, error, warning, 
    spinner, github_summary_table
)

# Import DynamoDB utilities
from otel_layer_utils.dynamodb_utils import (
    DYNAMODB_TABLE_NAME,
    get_item,
    write_item
)

# Import boto3 for AWS API operations
try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    error("boto3 library not found", "Please install it: pip install boto3")
    sys.exit(1)

# Default values
DEFAULT_UPSTREAM_REPO = "open-telemetry/opentelemetry-lambda"
DEFAULT_UPSTREAM_REF = "main"
DEFAULT_DISTRIBUTION = "default"
DEFAULT_ARCHITECTURE = "amd64"


def calculate_md5(filename: str) -> str:
    """Calculate MD5 hash of a file."""
    status("Computing MD5", filename)
    
    def compute_hash():
        hash_md5 = hashlib.md5()
        with open(filename, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    md5_hash = spinner("Computing MD5 hash", compute_hash)
    success("MD5 Hash", md5_hash)
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
    warning(f"Could not reliably extract version string from '{layer_name}'", 
            f"Using last part: '{version_part}'")
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
    arch_str = architecture.replace("amd64", "x86_64") if architecture else "x86_64"
    if architecture:
        layer_name = f"{layer_name}-{architecture}"
    
    # Add distribution if specified
    if distribution: 
        layer_name = f"{layer_name}-{distribution}"
        info("Including distribution in layer name", distribution)
    
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
    
    success("Final layer name", layer_name_cleaned)
    # The actual version string might differ slightly from the cleaned one used in the name
    # We will re-extract it from the final name if needed later, or use layer_version_str_for_naming
    return layer_name_cleaned, arch_str, layer_version_str_for_naming


def check_layer_exists(layer_name: str, current_md5: str, region: str) -> Tuple[bool, Optional[str]]:
    """Check if a Lambda layer with the given name and MD5 hash exists using boto3."""
    subheader("Checking layers")
    status("Checking layer existence", f"{layer_name} in {region}")
    
    def check_lambda_layers():
        try:
            lambda_client = boto3.client('lambda', region_name=region)
            
            # Get all versions of the layer
            try:
                paginator = lambda_client.get_paginator('list_layer_versions')
                existing_layers = []
                
                for page in paginator.paginate(LayerName=layer_name):
                    for version in page['LayerVersions']:
                        existing_layers.append({
                            'LayerVersionArn': version['LayerVersionArn'],
                            'Description': version.get('Description', '')
                        })
                        
                return existing_layers
            except lambda_client.exceptions.ResourceNotFoundException:
                return None
                
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_message = e.response.get('Error', {}).get('Message', '')
            error("AWS Error", f"{error_code} - {error_message}")
            return False
        except Exception as e:
            error("Error", str(e))
            return False
    
    existing_layers = spinner("Checking existing layers", check_lambda_layers)
    
    if existing_layers is None:
        info("No existing layers found", layer_name)
        return False, None
    
    if not existing_layers:
        info("No existing layers found", "Empty response")
        return False, None
        
    status("Found existing layers", str(len(existing_layers)))
    detail("Current MD5", current_md5)
    
    # Check for MD5 match in descriptions
    for layer in existing_layers:
        if current_md5 in layer['Description']:
            matching_layer = layer['LayerVersionArn']
            success("Found match", matching_layer)
            return True, matching_layer
    
    # No match found, return the latest version ARN if available
    if existing_layers:
        latest_layer = existing_layers[0]['LayerVersionArn']
        info("No MD5 match", f"Latest version: {latest_layer}")
        return False, latest_layer
            
    return False, None


def publish_layer(
    layer_name: str, 
    layer_file: str, 
    md5_hash: str, 
    region: str,
    arch: str,
    runtimes: Optional[str] = None,
    build_tags: Optional[str] = None
) -> Optional[str]:
    """Publish a new Lambda layer version using boto3."""
    subheader("Publishing layer")
    status("Layer name", layer_name)
    
    # Construct description
    description = f"Build Tags: {build_tags if build_tags else 'N/A'} | MD5: {md5_hash}"
    # Truncate description if it exceeds AWS limit (256 chars)
    if len(description) > 256:
        description = description[:253] + "..."
        info("Description truncated", "Length limit exceeded")
        
    detail("Description", description)
    
    # Convert arch from amd64 to x86_64 if needed
    compatible_architectures = [arch.replace("amd64", "x86_64")]
    
    # Prepare the runtimes list
    compatible_runtimes = runtimes.split() if runtimes else None
    
    # Define a function to handle the publishing process
    def do_publish():
        try:
            # Read the ZIP file content
            with open(layer_file, 'rb') as f:
                zip_content = f.read()
            
            lambda_client = boto3.client('lambda', region_name=region)
            
            # Prepare the parameters
            params = {
                'LayerName': layer_name,
                'Description': description,
                'Content': {
                    'ZipFile': zip_content
                },
                'CompatibleArchitectures': compatible_architectures,
                'LicenseInfo': 'Apache 2.0'
            }
            
            # Add runtimes if specified
            if compatible_runtimes:
                params['CompatibleRuntimes'] = compatible_runtimes
            
            # Publish the layer
            response = lambda_client.publish_layer_version(**params)
            
            return response['LayerVersionArn']
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_message = e.response.get('Error', {}).get('Message', '')
            error("AWS Error", f"{error_code} - {error_message}")
            return None
        except Exception as e:
            error("Error", str(e))
            return None
    
    # Use spinner for reading file
    layer_zip_size = os.path.getsize(layer_file) / (1024 * 1024)  # Convert to MB
    info("Layer file size", f"{layer_zip_size:.2f} MB")
    
    # Use spinner for uploading
    layer_arn = spinner("Uploading to AWS Lambda", do_publish)
    
    if layer_arn:
        success("Published", layer_arn)
    return layer_arn


def make_layer_public(layer_name: str, layer_arn: str, region: str) -> bool:
    """Make a Lambda layer version publicly accessible using boto3."""
    subheader("Making layer public")
    status("Layer ARN", layer_arn)
    
    if not layer_arn:
        error("No ARN", "Cannot make layer public")
        return False
    
    # Extract version number from ARN
    version_match = re.search(r':(\d+)$', layer_arn)
    if not version_match:
        error("Invalid ARN", f"No version number in ARN: {layer_arn}")
        return False
        
    layer_version = int(version_match.group(1))
    detail("Version", str(layer_version))
    
    def update_permissions():
        try:
            lambda_client = boto3.client('lambda', region_name=region)
            
            # Check if permission already exists
            try:
                lambda_client.get_layer_version_policy(
                    LayerName=layer_name,
                    VersionNumber=layer_version
                )
                return "already_public"
            except lambda_client.exceptions.ResourceNotFoundException:
                # Expected exception if no policy exists
                pass
            
            # Add public permission
            lambda_client.add_layer_version_permission(
                LayerName=layer_name,
                VersionNumber=layer_version,
                StatementId='publish',
                Action='lambda:GetLayerVersion',
                Principal='*'
            )
            
            return "success"
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_message = e.response.get('Error', {}).get('Message', '')
            error("AWS Error", f"{error_code} - {error_message}")
            return None
        except Exception as e:
            error("Error", str(e))
            return None
    
    result = spinner("Updating layer permissions", update_permissions)
    
    if result == "already_public":
        info("Already public", "Skipping permission update")
        return True
    elif result == "success":
        status("Setting permissions", "Public access enabled")
        success("Layer public")
        return True
    else:
        return False


def write_metadata_to_dynamodb(metadata: dict) -> bool:
    """Write the collected layer metadata to the DynamoDB table."""
    subheader("Writing metadata")
    status("Target table", DYNAMODB_TABLE_NAME)
    
    # Basic validation
    required_keys = ['pk', 'sk', 'layer_arn', 'region', 'distribution', 'architecture', 'md5_hash']
    if not all(key in metadata and metadata[key] for key in required_keys):
        error("Invalid metadata", "Missing required fields")
        return False
        
    # Ensure publish_timestamp is set
    if 'publish_timestamp' not in metadata:
        metadata['publish_timestamp'] = datetime.now(timezone.utc).isoformat()
    
    def write_to_dynamo():
        try:
            response = write_item(metadata)
            return response
        except ValueError as e:
            error("Validation Error", str(e))
            return None
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == 'ResourceNotFoundException':
                error("AWS Error", str(e))
                detail("Detail", "Table not found in us-east-1")
            elif error_code == 'AccessDeniedException':
                error("AWS Error", str(e))
                detail("Detail", "Access denied - check IAM permissions")
            else:
                error("AWS Error", str(e))
            return None
        except Exception as e:
            error("Error", str(e))
            return None
    
    response = spinner("Writing to DynamoDB", write_to_dynamo)
    
    if response:
        status_code = response.get('ResponseMetadata', {}).get('HTTPStatusCode')
        if status_code == 200:
            success("Write successful", metadata['layer_arn'])
            return True
        else:
            error("Write failed", f"Status code: {status_code}")
            return False
    
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
    
    properties = {
        "Layer Name": layer_name,
        "Region": region,
        "ARN": layer_arn,
        "Content MD5": md5_hash,
        "Status": "Reused existing layer (identical content)" if skip_publish else "Published new layer version",
        "Artifact": artifact_name
    }
    
    if distribution and distribution != "default":
        properties["Distribution"] = distribution
    
    if architecture:
        properties["Architecture"] = architecture
    
    if collector_version:
        properties["Collector Version"] = collector_version
    
    summary = github_summary_table(properties, "Layer Publishing Summary")

    try:
        with open(github_step_summary, 'a') as f:
            f.write(summary + "\n")
    except Exception as e:
        error("Error writing to GITHUB_STEP_SUMMARY", str(e))


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
             error("Error writing to GITHUB_OUTPUT", str(e))


def check_and_repair_dynamodb(args, existing_layer_arn: str, md5_hash: str, layer_version_str: str):
    """Checks if metadata for an existing layer ARN is in DynamoDB and adds it if missing."""
    subheader("Checking DynamoDB")
    status("Checking metadata", existing_layer_arn)
    
    pk = existing_layer_arn
    sk = args.distribution
    
    def check_dynamodb():
        try:
            item = get_item(pk)
            return {'Item': item} if item else {}
        except ClientError as e:
            error("AWS Error", str(e))
            return None
        except Exception as e:
            error("Error", str(e))
            return None
    
    response = spinner("Checking DynamoDB", check_dynamodb)
    
    if response and 'Item' not in response:
        info("Metadata missing", "Will repair record")
        status("Repairing record", "Creating new metadata")
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
            'publish_timestamp': datetime.now(timezone.utc).isoformat(),
            'compatible_runtimes': args.runtimes.split() if args.runtimes else None
        }
        # Attempt to write the missing record
        write_success = write_metadata_to_dynamodb(metadata)
        if write_success:
            success("Repair complete")
        else:
            error("Repair failed")
    elif response:
        info("Metadata exists", "No repair needed")


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
    
    header("Lambda layer publisher")
    
    # Step 1: Construct layer name
    subheader("Constructing layer name")
    layer_name, arch_str, layer_version_str = construct_layer_name(
        args.layer_name, 
        args.architecture,
        args.distribution,
        args.layer_version,
        args.collector_version,
        args.release_group
    )
    
    # Step 2: Calculate MD5 hash
    subheader("Calculating MD5 hash")
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
        info("Publishing new layer version", "Creating new AWS Lambda layer")
        # Read build tags from environment variable
        build_tags_env = os.environ.get('PY_BUILD_TAGS', '') 
        layer_arn = publish_layer(
            layer_name,
            args.artifact_name,
            md5_hash,
            args.region,
            arch_str,
            args.runtimes,
            build_tags=build_tags_env
        )
        if layer_arn:
            # Step 5: Make layer public only if explicitly requested
            public_success = True
            if args.public:
                public_success = make_layer_public(layer_name, layer_arn, args.region)
            else:
                info("Keeping layer private", "Use --public to make it publicly accessible")
            
            if public_success:
                # Step 5.5: Write Metadata for NEW layer to DynamoDB
                info("Preparing metadata for new layer", "For DynamoDB storage")
                metadata = {
                    'pk': layer_arn,
                    'sk': args.distribution,
                    'layer_arn': layer_arn,
                    'region': args.region,
                    'base_name': args.layer_name,
                    'architecture': args.architecture,
                    'distribution': args.distribution,
                    'layer_version_str': layer_version_str,
                    'collector_version_input': args.collector_version,
                    'md5_hash': md5_hash,
                    'publish_timestamp': datetime.now(timezone.utc).isoformat(),
                    'public': args.public,  # Track whether the layer is public
                    # Store as a list instead of a set for DynamoDB List (L) type
                    'compatible_runtimes': args.runtimes.split() if args.runtimes else None 
                }
                dynamo_write_attempted = True
                dynamo_success = write_metadata_to_dynamodb(metadata)
                if not dynamo_success:
                     warning("Layer published and made public, but failed to write metadata to DynamoDB")
            else:
                warning(f"Layer {layer_arn} was published but could not be made public", 
                        "Skipping DynamoDB write")
        else:
             # Handle case where publishing failed
             error(f"Layer publishing failed for {layer_name} in {args.region}", "No ARN generated")
             sys.exit(1) # Exit if publish fails
             
    # --- Logic for skipped publish --- 
    elif skip_publish and existing_layer_arn:
        subheader("Reusing existing layer")
        info(f"Layer with MD5 {md5_hash} already exists", existing_layer_arn)
        layer_arn = existing_layer_arn # Ensure layer_arn is set to the existing one
        
        # Check if the metadata for this existing layer is in DynamoDB and repair if needed
        check_and_repair_dynamodb(args, existing_layer_arn, md5_hash, layer_version_str)
        # Note: We don't set dynamo_success here, as the goal was just checking/repairing.
        # The summary will correctly reflect 'Reused existing layer'.
        
    # --- End of skipped publish logic ---
    
    # Set layer_arn output for GitHub Actions
    if layer_arn:
        set_github_output("layer_arn", layer_arn)
        subheader("Layer processing complete")
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
        )
    else:
        # This case should ideally not be reached if publishing failed (exited) 
        # or if skip_publish was true but existing_layer_arn was somehow None
        error("No valid layer ARN available to generate summary")


if __name__ == "__main__":
    main()
