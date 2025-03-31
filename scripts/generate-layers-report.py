#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "boto3",
# ]
# ///
"""
Generate a markdown report of all OpenTelemetry Lambda layers across AWS regions.
"""

import argparse
import boto3
import fnmatch
import json
import os
import re
import tempfile
from botocore.exceptions import ClientError
from datetime import datetime
from typing import Dict, List, Optional, Tuple

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

# Known distributions
DISTRIBUTIONS = ["default", "minimal", "clickhouse", "clickhouse-otlphttp", "full", "custom"]

# Known architectures
ARCHITECTURES = ["amd64", "arm64"]


def get_distribution(layer_name: str) -> str:
    """
    Extract the distribution from the layer name.
    """
    if "-clickhouse-otlphttp-" in layer_name:
        return "clickhouse-otlphttp"
    elif "-clickhouse-" in layer_name:
        return "clickhouse"
    elif "-minimal-" in layer_name:
        return "minimal"
    elif "-full-" in layer_name:
        return "full"
    elif "-custom-" in layer_name:
        return "custom"
    else:
        return "default"


def get_architecture(layer_name: str) -> str:
    """
    Extract the architecture from the layer name.
    """
    if "-amd64-" in layer_name:
        return "amd64"
    elif "-arm64-" in layer_name:
        return "arm64"
    else:
        return "unknown"


def get_version(layer_name: str) -> str:
    """
    Extract the version from the layer name.
    """
    arch = get_architecture(layer_name)
    dist = get_distribution(layer_name)
    
    if arch != "unknown" and dist != "default":
        # Remove everything up to and including architecture and distribution
        pattern = f".*-{arch}-{dist}-"
        match = re.search(pattern, layer_name)
        if match:
            version_part = layer_name[match.end():]
            return version_part
    elif arch != "unknown":
        # Remove everything up to and including architecture
        pattern = f".*-{arch}-"
        match = re.search(pattern, layer_name)
        if match:
            version_part = layer_name[match.end():]
            return version_part
    
    return "unknown"


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


def fetch_layers(prefix: str = "opentelemetry-collector", pattern: str = None) -> Dict:
    """
    Fetch all layers with the given prefix from all regions.
    If a pattern is provided, only return layers that match the pattern.
    """
    layers_by_dist_arch = {}
    
    print(f"Querying layers across {len(REGIONS)} regions...")
    
    # Verify AWS credentials
    if not check_aws_cli():
        print("AWS credentials not configured. Please run 'aws configure' or set AWS environment variables.")
        return layers_by_dist_arch
    
    for region in REGIONS:
        print(f"Fetching layers from {region}...")
        
        try:
            # Create a Lambda client for the region
            lambda_client = boto3.client('lambda', region_name=region)
            
            # List layers with the prefix
            paginator = lambda_client.get_paginator('list_layers')
            
            for page in paginator.paginate():
                for layer in page['Layers']:
                    layer_name = layer['LayerName']
                    
                    # Check if the layer name starts with the prefix and matches the pattern if provided
                    if layer_name.startswith(prefix) and (pattern is None or fnmatch.fnmatch(layer_name, pattern)):
                        # Get additional details including timestamp for the latest version
                        try:
                            layer_arn = layer.get('LatestMatchingVersion', {}).get('LayerVersionArn', 'N/A')
                            layer_version = int(layer_arn.split(':')[-1]) if ':' in layer_arn else 1
                            layer_detail = lambda_client.get_layer_version(
                                LayerName=layer_name,
                                VersionNumber=layer_version
                            )
                            created_date = layer_detail.get('CreatedDate', '')
                            # Format the timestamp if it exists
                            if created_date:
                                if isinstance(created_date, str):
                                    timestamp = created_date
                                else:
                                    # It's likely a datetime object from boto3
                                    timestamp = created_date.strftime('%Y-%m-%d %H:%M:%S')
                            else:
                                timestamp = 'Unknown'
                        except Exception as e:
                            print(f"Error getting layer version details: {e}")
                            timestamp = 'Unknown'
                        
                        distribution = get_distribution(layer_name)
                        architecture = get_architecture(layer_name)
                        version = get_version(layer_name)
                        
                        # Organize by distribution and architecture
                        key = f"{distribution}:{architecture}"
                        if key not in layers_by_dist_arch:
                            layers_by_dist_arch[key] = []
                        
                        layers_by_dist_arch[key].append({
                            "region": region,
                            "arn": layer_arn,
                            "version": version,
                            "timestamp": timestamp
                        })
        
        except ClientError as e:
            print(f"Error fetching layers from {region}: {e}")
    
    return layers_by_dist_arch


def generate_report(layers_by_dist_arch: Dict, output_file: str = "LAYERS.md", pattern: str = None):
    """
    Generate a markdown report from the collected layer information.
    """
    with open(output_file, 'w') as f:
        f.write("# OpenTelemetry Lambda Layers Report\n")
        f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        if pattern:
            f.write(f"Filtered by pattern: `{pattern}`\n\n")
            
        f.write("This report lists all OpenTelemetry Lambda layers available across AWS regions.\n\n")
        
        f.write("## Available Layers by Distribution\n\n")
        
        if not layers_by_dist_arch:
            f.write("No layers found matching the specified criteria in any region.\n\n")
        else:
            # Create a section for each distribution in the specified order
            for dist in DISTRIBUTIONS:
                has_dist = False
                
                # Check if we have any layers for this distribution
                for key in layers_by_dist_arch.keys():
                    if key.startswith(f"{dist}:"):
                        has_dist = True
                        break
                
                if has_dist:
                    f.write(f"### {dist} Distribution\n\n")
                    
                    # Create tables for each architecture
                    for arch in ARCHITECTURES:
                        key = f"{dist}:{arch}"
                        
                        if key in layers_by_dist_arch and layers_by_dist_arch[key]:
                            f.write(f"#### {arch} Architecture\n\n")
                            f.write("| Region | Layer ARN | Version | Published |\n")
                            f.write("|--------|-----------|---------|----------|\n")
                            
                            # Sort by region for consistent output
                            for layer in sorted(layers_by_dist_arch[key], key=lambda x: x["region"]):
                                f.write(f"| {layer['region']} | `{layer['arn']}` | {layer['version']} | {layer['timestamp']} |\n")
                            
                            f.write("\n")
        
        f.write("## Usage Instructions\n\n")
        f.write("To use a layer in your Lambda function, add the ARN to your function's configuration:\n\n")
        f.write("```bash\n")
        f.write("aws lambda update-function-configuration --function-name YOUR_FUNCTION --layers ARN_FROM_TABLE\n")
        f.write("```\n\n")
        f.write("For more information, see the [documentation](https://github.com/open-telemetry/opentelemetry-lambda).\n")
    
    print(f"Report generated and saved to {output_file}")


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Generate a markdown report of OpenTelemetry Lambda layers")
    parser.add_argument("--prefix", default="opentelemetry-collector", 
                      help="Prefix for Lambda layer names to include in the report")
    parser.add_argument("--pattern", default=None,
                      help="Glob pattern to filter layers (e.g., '*clickhouse*')")
    parser.add_argument("--output", default="LAYERS.md", 
                      help="Output file path for the markdown report")
    parser.add_argument("--regions", 
                      help="Comma-separated list of regions to check (default: all supported regions)")
    args = parser.parse_args()
    
    # Use specified regions if provided
    global REGIONS
    if args.regions:
        REGIONS = [region.strip() for region in args.regions.split(',')]
        print(f"Using specified regions: {', '.join(REGIONS)}")
    
    # Fetch layers from all regions
    layers_by_dist_arch = fetch_layers(args.prefix, args.pattern)
    
    # Generate the report
    generate_report(layers_by_dist_arch, args.output, args.pattern)


if __name__ == "__main__":
    main() 