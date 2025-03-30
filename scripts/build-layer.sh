#!/bin/bash

# build-layer.sh: Build a custom OpenTelemetry collector Lambda layer
# This script implements the overlay approach for building custom components
# with the upstream OpenTelemetry Lambda repository.

set -e  # Exit on error

# Default values
UPSTREAM_REPO="open-telemetry/opentelemetry-lambda"
UPSTREAM_REF="main"
DISTRIBUTION="default"
ARCHITECTURE="amd64"  # Default architecture
BUILD_TAGS=""
CUSTOM_REPO_PATH=$(dirname "$(dirname "$(realpath "$0")")")
TEMP_DIR=""
SKIP_CLEANUP=false

# Function to display usage information
usage() {
    echo "Usage: $0 [options]"
    echo
    echo "Options:"
    echo "  -r, --upstream-repo REPO     Upstream repository (default: ${UPSTREAM_REPO})"
    echo "  -b, --upstream-ref REF       Upstream Git reference (branch, tag, SHA) (default: ${UPSTREAM_REF})"
    echo "  -d, --distribution DIST      Distribution name (default, minimal, clickhouse, clickhouse-otlphttp, full, custom) (default: ${DISTRIBUTION})"
    echo "  -a, --arch ARCH              Architecture (amd64, arm64) (default: ${ARCHITECTURE})"
    echo "  -t, --build-tags TAGS        Custom build tags (comma-separated, only used with -d custom)"
    echo "  -o, --output-dir DIR         Output directory for built layer (default: current directory)"
    echo "  -k, --keep-temp              Keep temporary build directory"
    echo "  -h, --help                   Show this help message"
    echo
    echo "Examples:"
    echo "  $0 -d clickhouse -a arm64                    # Build clickhouse distribution for arm64"
    echo "  $0 -d custom -t 'lambdacomponents.custom,lambdacomponents.exporter.clickhouse'  # Build with custom tags"
}

# Function to cleanup temporary directory
cleanup() {
    if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ] && [ "$SKIP_CLEANUP" = false ]; then
        echo "Cleaning up temporary directory: $TEMP_DIR"
        rm -rf "$TEMP_DIR"
    fi
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    key="$1"
    case $key in
        -r|--upstream-repo)
            UPSTREAM_REPO="$2"
            shift 2
            ;;
        -b|--upstream-ref)
            UPSTREAM_REF="$2"
            shift 2
            ;;
        -d|--distribution)
            DISTRIBUTION="$2"
            shift 2
            ;;
        -a|--arch)
            ARCHITECTURE="$2"
            shift 2
            ;;
        -t|--build-tags)
            BUILD_TAGS="$2"
            shift 2
            ;;
        -o|--output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -k|--keep-temp)
            SKIP_CLEANUP=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Set default OUTPUT_DIR if not specified
if [ -z "$OUTPUT_DIR" ]; then
    OUTPUT_DIR="$(pwd)"
fi

# Create temp directory and register cleanup handler
TEMP_DIR=$(mktemp -d)
trap cleanup EXIT

# Function to determine build tags based on distribution
get_build_tags() {
    local dist=$1
    local custom_tags=$2
    local tags=""
    
    case "$dist" in
        minimal)
            tags="lambdacomponents.custom,lambdacomponents.receiver.otlp,lambdacomponents.processor.batch"
            ;;
        clickhouse)
            tags="lambdacomponents.custom,lambdacomponents.receiver.otlp,lambdacomponents.processor.batch,lambdacomponents.exporter.clickhouse"
            ;;
        clickhouse-otlphttp)
            tags="lambdacomponents.custom,lambdacomponents.receiver.otlp,lambdacomponents.processor.batch,lambdacomponents.exporter.clickhouse,lambdacomponents.exporter.otlphttp"
            ;;
        full)
            tags="lambdacomponents.custom,lambdacomponents.all"
            ;;
        custom)
            if [ -n "$custom_tags" ]; then
                tags="$custom_tags"
                # Ensure lambdacomponents.custom is present if custom tags are provided
                if [[ "$tags" != *"lambdacomponents.custom"* ]]; then
                    tags="lambdacomponents.custom,$tags"
                fi
            else
                # If distribution is custom but no tags provided, default to just the custom tag
                tags="lambdacomponents.custom"
            fi
            ;;
        default | *)
            tags=""
            ;;
    esac
    
    echo "$tags"
}

# Step 1: Clone upstream repository
echo "Cloning upstream repository ${UPSTREAM_REPO} (ref: ${UPSTREAM_REF})..."
git clone --depth 1 --branch "$UPSTREAM_REF" "https://github.com/${UPSTREAM_REPO}.git" "$TEMP_DIR/upstream" 2>/dev/null || \
git clone --depth 1 "https://github.com/${UPSTREAM_REPO}.git" "$TEMP_DIR/upstream" && cd "$TEMP_DIR/upstream" && git checkout "$UPSTREAM_REF" && cd - >/dev/null

# Step 2: Copy custom components to the upstream directory
echo "Overlaying custom components..."
if [ -d "$CUSTOM_REPO_PATH/components" ]; then
    cp -r "$CUSTOM_REPO_PATH/components/"* "$TEMP_DIR/upstream/"
    echo "Copied files from custom components directory"
    find "$TEMP_DIR/upstream/collector/lambdacomponents" -type f -name "*.go" | sort
else
    echo "No components directory found in $CUSTOM_REPO_PATH"
    exit 1
fi

# Step 3: Fix dependencies and build
cd "$TEMP_DIR/upstream/collector"

echo "Detecting OpenTelemetry version from upstream go.mod..."
# Try to extract OTEL version from go.mod
OTEL_VERSION=$(grep -E "go.opentelemetry.io/collector " go.mod | sed -E 's/.*v([0-9]+\.[0-9]+\.[0-9]+).*/v\1/')

# Check if we found a version
if [ -z "$OTEL_VERSION" ]; then
    # Try alternate pattern with require syntax
    OTEL_VERSION=$(grep -E "require go.opentelemetry.io/collector " go.mod | sed -E 's/.*v([0-9]+\.[0-9]+\.[0-9]+).*/v\1/')
fi

# If still not found, fall back to a default version
if [ -z "$OTEL_VERSION" ]; then
    echo "Could not detect OTEL version from go.mod, using default v0.119.0"
    OTEL_VERSION="v0.119.0"
fi

echo "Using OpenTelemetry version: $OTEL_VERSION"

# Apply comprehensive dependency fixes using our helper script
echo "Applying comprehensive dependency fixes..."
"$CUSTOM_REPO_PATH/scripts/fix-dependencies.sh" "$TEMP_DIR/upstream"

# Fix Go Module Dependencies
echo "Installing OpenTelemetry modules with consistent versions..."

# Initialize dependency list
OTEL_DEPS=(
    "go.opentelemetry.io/collector@$OTEL_VERSION"
    "go.opentelemetry.io/collector/exporter@$OTEL_VERSION"
    "go.opentelemetry.io/collector/processor@$OTEL_VERSION"
    "go.opentelemetry.io/collector/receiver@$OTEL_VERSION"
    "go.opentelemetry.io/collector/extension@$OTEL_VERSION"
    "go.opentelemetry.io/collector/connector@$OTEL_VERSION"
    "go.opentelemetry.io/collector/pdata@$OTEL_VERSION"
    "go.opentelemetry.io/collector/consumer@$OTEL_VERSION"
)

# Install dependencies in the main module
echo "Installing dependencies in collector module..."
for dep in "${OTEL_DEPS[@]}"; do
    echo "Installing $dep"
    go get "$dep"
done

# Also install specific test packages that might cause issues
go get go.opentelemetry.io/collector/component/componenttest@$OTEL_VERSION
go get go.opentelemetry.io/collector/consumer/consumertest@$OTEL_VERSION
go get go.opentelemetry.io/collector/pdata/testdata@$OTEL_VERSION

# Remove debugexporter usage if it causes problems
if grep -q "debugexporter" lambdacomponents/exporter/debug.go 2>/dev/null || grep -q "debugexporter" lambdacomponents/default.go 2>/dev/null; then
    echo "Found debug exporter usage, handling potential incompatibility..."
    
    # Check if the problematic package exists
    if ! go list -m go.opentelemetry.io/collector/exporter/internal/requesttest &>/dev/null; then
        echo "Warning: Requesttest package not found - modifying files to remove debug exporter usage"
        
        # Disable debug.go if it exists
        if [ -f "lambdacomponents/exporter/debug.go" ]; then
            echo "Disabling debug exporter in lambdacomponents/exporter/debug.go"
            # Completely comment out the entire file
            sed -i.bak 's/^/\/\/ DISABLED: /g' lambdacomponents/exporter/debug.go
            # For safety, also rename the file so it won't be compiled
            mv lambdacomponents/exporter/debug.go lambdacomponents/exporter/debug.go.disabled
            touch lambdacomponents/exporter/debug.go
            echo "// This file has been disabled to avoid dependency conflicts" > lambdacomponents/exporter/debug.go
            echo "// The original content is in debug.go.disabled" >> lambdacomponents/exporter/debug.go
            echo "package exporter" >> lambdacomponents/exporter/debug.go
        fi
        
        # Also check and modify default.go which might import debugexporter
        if [ -f "lambdacomponents/default.go" ]; then
            echo "Modifying lambdacomponents/default.go to remove debug exporter usage"
            # Create backup
            cp lambdacomponents/default.go lambdacomponents/default.go.bak
            # Only comment out specific lines with debugexporter
            grep -v "debugexporter" lambdacomponents/default.go > lambdacomponents/default.go.new
            mv lambdacomponents/default.go.new lambdacomponents/default.go
        fi
        
        # Check for any other Go files (not go.mod/go.sum) that might reference debugexporter
        GO_FILES=$(find lambdacomponents -name "*.go" -not -name "debug.go" | xargs grep -l "debugexporter" 2>/dev/null || true)
        if [ -n "$GO_FILES" ]; then
            echo "Found other Go files with debugexporter references:"
            for file in $GO_FILES; do
                echo "  - $file"
                # Create backup
                cp "$file" "$file.bak"
                # Remove lines with debugexporter
                grep -v "debugexporter" "$file" > "$file.new"
                mv "$file.new" "$file"
            done
        fi
    fi
fi

# Update the lambdacomponents go.mod if it exists
if [ -f "./lambdacomponents/go.mod" ]; then
    echo "Updating lambdacomponents module..."
    cd ./lambdacomponents
    
    # Install dependencies in the lambdacomponents module
    for dep in "${OTEL_DEPS[@]}"; do
        echo "Installing $dep in lambdacomponents"
        go get "$dep"
    done
    cd ..
fi

# Tidy Go modules
echo "Running go mod tidy on collector module..."
go mod tidy

# Tidy LambdaComponents module if it exists
if [ -f "./lambdacomponents/go.mod" ]; then
    echo "Running go mod tidy on lambdacomponents module..."
    cd ./lambdacomponents
    go mod tidy
    cd ..
fi

# Step 4: Build the collector
echo "Building the collector..."
BUILDTAGS=$(get_build_tags "$DISTRIBUTION" "$BUILD_TAGS")
if [ -n "$BUILDTAGS" ]; then
    echo "Using build tags: $BUILDTAGS"
    make package "GOARCH=$ARCHITECTURE" "BUILDTAGS=$BUILDTAGS"
else
    echo "Using default build (no special tags)"
    make package "GOARCH=$ARCHITECTURE"
fi

# Step 5: Copy the built layer to the output directory
echo "Copying built layer to output directory: $OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"
cp build/opentelemetry-collector-layer-$ARCHITECTURE.zip "$OUTPUT_DIR/"

echo "Build complete! Layer available at: $OUTPUT_DIR/opentelemetry-collector-layer-$ARCHITECTURE.zip"
