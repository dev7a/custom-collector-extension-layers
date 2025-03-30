#!/bin/bash
# build-extension-layer.sh: Simplified script to build OpenTelemetry Collector Lambda layer
# with custom components

set -e  # Exit on error

# Default values
UPSTREAM_REPO="open-telemetry/opentelemetry-lambda"
UPSTREAM_REF="main"
DISTRIBUTION="default"
ARCHITECTURE="amd64"  # Default architecture
BUILD_TAGS=""
CUSTOM_REPO_PATH=$(dirname "$(dirname "$(realpath "$0")")")
OUTPUT_DIR=""
SKIP_CLEANUP=false
COMPONENT_DIR="${CUSTOM_REPO_PATH}/components"
TEMP_DIR=""

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
    else
        echo "Temporary directory kept at: $TEMP_DIR"
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

# Convert to absolute path to avoid any issues
OUTPUT_DIR=$(realpath "$OUTPUT_DIR")

# Create temp directory and register cleanup handler
TEMP_DIR=$(mktemp -d)
trap cleanup EXIT

# Determine build tags based on distribution
get_build_tags() {
    local dist=$1
    local custom_tags=$2
    
    case "$dist" in
        minimal)
            echo "lambdacomponents.custom,lambdacomponents.receiver.otlp,lambdacomponents.processor.batch"
            ;;
        clickhouse)
            echo "lambdacomponents.custom,lambdacomponents.receiver.otlp,lambdacomponents.processor.batch,lambdacomponents.exporter.clickhouse"
            ;;
        clickhouse-otlphttp)
            echo "lambdacomponents.custom,lambdacomponents.receiver.otlp,lambdacomponents.processor.batch,lambdacomponents.exporter.clickhouse,lambdacomponents.exporter.otlphttp"
            ;;
        full)
            echo "lambdacomponents.custom,lambdacomponents.all"
            ;;
        custom)
            if [ -n "$custom_tags" ]; then
                local tags="$custom_tags"
                # Ensure lambdacomponents.custom is present if custom tags are provided
                if [[ "$tags" != *"lambdacomponents.custom"* ]]; then
                    tags="lambdacomponents.custom,$tags"
                fi
                echo "$tags"
            else
                # If distribution is custom but no tags provided, default to just the custom tag
                echo "lambdacomponents.custom"
            fi
            ;;
        default | *)
            echo "" # Default build with no special tags
            ;;
    esac
}

echo "Building with the following configuration:"
echo "Upstream Repository: ${UPSTREAM_REPO}"
echo "Upstream Ref: ${UPSTREAM_REF}"
echo "Distribution: ${DISTRIBUTION}"
echo "Architecture: ${ARCHITECTURE}"
echo "Output Directory: ${OUTPUT_DIR}"

# Step 1: Clone upstream repository
echo "Cloning upstream repository ${UPSTREAM_REPO} (ref: ${UPSTREAM_REF})..."
git clone --depth 1 "https://github.com/${UPSTREAM_REPO}.git" "$TEMP_DIR/upstream"
if [ $? -ne 0 ]; then
    echo "Failed to clone repository"
    exit 1
fi

cd "$TEMP_DIR/upstream"
git checkout "$UPSTREAM_REF"
if [ $? -ne 0 ]; then
    echo "Failed to checkout reference: $UPSTREAM_REF"
    exit 1
fi
cd "$CUSTOM_REPO_PATH"

# Step 2: Copy custom components to the upstream directory
echo "Overlaying custom components..."
if [ -d "$COMPONENT_DIR" ]; then
    cp -r "$COMPONENT_DIR/"* "$TEMP_DIR/upstream/"
    echo "Copied files from custom components directory"
else
    echo "No components directory found at $COMPONENT_DIR"
    exit 1
fi

# Step 3: Determine build tags
BUILDTAGS=$(get_build_tags "$DISTRIBUTION" "$BUILD_TAGS")
echo "Using build tags: $BUILDTAGS"

# Step 4: Add dependencies for custom components
echo "Changing to collector directory"
cd "$TEMP_DIR/upstream/collector"
if [ $? -ne 0 ]; then
    echo "Failed to change to collector directory"
    exit 1
fi

# Check if we need to add ClickHouse dependency
if [[ "$BUILDTAGS" == *"lambdacomponents.exporter.clickhouse"* ]]; then
    echo "Adding ClickHouse exporter dependency..."
    # Extract version from go.mod to ensure compatibility
    OTEL_VERSION=$(grep -E "go.opentelemetry.io/collector " go.mod | sed -E 's/.*v([0-9]+\.[0-9]+\.[0-9]+).*/v\1/')
    if [ -z "$OTEL_VERSION" ]; then
        OTEL_VERSION=$(grep -E "require go.opentelemetry.io/collector " go.mod | sed -E 's/.*v([0-9]+\.[0-9]+\.[0-9]+).*/v\1/')
    fi
    if [ -z "$OTEL_VERSION" ]; then
        echo "Could not detect OTEL version from go.mod, using default v0.119.0"
        OTEL_VERSION="v0.119.0"
    fi
    
    echo "Using OpenTelemetry version: $OTEL_VERSION"
    go get "github.com/open-telemetry/opentelemetry-collector-contrib/exporter/clickhouseexporter@$OTEL_VERSION"
    if [ $? -ne 0 ]; then
        echo "Failed to get ClickHouse exporter dependency"
        exit 1
    fi
    
    # Tidy up the module
    go mod tidy
    if [ $? -ne 0 ]; then
        echo "Failed to run go mod tidy"
        exit 1
    fi
fi

# Step 5: Build the collector
echo "Building the collector for $ARCHITECTURE architecture..."
if [ -n "$BUILDTAGS" ]; then
    GOARCH="$ARCHITECTURE" BUILDTAGS="$BUILDTAGS" make package
else
    GOARCH="$ARCHITECTURE" make package
fi

if [ $? -ne 0 ]; then
    echo "Failed to build collector"
    exit 1
fi

# Step 6: Copy the built layer to the output directory
echo "Copying built layer to output directory: $OUTPUT_DIR"
BUILD_FILE="$TEMP_DIR/upstream/collector/build/opentelemetry-collector-layer-$ARCHITECTURE.zip"

if [ ! -f "$BUILD_FILE" ]; then
    echo "Build file not found: $BUILD_FILE"
    echo "Contents of build directory:"
    ls -la "$TEMP_DIR/upstream/collector/build/"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"
cp "$BUILD_FILE" "$OUTPUT_DIR/"

if [ $? -ne 0 ]; then
    echo "Failed to copy build file to output directory"
    exit 1
fi

echo "Build complete! Layer available at: $OUTPUT_DIR/opentelemetry-collector-layer-$ARCHITECTURE.zip" 