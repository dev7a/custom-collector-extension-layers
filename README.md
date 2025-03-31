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

## Understanding Distributions

When running the "Publish Custom Collector Lambda layer" workflow, the **Distribution** option determines which set of OpenTelemetry Collector components are included in the layer. Here's a breakdown of what each option provides:

| Distribution          | Included Components / Build Tags                                                                                                | Description                                                                 |
| :-------------------- | :------------------------------------------------------------------------------------------------------------------------------ | :-------------------------------------------------------------------------- |
| `default`             | *(Upstream Default)*                                                                                                            | The standard set of components provided by the upstream OpenTelemetry Lambda. |
| `minimal`             | `lambdacomponents.custom`, OTLP Receiver, Batch Processor                                                                       | A lightweight layer with only essential OTLP receiving and batching.        |
| `clickhouse`          | `lambdacomponents.custom`, OTLP Receiver, Batch Processor, **ClickHouse Exporter**                                              | Includes the custom ClickHouse exporter for sending data to ClickHouse.     |
| `clickhouse-otlphttp` | `lambdacomponents.custom`, OTLP Receiver, Batch Processor, **ClickHouse Exporter**, **OTLP/HTTP Exporter**                       | Includes both the ClickHouse and standard OTLP/HTTP exporters.              |
| `full`                | `lambdacomponents.custom`, `lambdacomponents.all` (All custom *and* upstream components)                                        | A comprehensive layer including all available upstream and custom components. |
| `custom`              | `lambdacomponents.custom` + tags specified in **Build Tags** input                                                              | Allows specifying a custom set of components using Go build tags directly.    |

**Note:** All distributions except `default` automatically include the `lambdacomponents.custom` build tag, which is necessary for enabling the custom component overlay mechanism. The `custom` distribution allows fine-grained control by specifying exact build tags. Refer to the Go files in the `components/` directory and the upstream repository for details on available component tags.

## Upstream Default Components

The `default` distribution uses the standard component set provided by the upstream OpenTelemetry Lambda repository when no custom build tags are specified. This includes:

*   **Receivers:**
    *   `otlp`: OTLP gRPC/HTTP receiver.
    *   `telemetryapi`: AWS Lambda Telemetry API receiver.
*   **Exporters:**
    *   `debug`: Logs telemetry data to the console.
    *   `otlp`: OTLP gRPC exporter.
    *   `otlphttp`: OTLP HTTP exporter.
    *   `prometheusremotewrite`: Prometheus Remote Write exporter.
*   **Processors:**
    *   `attributes`: Modifies attributes based on rules.
    *   `filter`: Filters telemetry data based on criteria.
    *   `memory_limiter`: Prevents excessive memory usage.
    *   `probabilistic_sampler`: Samples traces probabilistically.
    *   `resource`: Modifies resource attributes.
    *   `span`: Modifies span attributes.
    *   `coldstart`: Detects Lambda cold starts (Lambda specific).
    *   `decouple`: Decouples pipeline processing for better Lambda performance (Lambda specific).
    *   `batch`: Batches telemetry data before export.
*   **Extensions:**
    *   `sigv4auth`: Provides AWS SigV4 authentication for exporters.
    *   `basicauth`: Provides Basic HTTP authentication for exporters/receivers.

For detailed configuration options of these components, please refer to the upstream [OpenTelemetry Lambda](https://github.com/open-telemetry/opentelemetry-lambda) and [OpenTelemetry Collector Contrib](https://github.com/open-telemetry/opentelemetry-collector-contrib) documentation.

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
