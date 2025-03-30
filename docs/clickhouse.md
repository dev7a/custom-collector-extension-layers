# Adding ClickHouse Exporter to OpenTelemetry Collector Lambda Layer

This guide explains how to add ClickHouse exporter support to the OpenTelemetry Collector Lambda layer. ClickHouse is a high-performance, column-oriented database management system that allows you to store and query telemetry data efficiently.

**Important Note:** The build process described here relies on Go `replace` directives pointing to local directories within this repository structure. Therefore, these steps must be performed within a full clone (or your fork) of the `opentelemetry-lambda` repository. Creating a minimal standalone project requires copying these local dependency directories. Using a fork is the recommended approach for managing customizations.

## Prerequisites

Before starting, ensure you have:

- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) installed
- [AWS credentials](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html) configured
- [Go](https://golang.org/doc/install) installed (version 1.20 or newer)
- Git installed

## Step 1: Clone the Repository

If you haven't already, clone the OpenTelemetry Lambda repository or your fork:

```bash
# Clone the main repo (if contributing back)
# git clone https://github.com/open-telemetry/opentelemetry-lambda.git

# Clone your fork (recommended for customization)
git clone https://github.com/YOUR_USERNAME/opentelemetry-lambda.git
cd opentelemetry-lambda

# Optional: Configure upstream remote if using a fork
# git remote add upstream https://github.com/open-telemetry/opentelemetry-lambda.git
```

## Step 2: Create the ClickHouse Exporter Component

Create a new file in the `collector/lambdacomponents/exporter` directory:

```bash
touch collector/lambdacomponents/exporter/clickhouse.go
```

Add the following content to the file:

```go
//go:build lambdacomponents.custom && (lambdacomponents.all || lambdacomponents.exporter.all || lambdacomponents.exporter.clickhouse)
package exporter
import (
	"github.com/open-telemetry/opentelemetry-collector-contrib/exporter/clickhouseexporter"
	"go.opentelemetry.io/collector/exporter"
)
func init() {
	Factories = append(Factories, func(extensionId string) exporter.Factory {
		return clickhouseexporter.NewFactory()
	})
}
```

## Step 3: Add the ClickHouse Exporter Dependency

Add the ClickHouse exporter dependency to your Go modules:

```bash
cd collector
go get github.com/open-telemetry/opentelemetry-collector-contrib/exporter/clickhouseexporter@v0.119.0
cd ..
```

This command will download the ClickHouse exporter and all its dependencies, including the ClickHouse Go client.

## Step 4: Build the Collector with ClickHouse Support

Build the OpenTelemetry Collector Lambda layer, ensuring you include all necessary components using build tags.

**Minimal Build (ClickHouse Only):**
This build includes only the components needed for the simplest ClickHouse export pipeline (OTLP receiver, Batch processor, ClickHouse exporter).

```bash
cd collector
BUILDTAGS="lambdacomponents.custom,lambdacomponents.receiver.otlp,lambdacomponents.processor.batch,lambdacomponents.exporter.clickhouse" make publish-layer
cd ..
```

**Build with ClickHouse + OTLP HTTP Exporter (e.g., for Honeycomb):**
If you plan to export to other backends like Honeycomb using OTLP/HTTP alongside ClickHouse, include the `otlphttp` exporter as well.

```bash
cd collector
BUILDTAGS="lambdacomponents.custom,lambdacomponents.receiver.otlp,lambdacomponents.processor.batch,lambdacomponents.exporter.clickhouse,lambdacomponents.exporter.otlphttp" make publish-layer
cd ..
```

After the build completes, you'll get the ARN for your Lambda layer.

## Step 5: Configure Your Lambda Function

### Add the Layer to Your Lambda Function

Use the AWS CLI to add the layer to your Lambda function:

```bash
aws lambda update-function-configuration --function-name YOUR_FUNCTION_NAME --layers YOUR_NEW_LAYER_ARN
```

Or add it to your CloudFormation/SAM template:

```yaml
Properties:
  Layers:
    - YOUR_NEW_LAYER_ARN
```

### Create a ClickHouse Configuration File

Create a file named `collector.yaml` in your Lambda function package. This example focuses on exporting *traces* only. Remove or add pipelines for metrics/logs as needed.

```yaml
# collector.yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: "localhost:4318"

processors:
  batch:
    # Aggressive batch settings optimized for Lambda
    send_batch_size: 1000
    send_batch_max_size: 1000 # Ensure max size is also set
    timeout: 1s               # Flush frequently
    send_batch_on_shutdown: true # Flush before shutdown

exporters:
  # Use named instance for clarity
  clickhouse/main:
    endpoint: "${env:CLICKHOUSE_ENDPOINT}" # Use correct env var syntax
    database: "default" # Recommended for ClickHouse Cloud
    username: "default"
    password: "${env:CLICKHOUSE_PASSWORD}" # Use correct env var syntax
    timeout: 10s
    retry_on_failure:
      enabled: true
      initial_interval: 5s
      max_interval: 30s
      max_elapsed_time: 300s
    # Only include table names for pipelines you are using
    traces_table_name: "otel_spans"
    # logs_table_name: "otel_logs" # Add if using logs pipeline
    # metrics_table_name: "otel_metrics" # Add if using metrics pipeline

  # Optional: Add other exporters if included in your build
  # otlphttp/honeycomb:
  #   endpoint: "https://api.honeycomb.io"
  #   headers:
  #     x-honeycomb-team: "${env:HONEYCOMB_API_KEY}"
  #     x-honeycomb-dataset: "${env:HONEYCOMB_DATASET}"

service:
  telemetry:
    logs:
      level: "debug" # Helpful for debugging
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      # List all exporters for this pipeline
      exporters: [clickhouse/main] # Add otlphttp/honeycomb here if using
    # metrics: # Add if needed
    #   receivers: [otlp]
    #   processors: [batch]
    #   exporters: [clickhouse/main]
    # logs: # Add if needed
    #   receivers: [otlp]
    #   processors: [batch]
    #   exporters: [clickhouse/main]

```

### Set Environment Variables

Set the necessary environment variables for your Lambda function. Ensure the variable names match those used in `collector.yaml` (e.g., `CLICKHOUSE_ENDPOINT`, `CLICKHOUSE_PASSWORD`).

```bash
# Example for ClickHouse only
aws lambda update-function-configuration --function-name YOUR_FUNCTION_NAME --environment "Variables={OPENTELEMETRY_COLLECTOR_CONFIG_URI=/var/task/collector.yaml,CLICKHOUSE_ENDPOINT=your_clickhouse_endpoint_url,CLICKHOUSE_PASSWORD=your_clickhouse_password}"

# Example for ClickHouse + Honeycomb
# aws lambda update-function-configuration --function-name YOUR_FUNCTION_NAME --environment "Variables={OPENTELEMETRY_COLLECTOR_CONFIG_URI=/var/task/collector.yaml,CLICKHOUSE_ENDPOINT=your_clickhouse_endpoint_url,CLICKHOUSE_PASSWORD=your_clickhouse_password,HONEYCOMB_API_KEY=your_hc_key,HONEYCOMB_DATASET=your_hc_dataset}"

```

Or configure them in your CloudFormation/SAM template.

## ClickHouse Database Setup

The ClickHouse exporter will attempt to create the necessary tables (e.g., `otel_spans`) in the specified database if they don't exist and the user has permissions. However, it **will not create the database itself**.

1.  Ensure the database specified in your `collector.yaml` (e.g., `default`) **already exists** in your ClickHouse instance. Using the `default` database is often easiest with ClickHouse Cloud.
2.  Verify your ClickHouse user (`default` in the example) has permissions to `CREATE TABLE` in that database.
3.  Ensure your ClickHouse server is accessible from your Lambda function's network environment.

## Troubleshooting

### Dependency Issues

If you encounter dependency issues during the build, try:

```bash
go mod tidy
```

### Configuration Issues

If your Lambda is not sending data to ClickHouse:

1. Check the Lambda function logs for any errors
2. Verify that your ClickHouse server is accessible from the Lambda function
3. Check that the credentials and connection information are correct
4. Ensure the `OPENTELEMETRY_COLLECTOR_CONFIG_URI` environment variable points to the correct configuration file path

### Debugging Extension Startup Issues

If you see errors like `Extension.InitError` or need more detailed logs, increase the log verbosity by setting the `OPENTELEMETRY_EXTENSION_LOG_LEVEL` environment variable to `debug`.

```bash
# Example adding log level to ClickHouse only setup
aws lambda update-function-configuration --function-name YOUR_FUNCTION_NAME --environment "Variables={OPENTELEMETRY_COLLECTOR_CONFIG_URI=/var/task/collector.yaml,CLICKHOUSE_ENDPOINT=your_clickhouse_endpoint_url,CLICKHOUSE_PASSWORD=your_clickhouse_password,OPENTELEMETRY_EXTENSION_LOG_LEVEL=debug}"
```

Or add `OPENTELEMETRY_EXTENSION_LOG_LEVEL: debug` to the `Environment.Variables` section in your CloudFormation/SAM template.

Valid log levels are:
- `debug`: Most verbose, shows detailed debugging information
- `info`: Default level, shows informational messages
- `warn`: Only shows warning and error messages
- `error`: Only shows error messages

After setting this, invoke your Lambda function again to see more detailed error logs that can help diagnose the issue.

### Validating Configuration Files

Configuration errors are a common cause of startup failures. You can inspect whether your collector configuration file is properly formatted and accessible:

1. Check if the file path in `OPENTELEMETRY_COLLECTOR_CONFIG_URI` is correct
2. Make sure the YAML is valid with no syntax errors 
3. Verify all components (receivers, processors, exporters) referenced in your configuration are included in the `BUILDTAGS` used when building your Lambda layer.

## Advanced Configuration

For more advanced configuration options for the ClickHouse exporter, refer to the [official documentation](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/clickhouseexporter).