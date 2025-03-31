#!/usr/bin/env python3
"""
check_layer_exists.py

This script checks if an AWS Lambda layer with a specific name and MD5 hash already exists.
It returns information about whether the layer should be published or can be reused.
"""

import argparse
import json
import sys
import subprocess
import os


def run_aws_command(cmd):
    """Run an AWS CLI command and return its output as JSON."""
    try:
        result = subprocess.run(
            cmd, shell=True, check=True, 
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
            text=True
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        if "ResourceNotFoundException" in e.stderr:
            return []
        print(f"Error running AWS command: {e}", file=sys.stderr)
        print(f"Command was: {cmd}", file=sys.stderr)
        print(f"Error output: {e.stderr}", file=sys.stderr)
        return []
    except json.JSONDecodeError:
        print(f"Failed to parse AWS command output as JSON", file=sys.stderr)
        return []


def check_layer_exists(layer_name, current_md5, region):
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
    
    if not existing_layers:
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


def main():
    parser = argparse.ArgumentParser(description='Check if Lambda layer exists')
    parser.add_argument('--layer-name', required=True, help='Name of the Lambda layer')
    parser.add_argument('--md5', required=True, help='MD5 hash of the layer content')
    parser.add_argument('--region', required=True, help='AWS region')
    
    args = parser.parse_args()
    
    skip_publish, existing_layer = check_layer_exists(
        args.layer_name, args.md5, args.region
    )
    
    # Output for GitHub Actions (using the new syntax)
    github_output = os.environ.get('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a') as f:
            if skip_publish:
                f.write(f"skip_publish=true\n")
                f.write(f"layer_arn={existing_layer}\n")
            else:
                f.write(f"skip_publish=false\n")
    
    # Also print for human readability
    if skip_publish:
        print("Layer with identical content already exists")
        print("No need to publish again. Using existing layer.")
    else:
        if existing_layer:
            print("Content has changed. Will publish new version.")
        else:
            print("No existing layer found, will publish new version.")


if __name__ == "__main__":
    main() 