#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "boto3",
#     "click",
#     "termcolor",
# ]
# ///
"""
Interactive script to delete AWS Lambda layers matching a glob pattern across all regions.
This is a maintenance utility to clean up old or unneeded Lambda layers.

CAUTION: Use with care as layer deletion CANNOT be undone.
"""

import argparse
import boto3
import fnmatch
import sys
import termcolor
from botocore.exceptions import ClientError
from typing import Dict, List, Tuple

# List of regions to query - keep in sync with publish workflow
REGIONS = [
    "ca-central-1",
    "ca-west-1",
    "eu-central-1",
    "eu-central-2",
    "eu-north-1",
    "eu-south-1",
    "eu-south-2",
    "eu-west-1",
    "eu-west-2",
    "eu-west-3",
    "us-east-1",
    "us-east-2",
    "us-west-2"
]


def check_aws_cli() -> bool:
    """
    Check if AWS credentials are configured properly.
    """
    try:
        # Create a boto3 session to check if credentials are available
        session = boto3.Session()
        sts = session.client('sts')
        sts.get_caller_identity()
        return True
    except ClientError as e:
        print(f"Error with AWS credentials: {e}")
        return False


def find_matching_layers(pattern: str) -> List[Dict]:
    """
    Find all Lambda layers that match the given glob pattern across all regions.
    Returns a list of dicts containing layer info.
    """
    matching_layers = []
    
    print(f"Searching for layers matching '{pattern}' across {len(REGIONS)} regions...")
    
    # Verify AWS credentials
    if not check_aws_cli():
        print("AWS credentials not configured. Please run 'aws configure' or set AWS environment variables.")
        return matching_layers
    
    for region in REGIONS:
        print(f"Searching in {region}...")
        
        try:
            # Create a Lambda client for the region
            lambda_client = boto3.client('lambda', region_name=region)
            
            # List all layers
            paginator = lambda_client.get_paginator('list_layers')
            
            for page in paginator.paginate():
                for layer in page['Layers']:
                    layer_name = layer['LayerName']
                    
                    # Check if the layer name matches the pattern
                    if fnmatch.fnmatch(layer_name, pattern):
                        # Get all versions of this layer
                        try:
                            versions_paginator = lambda_client.get_paginator('list_layer_versions')
                            versions = []
                            
                            for version_page in versions_paginator.paginate(LayerName=layer_name):
                                for version in version_page['LayerVersions']:
                                    versions.append({
                                        'Version': version['Version'],
                                        'Arn': version['LayerVersionArn'],
                                        'CreatedDate': version.get('CreatedDate', 'Unknown')
                                    })
                            
                            matching_layers.append({
                                'Name': layer_name,
                                'Region': region,
                                'Versions': versions
                            })
                            
                            print(f"  Found: {layer_name} with {len(versions)} version(s)")
                        
                        except ClientError as e:
                            print(f"  Error getting versions for layer {layer_name}: {e}")
        
        except ClientError as e:
            print(f"Error searching in region {region}: {e}")
    
    return matching_layers


def delete_layers(layers: List[Dict], dry_run: bool = False) -> Tuple[int, int]:
    """
    Delete the specified layers and all their versions.
    Returns a tuple of (success_count, failure_count).
    """
    success_count = 0
    failure_count = 0
    
    if not layers:
        print("No layers to delete.")
        return (0, 0)
    
    for layer in layers:
        region = layer['Region']
        layer_name = layer['Name']
        versions = layer['Versions']
        
        if dry_run:
            print(f"[DRY RUN] Would delete layer {layer_name} in {region} with {len(versions)} version(s)")
            success_count += len(versions)
            continue
        
        try:
            lambda_client = boto3.client('lambda', region_name=region)
            
            for version in versions:
                version_number = version['Version']
                try:
                    lambda_client.delete_layer_version(
                        LayerName=layer_name,
                        VersionNumber=version_number
                    )
                    print(f"  Deleted: {layer_name} version {version_number} in {region}")
                    success_count += 1
                except ClientError as e:
                    print(f"  Error deleting {layer_name} version {version_number} in {region}: {e}")
                    failure_count += 1
        
        except ClientError as e:
            print(f"Error setting up client for region {region}: {e}")
            failure_count += len(versions)
    
    return (success_count, failure_count)


def print_layer_summary(layers: List[Dict]):
    """
    Print a summary of layers that will be deleted.
    """
    if not layers:
        print("No layers found matching the specified pattern.")
        return
    
    total_layers = len(layers)
    total_versions = sum(len(layer['Versions']) for layer in layers)
    
    print("\n" + "=" * 80)
    print(f"Found {total_layers} layer(s) with a total of {total_versions} version(s):")
    print("=" * 80)
    
    # Group by region for better organization
    layers_by_region = {}
    for layer in layers:
        region = layer['Region']
        if region not in layers_by_region:
            layers_by_region[region] = []
        layers_by_region[region].append(layer)
    
    # Print by region
    for region in sorted(layers_by_region.keys()):
        print(f"\nRegion: {termcolor.colored(region, 'cyan')}")
        print("-" * 80)
        
        for layer in layers_by_region[region]:
            layer_name = layer['Name']
            versions = layer['Versions']
            
            # Sort versions by number
            versions.sort(key=lambda x: x['Version'])
            
            print(f"  Layer: {termcolor.colored(layer_name, 'yellow')}")
            for version in versions:
                version_number = version['Version']
                created_date = version['CreatedDate']
                if isinstance(created_date, str):
                    created_date_str = created_date
                else:
                    created_date_str = created_date.strftime('%Y-%m-%d %H:%M:%S')
                
                print(f"    Version: {version_number} (Created: {created_date_str})")
            print()
    
    print("=" * 80)


def confirm_deletion(layers: List[Dict], force: bool = False) -> bool:
    """
    Ask for confirmation before deleting layers.
    """
    if force:
        return True
    
    if not layers:
        return False
    
    total_versions = sum(len(layer['Versions']) for layer in layers)
    
    print("\n" + "!" * 80)
    print(termcolor.colored(f"WARNING: You are about to delete {len(layers)} layer(s) with {total_versions} total version(s).", 'red', attrs=['bold']))
    print(termcolor.colored("This action CANNOT be undone!", 'red', attrs=['bold']))
    print("!" * 80 + "\n")
    
    confirmation = input("Type 'DELETE' to confirm: ")
    return confirmation == "DELETE"


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Delete AWS Lambda layers matching a glob pattern across all regions.",
        epilog="CAUTION: Layer deletion cannot be undone!"
    )
    parser.add_argument("pattern", 
                      help="Glob pattern to match layer names (e.g., 'opentelemetry-collector-*-0_119_0')")
    parser.add_argument("--dry-run", action="store_true",
                      help="Perform a dry run without actually deleting layers")
    parser.add_argument("--force", action="store_true",
                      help="Skip confirmation prompt (use with caution)")
    parser.add_argument("--regions", 
                      help="Comma-separated list of regions to check (default: all supported regions)")
    args = parser.parse_args()
    
    # Use specified regions if provided
    global REGIONS
    if args.regions:
        REGIONS = [region.strip() for region in args.regions.split(',')]
        print(f"Using specified regions: {', '.join(REGIONS)}")
    
    # Find matching layers
    matching_layers = find_matching_layers(args.pattern)
    
    # Print summary
    print_layer_summary(matching_layers)
    
    # Ask for confirmation
    if not args.dry_run:
        if not confirm_deletion(matching_layers, args.force):
            print("Deletion cancelled.")
            return
    
    # Delete layers
    success, failure = delete_layers(matching_layers, args.dry_run)
    
    # Print results
    if args.dry_run:
        print(f"\nDRY RUN: Would have deleted {success} layer version(s).")
    else:
        print(f"\nSuccessfully deleted {success} layer version(s).")
        if failure > 0:
            print(f"Failed to delete {failure} layer version(s).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(1) 
