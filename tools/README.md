# Custom Collector Development Tools

This directory contains tools to help with local development and testing of custom OpenTelemetry Collector Lambda layers.

## test-distribution-locally.py

This script allows you to build and test custom collector distributions locally without having to run the full GitHub Actions workflow. It mimics the behavior of the workflow but only deploys to your local AWS region and uses the `local` release group to keep test layers separate from production ones.

### Prerequisites

- Python 3.6+ installed
- AWS CLI configured with credentials (IAM permissions for Lambda layer publishing)
- Required Python libraries: boto3 (`pip install boto3`)

### Usage

```bash
# Basic usage with default options
./test-distribution-locally.py

# Build and publish the clickhouse distribution
./test-distribution-locally.py --distribution clickhouse

# Build for arm64 architecture
./test-distribution-locally.py --architecture arm64

# Build only without publishing to AWS
./test-distribution-locally.py --skip-publish

# Use a different upstream repository or branch/tag
./test-distribution-locally.py --upstream-repo username/opentelemetry-lambda --upstream-ref my-branch

# Show verbose output during publishing (helpful for troubleshooting)
./test-distribution-locally.py --verbose

# Make the layer publicly accessible (by default layers are private)
./test-distribution-locally.py --public
```

### Command-line Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--distribution` | `-d` | `default` | Distribution to build (default, minimal, clickhouse, full) |
| `--architecture` | `-a` | `amd64` | Architecture to build for (amd64 or arm64) |
| `--upstream-repo` | `-r` | `open-telemetry/opentelemetry-lambda` | Upstream repository to use |
| `--upstream-ref` | `-b` | `main` | Upstream Git reference (branch, tag, SHA) |
| `--layer-name` | `-l` | `otel-ext-layer` | Base name for the Lambda layer |
| `--runtimes` | | `nodejs18.x nodejs20.x java17 python3.9 python3.10` | Space-delimited list of compatible runtimes |
| `--skip-publish` | | `false` | Skip publishing and only build the layer |
| `--verbose` | `-v` | `false` | Show detailed output during publishing (helpful for troubleshooting) |
| `--public` | | `false` | Make the layer publicly accessible (by default layers are private) |

### Understanding the Output

The script performs two main operations:

1. **Building the layer**: It clones the upstream repository, overlays custom components, and builds the collector layer just like the GitHub workflow.

2. **Publishing the layer**: It publishes the built layer to AWS Lambda in your current region with the `local` release group.

When publishing completes successfully, you'll get a layer ARN that you can use to attach to your test Lambda functions.

### Troubleshooting

If you encounter issues during publishing:

1. **AWS Credentials**: The script now automatically checks if your AWS credentials are properly configured before attempting to publish.
   
2. **Detailed Error Messages**: Use the `--verbose` flag to see detailed error messages from the AWS Lambda publishing process.
   
3. **Common Errors**:
   - `AccessDeniedException`: Your IAM user or role doesn't have permission to create Lambda layers
   - `ResourceLimitExceededException`: You've hit your Lambda layer quota limit
   - `InvalidParameterValueException`: Something is wrong with the layer contents or configuration

### Naming Convention

The published layers follow the same naming pattern as the main workflow but with `-local` appended:

```
otel-ext-layer-{architecture}-{distribution}-{version}-local
```

This naming helps distinguish test layers from production deployments.

### Example Output

```
Building the clickhouse distribution for amd64...
[Build output...]
Build successful. Layer file: /path/to/repo/build/collector-amd64.zip
Checking AWS credentials...
AWS credentials are configured for account: 123456789012
Publishing layer to AWS Lambda...
[Publish output...]
Successfully published clickhouse distribution to region us-east-1 as a 'local' release.
You can now test this layer by attaching it to a Lambda function.
``` 