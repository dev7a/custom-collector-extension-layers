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
# import yaml # No longer needed directly
from pathlib import Path
from distribution_utils import load_distributions, resolve_build_tags, DistributionError # Import utilities

def set_output(name, value):
    """Sets a GitHub Actions output."""
    print(f"::set-output name={name}::{value}")

# --- Get inputs from environment variables ---
distribution = os.environ.get('DISTRIBUTION', 'default')
# custom_tags_input removed
collector_version = os.environ.get('INPUT_COLLECTOR_VERSION', 'v0.0.0') # Default if missing
release_group = os.environ.get('RELEASE_GROUP', 'prod') # Get release group
# Default path is now config/distributions.yaml relative to repo root
repo_root = Path(__file__).parent.parent.resolve()
default_yaml_path = repo_root / "config" / "distributions.yaml"
yaml_path_str = os.environ.get('DIST_YAML_PATH', str(default_yaml_path))
yaml_path = Path(yaml_path_str)

print(f"Input Distribution: {distribution}")
# print(f"Input Custom Tags: {custom_tags_input}") # Removed
print(f"Input Collector Version: {collector_version}")
print(f"Distribution Yaml Path: {yaml_path}")

# --- Determine Build Tags ---
build_tags = ''
# Removed 'if distribution == custom' block. Always use the utility functions.
# Use the utility functions for non-custom distributions
try:
    distributions_data = load_distributions(yaml_path)
    # Resolve tags using the utility, handles base inheritance
    buildtags_list = resolve_build_tags(distribution, distributions_data)
    build_tags = ",".join(buildtags_list)

except DistributionError as e:
    # Handle errors from the utility functions (e.g., file not found, dist not found, circular dep)
    print(f"Error processing distributions: {e}", file=sys.stderr)
    # Attempt fallback to 'default' distribution if the original one wasn't found
    if "not found in configuration" in str(e) and distribution != 'default':
        print(f"Warning: Distribution '{distribution}' not found, attempting fallback to 'default'.", file=sys.stderr)
        try:
            # We assume distributions_data was loaded if the error wasn't file not found/parse error
                # If loading failed initially, this fallback won't work, which is intended.
                buildtags_list = resolve_build_tags('default', distributions_data)
                build_tags = ",".join(buildtags_list)
                print(f"Successfully fell back to default tags: {build_tags}")
            except DistributionError as fallback_e:
                print(f"Error resolving fallback 'default' distribution: {fallback_e}", file=sys.stderr)
                sys.exit(1) # Exit if fallback also fails
            except NameError: # Handle case where distributions_data wasn't loaded
                 print(f"Error: Cannot fallback to default because distribution file could not be loaded initially.", file=sys.stderr)
             sys.exit(1)
        else:
            # Exit for other DistributionErrors (circular dep, invalid format, etc.) or if fallback failed
            sys.exit(1)
except Exception as e: # Catch any other unexpected errors
    print(f"An unexpected error occurred while getting build tags: {e}", file=sys.stderr)
    sys.exit(1)

print(f"Determined Build Tags: {build_tags}")

# --- Determine Release Tag and Title ---
# Clean collector version for tag/name (remove 'v' prefix)
version_tag_part = collector_version.lstrip('v')
# Always include release group in tag and title
release_tag = f"{distribution}-v{version_tag_part}-{release_group}"
# Use requested title format: Release distribution:<name> v<version> (<group>)
release_title = f"Release distribution:{distribution} v{version_tag_part} ({release_group})"

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
