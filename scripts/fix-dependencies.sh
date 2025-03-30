#!/bin/bash
# fix-dependencies.sh - Helper script to fix OpenTelemetry dependency issues

# Create a build constraint file to exclude problematic packages
create_build_constraints() {
    local build_dir="$1"
    
    echo "Creating build constraint file to exclude problematic packages..."
    
    # Create a directory for build constraints if it doesn't exist
    mkdir -p "$build_dir/collector/internal/buildconstraints"
    
    # Create a build constraint file
    cat > "$build_dir/collector/internal/buildconstraints/constraints.go" << 'CONSTRAINT'
// Exclude problematic packages during build
// This is auto-generated to work around dependency issues

package buildconstraints

// Configure build tags to exclude certain problematic imports
//go:build !test

import _ "unsafe" // for go:linkname
import _ "embed"  // for embedding files

//go:linkname excludeRequestTest go.opentelemetry.io/collector/exporter/internal/requesttest
var excludeRequestTest bool
CONSTRAINT

    # Modify main.go to import the build constraints
    if [ -f "$build_dir/collector/main.go" ]; then
        echo "Adding build constraint import to main.go..."
        
        # Create backup
        cp "$build_dir/collector/main.go" "$build_dir/collector/main.go.bak"
        
        # Add the import at the beginning of the imports block
        awk '
        /^import[[:space:]]*\(/ {
            print $0
            print "\t_ \"github.com/open-telemetry/opentelemetry-lambda/collector/internal/buildconstraints\" // Build constraints"
            next
        }
        { print }
        ' "$build_dir/collector/main.go.bak" > "$build_dir/collector/main.go"
    fi
}

# Detect pdata version
detect_pdata_version() {
    local collector_dir="$1"
    local default_version="v1.28.1" # Fallback
    local detected_version=""
    
    echo "Detecting pdata version..."
    
    # Check if pdata is defined in go.mod directly
    if grep -q "go.opentelemetry.io/collector/pdata" "$collector_dir/go.mod"; then
        # Extract version with regex
        detected_version=$(grep -E "go.opentelemetry.io/collector/pdata[[:space:]]+v[0-9]+\.[0-9]+\.[0-9]+" "$collector_dir/go.mod" | sed -E 's/.*v([0-9]+\.[0-9]+\.[0-9]+).*/v\1/')
        if [ -n "$detected_version" ]; then
            echo "Found pdata version in go.mod: $detected_version"
            return 0
        fi
    fi
    
    # Try running go list to find pdata's version
    if command -v go >/dev/null 2>&1; then
        pushd "$collector_dir" >/dev/null
        # Try to get pdata version from go list
        detected_version=$(go list -m go.opentelemetry.io/collector/pdata 2>/dev/null | grep -o "v[0-9]\+\.[0-9]\+\.[0-9]\+" || echo "")
        popd >/dev/null
        
        if [ -n "$detected_version" ]; then
            echo "Found pdata version via go list: $detected_version"
            return 0
        fi
    fi
    
    # If all else fails, use default
    echo "Could not detect pdata version, using default: $default_version"
    detected_version="$default_version"
    return 0
}

# Apply a comprehensive fix to the OTel dependencies
fix_otel_dependencies() {
    local build_dir="$1"
    local collector_dir="$build_dir/collector"
    
    cd "$collector_dir"
    
    echo "Applying fixes to collector codebase..."
    
    # Create build constraints
    create_build_constraints "$build_dir"
    
    # Remove debug exporter
    if [ -f "lambdacomponents/exporter/debug.go" ]; then
        echo "Disabling debug.go"
        mv "lambdacomponents/exporter/debug.go" "lambdacomponents/exporter/debug.go.disabled"
        echo '// Package exporter contains exporter factories
// This file is disabled due to compatibility issues
package exporter' > "lambdacomponents/exporter/debug.go"
    fi
    
    # Find and remove debugexporter references
    if [ -f "lambdacomponents/default.go" ]; then
        echo "Fixing default.go"
        grep -v "debugexporter" "lambdacomponents/default.go" > "lambdacomponents/default.go.new"
        mv "lambdacomponents/default.go.new" "lambdacomponents/default.go"
    fi
    
    # Detect OpenTelemetry version
    OTEL_VERSION=$(grep -E "go.opentelemetry.io/collector " go.mod | sed -E 's/.*v([0-9]+\.[0-9]+\.[0-9]+).*/v\1/')
    if [ -z "$OTEL_VERSION" ]; then
        OTEL_VERSION=$(grep -E "require go.opentelemetry.io/collector " go.mod | sed -E 's/.*v([0-9]+\.[0-9]+\.[0-9]+).*/v\1/')
    fi
    if [ -z "$OTEL_VERSION" ]; then
        OTEL_VERSION="v0.119.0" # Default fallback
    fi
    
    # Detect pdata version - this will set PDATA_VERSION
    PDATA_VERSION=$(detect_pdata_version "$collector_dir")
    if [ -z "$PDATA_VERSION" ]; then
        PDATA_VERSION="v1.28.1" # Default fallback if detection fails
    fi
    
    # Create patch for go.mod to force consistent versions
    echo "Creating go.mod patches..."
    
    # Debug: Check the contents of the original go.mod file
    echo "Original go.mod contents:"
    cat go.mod
    
    # Create a new go.mod file with correct formatting
    # Temporary file for the new go.mod
    TMP_MOD_FILE=$(mktemp)
    
    # Extract the module line and any valid directives from the original go.mod
    # Then add our replace directives
    {
        # Extract the first part of go.mod up to and including the last go line
        sed -n '1,/^go /p' go.mod
        
        # Add a blank line and our replace directives
        echo ""
        echo "// Consistent versioning for OpenTelemetry packages"
        echo "replace go.opentelemetry.io/collector => go.opentelemetry.io/collector $OTEL_VERSION"
        echo "replace go.opentelemetry.io/collector/component => go.opentelemetry.io/collector/component $OTEL_VERSION"
        echo "replace go.opentelemetry.io/collector/config => go.opentelemetry.io/collector/config $OTEL_VERSION"
        echo "replace go.opentelemetry.io/collector/consumer => go.opentelemetry.io/collector/consumer $OTEL_VERSION"
        echo "replace go.opentelemetry.io/collector/exporter => go.opentelemetry.io/collector/exporter $OTEL_VERSION"
        echo "replace go.opentelemetry.io/collector/extension => go.opentelemetry.io/collector/extension $OTEL_VERSION"
        echo "replace go.opentelemetry.io/collector/processor => go.opentelemetry.io/collector/processor $OTEL_VERSION"
        echo "replace go.opentelemetry.io/collector/receiver => go.opentelemetry.io/collector/receiver $OTEL_VERSION"
        echo "replace go.opentelemetry.io/collector/connector => go.opentelemetry.io/collector/connector $OTEL_VERSION"
        echo "replace go.opentelemetry.io/collector/pdata => go.opentelemetry.io/collector/pdata $PDATA_VERSION"
        
        # Add any require statements from the original
        sed -n '/^require/,/^\)/p' go.mod
    } > "$TMP_MOD_FILE"
    
    # Backup the original go.mod
    cp go.mod go.mod.bak
    
    # Replace with the new file
    mv "$TMP_MOD_FILE" go.mod
    
    # Debug: Show the result
    echo "Modified go.mod contents:"
    cat go.mod
    
    # Also patch lambdacomponents go.mod if it exists
    if [ -f "lambdacomponents/go.mod" ]; then
        echo "Patching lambdacomponents/go.mod..."
        TMP_COMP_MOD_FILE=$(mktemp)
        
        # Extract the first part of lambdacomponents/go.mod up to and including the last go line
        {
            sed -n '1,/^go /p' lambdacomponents/go.mod
            
            # Add a blank line and our replace directives
            echo ""
            echo "// Consistent versioning for OpenTelemetry packages"
            echo "replace go.opentelemetry.io/collector => go.opentelemetry.io/collector $OTEL_VERSION"
            echo "replace go.opentelemetry.io/collector/component => go.opentelemetry.io/collector/component $OTEL_VERSION"
            echo "replace go.opentelemetry.io/collector/config => go.opentelemetry.io/collector/config $OTEL_VERSION"
            echo "replace go.opentelemetry.io/collector/consumer => go.opentelemetry.io/collector/consumer $OTEL_VERSION"
            echo "replace go.opentelemetry.io/collector/exporter => go.opentelemetry.io/collector/exporter $OTEL_VERSION"
            echo "replace go.opentelemetry.io/collector/extension => go.opentelemetry.io/collector/extension $OTEL_VERSION"
            echo "replace go.opentelemetry.io/collector/processor => go.opentelemetry.io/collector/processor $OTEL_VERSION"
            echo "replace go.opentelemetry.io/collector/receiver => go.opentelemetry.io/collector/receiver $OTEL_VERSION"
            echo "replace go.opentelemetry.io/collector/connector => go.opentelemetry.io/collector/connector $OTEL_VERSION"
            echo "replace go.opentelemetry.io/collector/pdata => go.opentelemetry.io/collector/pdata $PDATA_VERSION"
            
            # Add any require statements from the original
            sed -n '/^require/,/^\)/p' lambdacomponents/go.mod
        } > "$TMP_COMP_MOD_FILE"
        
        # Backup the original lambdacomponents/go.mod
        cp lambdacomponents/go.mod lambdacomponents/go.mod.bak
        
        # Replace with the new file
        mv "$TMP_COMP_MOD_FILE" lambdacomponents/go.mod
        
        # Debug: Show the result
        echo "Modified lambdacomponents/go.mod contents:"
        cat lambdacomponents/go.mod
    fi
    
    echo "Dependency fixes applied"
}

# Execute if run directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [ -z "$1" ]; then
        echo "Usage: $0 <build_directory>"
        exit 1
    fi
    
    fix_otel_dependencies "$1"
fi
