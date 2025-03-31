#!/usr/bin/env python3
"""
get_release_info.py

Determines build tags, release tag, and release title based on distribution,
custom tags, collector version, and the distributions.yaml configuration file.

Reads inputs from environment variables:
- DISTRIBUTION: The selected distribution name.
- CUSTOM_BUILD_TAGS_INPUT: User-provided custom build tags.
- INPUT_COLLECTOR_VERSION: The collector version string (e.g., "v0.119.0").
- RELEASE_GROUP: The release group (e.g., "prod", "beta").
- DIST_YAML_PATH: Path to the distributions YAML file (defaults to 'config/distributions.yaml').

Sets GitHub Actions outputs:
- tag: The calculated release tag (e.g., "minimal-v0.119.0-prod").
- title: The calculated release title (e.g., "Release minimal v0.119.0 (prod)").
- build_tags: The calculated, comma-separated build tags string.
- collector_version: The input collector version (passed through).
- distribution: The input distribution name (passed through).
"""

import os
import sys
import yaml
from pathlib import Path

def set_output(name, value):
    """Sets a GitHub Actions output."""
    print(f"::set-output name={name}::{value}")

# --- Get inputs from environment variables ---
distribution = os.environ.get('DISTRIBUTION', 'default')
custom_tags_input = os.environ.get('CUSTOM_BUILD_TAGS_INPUT', '')
collector_version = os.environ.get('INPUT_COLLECTOR_VERSION', 'v0.0.0') # Default if missing
release_group = os.environ.get('RELEASE_GROUP', 'prod') # Get release group
# Default path is now config/distributions.yaml relative to repo root
repo_root = Path(__file__).parent.parent.resolve()
default_yaml_path = repo_root / "config" / "distributions.yaml"
yaml_path_str = os.environ.get('DIST_YAML_PATH', str(default_yaml_path))
yaml_path = Path(yaml_path_str)

print(f"Input Distribution: {distribution}")
print(f"Input Custom Tags: {custom_tags_input}")
print(f"Input Collector Version: {collector_version}")
print(f"Distribution Yaml Path: {yaml_path}")

# --- Determine Build Tags ---
build_tags = ''
if distribution == 'custom':
    if custom_tags_input:
        build_tags = custom_tags_input
        # Ensure lambdacomponents.custom is present
        if 'lambdacomponents.custom' not in build_tags:
            build_tags = f'lambdacomponents.custom,{build_tags}'
    else:
        build_tags = 'lambdacomponents.custom'
else:
    try:
        if not yaml_path.is_file():
             print(f"Error: Distribution YAML file not found at {yaml_path}", file=sys.stderr)
             sys.exit(1)

        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)
            if data and distribution in data:
                buildtags_list = data[distribution].get('buildtags', [])
            else:
                print(f'Error: Distribution "{distribution}" not found in {yaml_path}. Cannot determine build tags.', file=sys.stderr)
                # Fallback to default tags if distribution is missing, but error if default is also missing
                if data and 'default' in data:
                     print(f'Warning: Falling back to default distribution tags.', file=sys.stderr)
                     buildtags_list = data['default'].get('buildtags', [])
                else:
                     print(f'Error: Default distribution also not found in {yaml_path}.', file=sys.stderr)
                     sys.exit(1) # Exit if we can't determine tags
        
        build_tags = ",".join(buildtags_list) # Join list into comma-separated string

    except yaml.YAMLError as e:
        print(f'Error parsing {yaml_path}: {e}', file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f'Error reading {yaml_path}: {e}', file=sys.stderr)
        sys.exit(1)

print(f"Determined Build Tags: {build_tags}")

# --- Determine Release Tag and Title ---
# Clean collector version for tag/name (remove 'v' prefix)
version_tag_part = collector_version.lstrip('v')
# Always include release group in tag and title
release_tag = f"{distribution}-v{version_tag_part}-{release_group}"
release_title = f"Release {distribution} v{version_tag_part} ({release_group})"

print(f"Release Tag: {release_tag}")
print(f"Release Title: {release_title}")

# --- Set GitHub Actions outputs ---
set_output('tag', release_tag)
set_output('title', release_title)
set_output('build_tags', build_tags)
set_output('collector_version', collector_version) # Pass through
set_output('distribution', distribution) # Pass through
set_output('release_group', release_group) # Output release group

print("Successfully set outputs.")
