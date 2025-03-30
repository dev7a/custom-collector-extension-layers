# Custom OpenTelemetry Lambda Layers

This repository contains customizations for OpenTelemetry Lambda Layers, building upon the [OpenTelemetry Lambda](https://github.com/open-telemetry/opentelemetry-lambda) project. It uses an "overlay" approach to maintain custom components while staying in sync with upstream changes.

## Overview

Instead of maintaining a direct fork of the OpenTelemetry Lambda repository (which would lead to complex merge conflicts), this repository contains only custom components and workflow definitions. During the build process, it:

1. Clones the upstream OpenTelemetry Lambda repository
2. Overlays our custom components on top
3. Builds and publishes custom Lambda layers with the extended functionality

This approach allows us to stay current with upstream changes while maintaining our custom integrations.

## Custom Components

Currently, the repository includes the following custom components:

- **ClickHouse Exporter**: Exports telemetry data to ClickHouse databases ([documentation](docs/clickhouse.md))

## Available Distributions

This repository can build several predefined distributions:

- `default`: Standard OpenTelemetry Collector
- `minimal`: A minimal distribution with just OTLP receivers and batch processors
- `clickhouse`: Distribution with ClickHouse exporter capabilities
- `clickhouse-otlphttp`: Distribution with ClickHouse and OTLP HTTP exporters
- `full`: Complete distribution with all available components
- `custom`: Build with custom-specified build tags

## Usage

### Publishing a Custom Layer

1. Navigate to the "Actions" tab in the GitHub repository
2. Select the "Publish Custom Collector Lambda layer" workflow
3. Click "Run workflow" and configure the options:
   - **Architecture**: Choose between `all`, `amd64`, or `arm64`
   - **AWS Region**: Select the AWS region(s) for publishing
   - **Distribution**: Select a predefined component set or `custom`
   - **Build Tags**: (Only for `custom` distribution) Comma-separated list of build tags
   - **Upstream Repo**: Repository to clone (default: `open-telemetry/opentelemetry-lambda`)
   - **Upstream Ref**: Git reference to use (branch, tag, commit SHA)

### Adding New Custom Components

To add a new custom component:

1. Create the corresponding `.go` file in the `components/collector/lambdacomponents/{component-type}/` directory
2. Add appropriate Go build tags at the top of the file:
   ```go
   //go:build lambdacomponents.custom && (lambdacomponents.all || lambdacomponents.{component-type}.all || lambdacomponents.{component-type}.{component-name})
   ```
3. Add documentation in the `docs/` directory
4. Update this README.md to include the new component
5. If needed, modify the workflow to add a new distribution option for your component

## Implementation Details

### Directory Structure

- `.github/workflows/`: GitHub Actions workflow definitions
- `components/`: Custom components to overlay onto the upstream repo
  - `collector/lambdacomponents/{component-type}/{component-name}.go`: Component implementations
- `docs/`: Documentation for custom components

### Workflow Architecture

The custom layers are built using a two-workflow approach:

1. **Publish Custom Collector Lambda layer**: Main workflow that:
   - Clones the upstream repository
   - Overlays custom components
   - Builds the collector with specified build tags
   - Uploads the resulting artifacts
   - Triggers the layer publishing process

2. **Custom Publish Lambda Layer**: Reusable workflow that:
   - Constructs the layer name based on inputs
   - Downloads the built layer artifact
   - Publishes the layer to AWS Lambda
   - Makes the layer public

## License

This project is licensed under the Apache 2.0 License - see the LICENSE file for details.
