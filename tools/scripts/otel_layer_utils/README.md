# UI Utilities for CLI Tools

This directory contains utility modules for the OpenTelemetry Lambda Extension Layer tools, including `ui_utils.py` which provides consistent UI/UX formatting for CLI outputs.

## UI Utilities Module (`ui_utils.py`)

The `ui_utils.py` module offers a centralized approach to CLI output formatting using a Professional style with clear visual hierarchy.

### Why Use This Module?

1. **Consistency**: Ensures all CLI tools use the same visual style, creating a unified experience

2. **Maintainability**: Makes global style changes possible by updating a single file

3. **Reduced Duplication**: Eliminates hundreds of redundant formatting calls across scripts

4. **Semantics**: Shifts focus from formatting details to meaning in the output

5. **Flexibility**: Simplifies switching between different styles

### Available Functions

- **Section Headers**: `header()`, `subheader()`
- **Status Messages**: `status()`, `info()`, `detail()`
- **Result Indicators**: `success()`, `error()`, `warning()`
- **Progress Indicators**: `spinner()`, `async_spinner()`
- **Structured Output**: `property_list()`, `command_output()`
- **GitHub Actions**: `github_summary_table()`

### Usage Example

```python
from otel_layer_utils.ui_utils import (
    header, status, info, success, error, spinner
)

# Display section header
header("CONFIGURATION")

# Show key information
status("Repository", "github.com/open-telemetry/opentelemetry-lambda")
info("Branch", "main")

# Use spinner for long-running operations
def clone_repo():
    # Do something that takes time
    import time
    time.sleep(1)
    return "Success"

result = spinner("Cloning repository", clone_repo)

# Show operation result
if result == "Success":
    success("Clone complete")
else:
    error("Clone failed", "Unable to access repository")
```

### Visual Style

This module implements the "Professional" style with:

- Main headers in uppercase with dash prefix (`- HEADER`) in bright white
- Status messages with arrow prefix (`>`) in white
- Detailed information indented with arrow prefix (`>   `) in gray
- Success messages with checkmark (`✓`) in white
- Error messages with X (`✗`) in bright white
- All messages followed by pipe separator (`|`) and content

### Benefits for Scripts

Scripts using this module become:
- **More focused** on their logic rather than formatting
- **More consistent** across the project
- **Easier to maintain** with centralized styling
- **More flexible** to style changes without script edits

For a complete demonstration, see the example in `build_extension_layer.py`. 