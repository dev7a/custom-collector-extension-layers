# Distribution Management Refactoring Plan

## Problem

Currently, defining and managing build distributions for the custom collector layer involves duplicated logic across multiple files:

1.  **`scripts/build_extension_layer.py`**:
    *   Hardcoded `choices` in the argument parser.
    *   Hardcoded `tags_map` dictionary in the `get_build_tags` function.
2.  **`.github/workflows/publish-custom-layer-collector.yml`**:
    *   Hardcoded `options` list for the `distribution` workflow input.
    *   A shell `case` statement in the `create-github-release` job that replicates the tag mapping logic.

Adding or modifying a distribution requires updating all these locations, increasing the risk of inconsistencies and errors.

## Proposed Solution: Centralized Configuration

To simplify management and reduce redundancy, we propose centralizing the distribution definitions in a single configuration file: `config/distributions.yaml`.

### 1. `config/distributions.yaml` File

This YAML file will serve as the single source of truth for all distributions. Each top-level key will be the distribution name (used in scripts and workflows), and the value will be an object containing its description and the corresponding Go build tags under the `buildtags` key as a list.

```yaml
# config/distributions.yaml
default:
  description: "Standard upstream components"
  buildtags: [] # Special case: Empty list means no custom tags
minimal:
  description: "OTLP receiver, Batch processor"
  buildtags:
    - lambdacomponents.custom
    - lambdacomponents.receiver.otlp
    - lambdacomponents.processor.batch
clickhouse:
  description: "Minimal + ClickHouse exporter"
  buildtags:
    - lambdacomponents.custom
    - lambdacomponents.receiver.otlp
    - lambdacomponents.processor.batch
    - lambdacomponents.exporter.clickhouse
# ... other existing distributions ...
full:
  description: "All available upstream and custom components"
  buildtags:
    - lambdacomponents.custom
    - lambdacomponents.all
# --- Example of adding a new distribution ---
# spanmetrics-lite:
#   description: "SpanMetrics connector, OTLP receiver, Batch/Decouple processors, OTLP/HTTP exporter"
#   buildtags:
#     - lambdacomponents.custom
#     - lambdacomponents.connector.spanmetrics
#     - lambdacomponents.receiver.otlp
#     - lambdacomponents.processor.batch
#     - lambdacomponents.processor.decouple
#     - lambdacomponents.exporter.otlphttp
```

### 2. Modifying `scripts/build_extension_layer.py`

*   **Dependencies:** Add `PyYAML` to handle YAML parsing. This might require adding a `requirements.txt` or similar mechanism if not already present.
*   **Parsing:** Load and parse `config/distributions.yaml` at the beginning of the script.
*   **Argument Parser:** Dynamically populate the `choices` for the `--distribution` argument using the keys (distribution names) from the loaded YAML data.
*   **`get_build_tags` Function:** Remove the hardcoded `tags_map`. Modify the function to retrieve the `buildtags` list from the loaded YAML data based on the provided `distribution` name, join the list into a comma-separated string, and return it. Handle the `custom` distribution case separately as before (using the `--build-tags` argument).

### 3. Modifying `.github/workflows/publish-custom-layer-collector.yml`

*   **Workflow Inputs:**
    *   Add a preliminary step (e.g., using `actions/github-script` with Python or a dedicated Python script checked into the repo) to read `config/distributions.yaml` using the `PyYAML` library.
    *   Extract the distribution names (keys).
    *   Generate a JSON array string of these names (e.g., `["default", "minimal", "clickhouse", ...]`).
    *   Use this generated JSON string to dynamically set the `inputs.distribution.options`. *(Note: This dynamic update of `workflow_dispatch` inputs is not directly possible; the options list in the workflow file remains static and needs manual updates if the UI dropdown should reflect changes.)*
*   **`create-github-release` Job:**
    *   Create/Modify `scripts/get_release_info.py`: This script reads `config/distributions.yaml` using `PyYAML`. It takes the distribution name and custom tags as input (env vars). It looks up the `buildtags` list for the given distribution, joins it into a comma-separated string, calculates the release tag/title, and sets the required outputs (`tag`, `title`, `build_tags`, etc.).
    *   Call `scripts/get_release_info.py` in the workflow, passing necessary inputs via environment variables.

### 4. Documentation (Optional Enhancement)

*   Consider adding a script (`scripts/generate_readme_tables.py`?) that reads `config/distributions.yaml` and automatically updates the "Available Distributions" list and "Understanding Distributions" table in `README.md`. This would keep the documentation perfectly in sync with the configuration.

## Benefits

*   **Single Source of Truth:** Adding or modifying distributions only requires editing `config/distributions.yaml`.
*   **Reduced Redundancy:** Eliminates duplicated logic in the Python script and workflow file.
*   **Improved Maintainability:** Easier to manage and less prone to errors.
*   **Dynamic Updates:** Build process automatically uses the latest definitions from the configuration file.

## Process for Adding a New Distribution (After Refactoring)

1.  Edit `config/distributions.yaml` to add the new distribution name, description, and `buildtags` list.
2.  (If auto-generation script exists) Run the script to update `README.md`.
3.  (If no auto-generation script) Manually update the relevant sections in `README.md`.
4.  Manually update the `options` list under `inputs.distribution` in `.github/workflows/publish-custom-layer-collector.yml` if you want the UI dropdown to show the new option.
5.  Commit the changes. The build process will automatically use the new definition.
