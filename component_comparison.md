# OpenTelemetry Lambda Collector Components Comparison

## Comparison between default and full builds

### Connectors

| Component Name | Default Build | Full Build |
|---------------|--------------|------------|
| spanmetrics |   | ✓ |

### Exporters

| Component Name | Default Build | Full Build |
|---------------|--------------|------------|
| debug | ✓ | ✓ |
| otlp | ✓ | ✓ |
| otlphttp | ✓ | ✓ |
| prometheusremotewrite | ✓ | ✓ |

### Extensions

| Component Name | Default Build | Full Build |
|---------------|--------------|------------|
| basicauth | ✓ | ✓ |
| sigv4auth | ✓ | ✓ |

### Processors

| Component Name | Default Build | Full Build |
|---------------|--------------|------------|
| attributes | ✓ | ✓ |
| batch | ✓ | ✓ |
| coldstart | ✓ | ✓ |
| decouple | ✓ | ✓ |
| filter | ✓ | ✓ |
| memorylimiter | ✓ | ✓ |
| probabilisticsampler | ✓ | ✓ |
| resource | ✓ | ✓ |
| span | ✓ | ✓ |

### Receivers

| Component Name | Default Build | Full Build |
|---------------|--------------|------------|
| otlp | ✓ | ✓ |
| telemetryapi | ✓ | ✓ |

