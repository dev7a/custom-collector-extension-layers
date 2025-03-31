# Design Document: Lambda Layer Metadata Store using DynamoDB

**Version:** 1.0
**Date:** 2024-03-31

## 1. Introduction

This document outlines the design for replacing the current method of fetching and parsing AWS Lambda layer metadata with a centralized metadata store using Amazon DynamoDB. The goal is to improve reliability, maintainability, and extensibility of the layer publishing and reporting processes.

## 2. Problem Statement

Currently, the `scripts/generate-layers-report.py` script fetches Lambda layers across multiple AWS regions using `boto3` calls to the Lambda API (`list_layers`, `get_layer_version`). It then parses the layer name string (e.g., `opentelemetry-collector-amd64-clickhouse-0_119_0`) to determine metadata such as the distribution, architecture, and version.

This approach has several drawbacks:

*   **Brittleness:** Relies heavily on a strict naming convention. Any change or inconsistency in layer naming breaks the metadata extraction.
*   **Limited Metadata:** Only metadata encoded in the name can be reliably retrieved. Information like the specific collector version used during build, MD5 hash, or exact build timestamp is not directly available via Lambda API listings.
*   **Inefficiency:** Querying `list_layers` across numerous AWS regions can be slow and potentially subject to API throttling, especially as the number of layers or regions grows.
*   **Maintainability:** String parsing logic is less robust and harder to maintain than accessing structured data.

## 3. Proposed Solution

We propose implementing a DynamoDB table to serve as a central metadata store for all published custom collector Lambda layers.

*   The publishing workflow will be responsible for writing metadata to this table after successfully publishing a layer version.
*   The reporting script will query this DynamoDB table instead of the AWS Lambda API to generate the `LAYERS.md` report.

## 4. DynamoDB Table Design

*   **Table Name:** `custom-collector-extension-layers`
*   **Billing Mode:** `PAY_PER_REQUEST` (Suitable for infrequent access patterns)
*   **Key Schema:**
    *   **`pk` (Partition Key):** `distribution` (Type: String). Example: `"clickhouse"`, `"default"`. This allows efficient querying by distribution for the reporting use case.
    *   **`sk` (Sort Key):** `layer_arn` (Type: String). Example: `"arn:aws:lambda:us-east-1:ACCOUNT_ID:layer:opentelemetry-collector-amd64-clickhouse-0_119_0:1"`. Ensures uniqueness within a distribution and allows sorting/filtering by ARN if needed.
*   **Core Attributes:**
    *   `pk` (String): As defined above.
    *   `sk` (String): As defined above.
    *   `layer_arn` (String): The unique ARN of the layer version (redundant with `sk` but useful for direct access).
    *   `region` (String): AWS region where the layer is published (e.g., `"us-east-1"`).
    *   `base_name` (String): The base name of the layer (e.g., `"opentelemetry-collector"`).
    *   `architecture` (String): The architecture (e.g., `"amd64"`, `"arm64"`).
    *   `distribution` (String): The distribution name (e.g., `"clickhouse"`, `"default"`, redundant with `pk`).
    *   `layer_version_str` (String): The version string extracted from the layer name during build/publish (e.g., `"0_119_0"`).
    *   `collector_version_input` (String): The specific collector version provided as input to the build/publish process (e.g., `"v0.119.0"`).
    *   `md5_hash` (String): The MD5 hash of the layer artifact content.
    *   `publish_timestamp` (String): ISO 8601 timestamp when the record was written/updated in DynamoDB (e.g., `"2024-03-31T10:00:00Z"`).
    *   *(Optional)* `compatible_runtimes` (String Set): Set of compatible runtimes if provided.
    *   *(Optional)* `build_timestamp` (String): ISO 8601 timestamp from the build process.

## 5. Workflow Modifications

### 5.1. Publishing (`scripts/lambda_layer_publisher.py`)

1.  **Add Dependency:** Ensure `boto3` is available in the execution environment.
2.  **Gather Metadata:** After a layer version is successfully published (`publish_layer` function) and made public (`make_layer_public` function), the script will collect all necessary metadata attributes defined in section 4.
3.  **Determine `pk`:** The `distribution` value will be determined based on the script's input arguments.
4.  **Write to DynamoDB:**
    *   Instantiate a DynamoDB resource: `dynamodb = boto3.resource('dynamodb')`.
    *   Get the table: `table = dynamodb.Table('custom-collector-extension-layers')`.
    *   Construct the item dictionary using the gathered metadata, setting `pk` to the `distribution` and `sk` to the `layer_arn`.
    *   Use `table.put_item(Item=item_dict)` to write the data.
    *   Implement try/except blocks to handle potential `boto3`/DynamoDB errors during the `put_item` operation and log appropriately. The write should occur *after* the layer is successfully published and made public. `put_item` will overwrite existing items with the same `pk` and `sk`, which is acceptable for this use case (re-publishing the exact same ARN with potentially updated metadata like timestamp).

### 5.2. Reporting (`scripts/generate-layers-report.py`)

1.  **Add Dependency:** Ensure `boto3` is available.
2.  **Remove Lambda API Interaction:** Delete the `fetch_layers` function and its usage of Lambda `list_layers`/`get_layer_version`. Remove associated helper functions for name parsing (`get_distribution`, `get_architecture`, `get_version`).
3.  **Implement DynamoDB Query:**
    *   Create a new function `fetch_layers_from_dynamodb()`.
    *   Instantiate `dynamodb = boto3.resource('dynamodb')` and get the table resource.
    *   Define the list of known `DISTRIBUTIONS`.
    *   Iterate through each `distribution` in the list.
    *   For each `distribution`, execute `table.query(KeyConditionExpression=Key('pk').eq(distribution))` using `boto3.dynamodb.conditions.Key`.
    *   Handle potential pagination within the `query` results using the `LastEvaluatedKey`.
    *   Aggregate all items retrieved from the queries.
4.  **Process Results:** Adapt the logic that consumes the fetched data (previously in `main`, now using the results from `fetch_layers_from_dynamodb`) to group the items based on the `distribution` and `architecture` attributes directly read from the DynamoDB items.
5.  **Generate Report:** The `generate_report` function will largely remain the same, taking the processed dictionary (grouped by `distribution:architecture`) as input.

## 6. Infrastructure Prerequisites

*   An AWS DynamoDB table named `custom-collector-extension-layers` must exist with the schema defined in Section 4.
*   The AWS IAM role assumed by the GitHub Actions workflows (`lambda_layer_publisher.py` and `generate-layers-report.py`) must have sufficient permissions (`dynamodb:PutItem`, `dynamodb:Query`, `dynamodb:Scan` - Scan might be useful for full table analysis later) for this table.
*   These infrastructure components are managed outside the scope of this specific code repository.

## 7. Benefits

*   **Improved Reliability:** Metadata is stored explicitly, eliminating errors from name parsing.
*   **Enhanced Maintainability:** Code becomes cleaner, replacing complex string manipulation with direct data access.
*   **Extensibility:** Easily add new metadata fields in the future without altering layer naming conventions.
*   **Simplified Reporting Query:** Direct `Query` by distribution simplifies the data fetching logic in the reporting script.

## 8. Considerations

*   **Data Consistency:** The `put_item` operation should be performed as the final step after successful layer publication and permission updates to minimize inconsistencies. Error handling during the `put_item` call is important.
*   **Error Handling:** Robust error handling for DynamoDB operations (throttling, access denied, etc.) should be implemented in both scripts.
*   **Scalability (Read):** While `Query` is efficient, if the number of items per distribution becomes extremely large (millions), pagination handling is essential. `Scan` should be avoided for frequent, performance-sensitive reporting if the table grows significantly, favouring `Query` on the base table or a GSI. (Note: User context indicates low frequency, so `Query` is suitable). 