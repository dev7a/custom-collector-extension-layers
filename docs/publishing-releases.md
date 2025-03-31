# Design Document: Automated GitHub Release Creation

**Version:** 1.0
**Date:** 2024-03-31

## 1. Introduction

This document outlines the design for automating the creation of GitHub Releases as part of the `publish-custom-layer-collector.yml` workflow. The goal is to provide users with easily discoverable, versioned packages containing the Lambda layer artifacts and relevant metadata.

## 2. Problem Statement

Currently, the workflow successfully builds and publishes custom Lambda layers and generates a markdown report (`LAYERS.md`) stored as a workflow artifact. However, these artifacts are not easily discoverable or consumable by end-users. Users typically expect versioned releases with downloadable assets and release notes.

## 3. Proposed Solution

We propose adding a new job to the `publish-custom-layer-collector.yml` workflow that automatically creates a GitHub Release after the layers have been successfully published and the report generated.

This release will be tagged and named according to the specific distribution and collector version being processed by the workflow run. It will include the relevant layer `.zip` files as downloadable assets and formatted release notes containing build tags and a list of published ARNs for that specific version/distribution.

## 4. Workflow Modifications (`publish-custom-layer-collector.yml`)

### 4.1. Permissions

The workflow requires `contents: write` permission at the top level to allow creating tags and releases.

```yaml
permissions:
  id-token: write
  contents: write # Added permission
```

### 4.2. New Job: `create-github-release`

A new job named `create-github-release` will be added.

*   **Dependencies:** It will run only after the `release-layer` matrix and the `generate-layers-report` job have successfully completed.
    ```yaml
    needs: [release-layer, generate-layers-report]
    ```
*   **Runner:** `runs-on: ubuntu-latest`
*   **Steps:**
    1.  **Checkout Code:** `uses: actions/checkout@v4` - Needed to access local scripts.
    2.  **Setup Python:** `uses: actions/setup-python@v5` - Needed to run the notes generation script.
    3.  **Install Boto3:** `run: python -m pip install boto3` - Dependency for the notes script.
    4.  **Configure AWS Credentials:** `uses: aws-actions/configure-aws-credentials@v4` - With role granting `dynamodb:Query` access to the `custom-collector-extension-layers` table.
    5.  **Determine Release Info:** An `id: release_info` step will determine and output:
        *   `DISTRIBUTION`: From `inputs.distribution`.
        *   `COLLECTOR_VERSION`: From `needs.prepare-release-jobs.outputs.collector-version`.
        *   `BUILD_TAGS`: Derived using the same logic as `scripts/build_extension_layer.py`'s `get_build_tags` function (implementation TBD: duplicate logic in bash or call Python script).
        *   `TAG`: Formatted as `${DISTRIBUTION}-v${VERSION_TAG_PART}` (e.g., `clickhouse-v0.119.0`).
        *   `TITLE`: Formatted as `Release ${DISTRIBUTION}-v${VERSION_TAG_PART}`.
    6.  **Generate Release Body:**
        *   Execute a new Python script: `python scripts/generate_release_notes.py --distribution ... --collector-version ... --build-tags ...`.
        *   Redirect the script's standard output (which will be the formatted markdown) to a file (e.g., `release_notes.md`).
    7.  **Download Layer Artifacts:** Use `actions/download-artifact@v4` to download the relevant `.zip` artifact(s) (based on `inputs.architecture`) from the `build-layer` job into a temporary directory (e.g., `./release-assets/`).
    8.  **Create GitHub Release:** Use the GitHub CLI (`gh`) within a `run` step:
        *   Authenticate using `GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}` in the step's `env`.
        *   Execute `gh release create <tag> --title <title> --notes-file <notes_file> <asset_path_glob>`. Example:
            ```bash
            gh release create ${{ steps.release_info.outputs.tag }} \
              --title "${{ steps.release_info.outputs.title }}" \
              --notes-file release_notes.md \
              ./release-assets/*.zip
            ```

## 5. New Script (`scripts/generate_release_notes.py`)

*   **Purpose:** To query the DynamoDB metadata store and generate formatted markdown release notes for a specific distribution and collector version.
*   **Inputs:** Command-line arguments: `--distribution`, `--collector-version`, `--build-tags`.
*   **Logic:**
    1.  Parse arguments.
    2.  Connect to DynamoDB using `boto3`.
    3.  Query the `custom-collector-extension-layers` table using the provided `distribution` as the partition key (`pk`). Handle pagination.
    4.  Filter the query results in Python to only include items where the `collector_version_input` attribute matches the provided `--collector-version` argument.
    5.  Format the output:
        *   Header indicating the distribution and version.
        *   List of build tags used (passed as argument).
        *   Markdown table containing `Region`, `Architecture`, and `Layer ARN` for the filtered items.
*   **Output:** Prints the complete, formatted markdown string to standard output.

## 6. Release Naming and Content

*   **Tag Format:** `${distribution}-v${version_number}` (e.g., `minimal-v0.119.0`)
*   **Release Title Format:** `Release ${distribution}-v${version_number}`
*   **Release Body:** Markdown generated by `scripts/generate_release_notes.py`, containing build tags and a table of ARNs specific to that distribution/version.
*   **Assets:** The `opentelemetry-collector-layer-*.zip` file(s) corresponding to the architecture(s) built in the workflow run.

## 7. Considerations

*   **Idempotency:** `gh release create` will fail if the specified tag already exists. The workflow should either handle this (e.g., check first, use `gh release edit --tag <tag> --latest` to update, or use `--clobber` cautiously) or rely on manual intervention if a release needs to be regenerated. For initial implementation, failing on existing tag is acceptable.
*   **Error Handling:** The `create-github-release` job should properly handle errors from downloading artifacts, generating notes (DynamoDB query failures), or creating the release.
*   **Build Tags Logic:** Duplicating the build tag generation logic in the workflow's `run` step is the simplest initial approach but creates redundancy. A future improvement could involve making the `get_build_tags` logic in the Python build script callable or outputting the tags during the build process for later retrieval. 