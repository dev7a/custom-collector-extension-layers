#!/usr/bin/env python3
import os
import re
from collections import defaultdict

# Path to the opentelemetry-lambda collector directory
COLLECTOR_DIR = "upstream/opentelemetry-lambda/collector"

def extract_component_name(file_path):
    """Extract the component name from a Go file path."""
    # E.g., from "lambdacomponents/exporter/otlp.go" -> "otlp"
    return os.path.splitext(os.path.basename(file_path))[0]

def extract_factory_name(file_path):
    """Extract the factory name from the Go file content."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
            # Look for the factory name in the import statement or the NewFactory call
            factory_match = re.search(r'import\s+\(\s*.*?"([^"]+)".*?\)', content, re.DOTALL)
            if factory_match:
                pkg_path = factory_match.group(1)
                # Extract the last part of the import path
                factory_name = pkg_path.split('/')[-1]
                return factory_name
            
            # Alternatively, look for NewFactory call
            factory_match = re.search(r'(\w+)\.NewFactory\(\)', content)
            if factory_match:
                return factory_match.group(1)
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
    return None

def is_component_file(file_path):
    """Check if the file is a component file with appropriate build tags."""
    try:
        with open(file_path, 'r') as f:
            first_line = f.readline().strip()
            # Check if the file has the lambdacomponents.custom and lambdacomponents.all build tags
            if "//go:build" in first_line and "lambdacomponents.custom" in first_line and (
                "lambdacomponents.all" in first_line or 
                ".exporter." in first_line or
                ".processor." in first_line or
                ".receiver." in first_line or
                ".extension." in first_line or
                ".connector." in first_line
            ):
                return True
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
    return False

def find_all_components():
    """Find all components that would be included in a full build."""
    components = defaultdict(list)
    
    # Find all component directories
    lambda_components_dir = os.path.join(COLLECTOR_DIR, "lambdacomponents")
    component_types = ["exporter", "processor", "receiver", "extension", "connector"]
    
    for component_type in component_types:
        component_dir = os.path.join(lambda_components_dir, component_type)
        if not os.path.exists(component_dir):
            print(f"Directory {component_dir} does not exist.")
            continue
        
        for file_name in os.listdir(component_dir):
            if file_name.endswith(".go") and file_name != "pkg.go":
                file_path = os.path.join(component_dir, file_name)
                if is_component_file(file_path):
                    component_name = extract_component_name(file_path)
                    components[component_type].append(component_name)
    
    # Sort components for consistent output
    for component_type in components:
        components[component_type].sort()
    
    return components

def generate_component_table(components):
    """Generate a markdown table of all components."""
    result = "# OpenTelemetry Lambda Collector Components\n\n"
    result += "## Components included in the full build\n\n"
    
    for component_type, component_list in sorted(components.items()):
        result += f"### {component_type.capitalize()}s\n\n"
        result += "| Component Name |\n"
        result += "|---------------|\n"
        for component in component_list:
            result += f"| {component} |\n"
        result += "\n"
    
    return result

def normalize_component_name(name):
    """Normalize component names to handle suffixes like 'processor', 'exporter', etc."""
    # Common suffixes for component types
    suffixes = ["processor", "exporter", "receiver", "extension", "connector"]
    
    # Remove suffix if present
    for suffix in suffixes:
        if name.endswith(suffix):
            return name[:-len(suffix)]
    
    return name

def extract_default_components():
    """Extract components defined in the default.go file."""
    default_components = {
        "receiver": ["otlp", "telemetryapi"],
        "exporter": ["debug", "otlp", "otlphttp", "prometheusremotewrite"],
        "processor": [
            "attributes", "filter", "memorylimiter", "probabilisticsampler", 
            "resource", "span", "coldstart", "decouple", "batch"
        ],
        "extension": ["sigv4auth", "basicauth"],
        "connector": []  # No connectors in default build
    }
    
    return default_components

def generate_comparison_table(full_components, default_components):
    """Generate a comparison table between full and default components."""
    result = "# OpenTelemetry Lambda Collector Components Comparison\n\n"
    result += "## Comparison between default and full builds\n\n"
    
    for component_type in sorted(set(list(full_components.keys()) + list(default_components.keys()))):
        result += f"### {component_type.capitalize()}s\n\n"
        
        # Create a set of all components of this type
        all_components = sorted(set(full_components.get(component_type, []) + default_components.get(component_type, [])))
        
        result += "| Component Name | Default Build | Full Build |\n"
        result += "|---------------|--------------|------------|\n"
        
        for component in all_components:
            in_default = component in default_components.get(component_type, [])
            in_full = component in full_components.get(component_type, [])
            
            result += f"| {component} | {'✓' if in_default else ' '} | {'✓' if in_full else ' '} |\n"
        
        result += "\n"
    
    return result

def main():
    print("Scanning OpenTelemetry Lambda collector for components...")
    
    # Get all components that would be included in a full build
    full_components = find_all_components()
    
    # Get components defined in default.go (hardcoded based on inspection)
    default_components = extract_default_components()
    
    # Generate comparison table
    comparison_table = generate_comparison_table(full_components, default_components)
    
    # Write comparison to file
    with open("component_comparison.md", "w") as f:
        f.write(comparison_table)
    
    print("Component comparison written to component_comparison.md")

if __name__ == "__main__":
    main() 