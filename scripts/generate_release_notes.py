#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "boto3",
# ]
# ///
"""
Generate markdown release notes for a specific layer distribution and version
by querying the DynamoDB metadata store.
"""

import argparse
import sys
from decimal import Decimal

# Try importing boto3
try:
    import boto3
    from botocore.exceptions import ClientError
    from boto3.dynamodb.conditions import Key
except ImportError:
    print("Error: boto3 library not found. Please install it: pip install boto3", file=sys.stderr)
    sys.exit(1)

# DynamoDB Table Name (as per design doc)
DYNAMODB_TABLE_NAME = 'custom-collector-extension-layers'

# Helper to convert DynamoDB types (like Decimal) to standard Python types
def deserialize_item(item: dict) -> dict:
    """Deserialize DynamoDB item removing Decimals and Sets."""
    cleaned_item = {}
    for key, value in item.items():
        if isinstance(value, Decimal):
            # Convert Decimal to int if it's whole, otherwise float
            cleaned_item[key] = int(value) if value % 1 == 0 else float(value)
        elif isinstance(value, set):
             # Convert set to list for broader compatibility (e.g., JSON)
             # Sort for consistent output if needed, though order might not matter here
             cleaned_item[key] = list(value)
        else:
            cleaned_item[key] = value
    return cleaned_item

def generate_notes(distribution: str, collector_version: str, build_tags: str):
    """Queries DynamoDB and generates markdown release notes."""
    
    # Use default region resolution, but let AWS credentials handle the endpoint
    dynamodb = boto3.resource('dynamodb') 
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)
    items = []
    last_evaluated_key = None

    print(f"Querying DynamoDB table '{DYNAMODB_TABLE_NAME}' for pk={distribution}...", file=sys.stderr)
    
    # Query by PK (distribution)
    try:
        while True:
            query_args = {
                'KeyConditionExpression': Key('pk').eq(distribution)
            }
            if last_evaluated_key:
                query_args['ExclusiveStartKey'] = last_evaluated_key
                
            response = table.query(**query_args)
            items.extend(response.get('Items', []))
            
            last_evaluated_key = response.get('LastEvaluatedKey')
            if not last_evaluated_key:
                break # Exit the pagination loop
                
    except ClientError as e:
        print(f"Error: Failed querying DynamoDB for distribution '{distribution}': {e}", file=sys.stderr)
        # Depending on requirements, might want to exit or return partial notes
        return f"# Error\n\nFailed to query layer metadata from DynamoDB: {e}"
    except Exception as e:
        print(f"Error: An unexpected error occurred during DynamoDB query: {e}", file=sys.stderr)
        return f"# Error\n\nAn unexpected error occurred while querying DynamoDB: {e}"

    print(f"Found {len(items)} raw items for distribution. Filtering for collector version '{collector_version}'...", file=sys.stderr)

    # Filter results in Python for the specific collector version
    filtered_items = [
        deserialize_item(item) for item in items
        if item.get('collector_version_input') == collector_version
    ]

    print(f"Found {len(filtered_items)} items matching the collector version.", file=sys.stderr)

    # --- Generate Markdown Body --- 
    # Use literal \n for multi-line strings passed to gh release create --notes
    body_lines = []
    body_lines.append(f"## Release Details for {distribution} - Collector {collector_version}\n")

    body_lines.append("### Build Tags Used:\n")
    if build_tags:
         # Simple comma split and format as list
         tags_list = [f"- `{tag.strip()}`" for tag in build_tags.split(',') if tag.strip()]
         if tags_list:
             body_lines.extend(tags_list)
         else:
             body_lines.append("- Default (no specific tags identified)")
    else:
         body_lines.append("- Default (no specific tags)")
    body_lines.append("\n") # Add blank line for spacing


    body_lines.append("### Layer ARNs by Region and Architecture:\n")
    if not filtered_items:
        body_lines.append("No matching layers found in the metadata store for this specific version and distribution.\n")
    else:
        body_lines.append("| Region | Architecture | Layer ARN |")
        body_lines.append("|--------|--------------|-----------|")
        # Sort for consistent output (Region, then Architecture)
        sorted_items = sorted(filtered_items, key=lambda x: (x.get('region', 'zzzz'), x.get('architecture', 'zzzz'))) # Sort unknowns last
        for item in sorted_items:
            region = item.get('region', 'N/A')
            arch = item.get('architecture', 'N/A')
            arn = item.get('layer_arn', 'N/A')
            body_lines.append(f"| {region} | {arch} | `{arn}` |")
            
    # Join lines with literal newline character for GitHub notes
    return "\n".join(body_lines)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate GitHub Release notes for custom Lambda layers.")
    parser.add_argument("--distribution", required=True, help="Layer distribution name (used as DynamoDB PK)")
    parser.add_argument("--collector-version", required=True, help="Collector version string to filter layers (e.g., v0.119.0)")
    parser.add_argument("--build-tags", required=False, default="", help="Comma-separated build tags used for this release")
    args = parser.parse_args()

    notes = generate_notes(args.distribution, args.collector_version, args.build_tags)
    print(notes) # Print final markdown notes to stdout 