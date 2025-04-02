"""
UI utilities for command-line tools in the extension layer project.

This module provides consistent formatting and display functions for CLI output using
a Professional style with clear visual hierarchy. It includes:

- Header sections
- Status messages
- Progress indicators with spinners
- Error and success notifications
- Structured output

All functions use a consistent style with prefixes and color coding to improve readability.
"""

import click
from yaspin import yaspin as yaspin_func
from yaspin.spinners import Spinners
from typing import List, Dict, Any, Optional, Callable

# STYLING CONFIGURATION
# You can change these settings to modify the appearance across all scripts
STYLE_CONFIG = {
    "uppercase_headers": False,  # Convert headers to uppercase
    "header_prefix": "> ",  # Prefix for headers
    "status_prefix": "  - ",  # Prefix for status messages
    "detail_prefix": "    - ",  # Prefix for detail messages
    "success_prefix": "✓ ",  # Prefix for success messages
    "error_prefix": "✗ ",  # Prefix for error messages
    "separator": " | ",  # Separator between label and value
    "table": {
        "column_separator": " | ",  # Separator between table columns
        "header_separator": "-",  # Character for header separator row
    },
    "steps": {
        "pending_symbol": "○",  # Symbol for pending steps
        "running_symbol": "◔",  # Symbol for running steps
        "complete_symbol": "●",  # Symbol for completed steps
        "failed_symbol": "✗",  # Symbol for failed steps
    },
    "progress_bar": {
        "filled_char": "█",  # Character for filled portion
        "empty_char": "░",  # Character for empty portion
        "width": 50,  # Default width of progress bar
    },
}

# Color definitions for consistent styling
COLORS = {
    "header": "bright_white",
    "subheader": "white",
    "info": "bright_black",
    "success": "white",
    "error": "bright_white",
    "warning": "bright_black",
}


# Helper functions for internal use
def _format_heading_case(text: str) -> str:
    """Apply case formatting to headings based on configuration.

    Only transforms text to uppercase if:
    1. uppercase_headers is enabled in STYLE_CONFIG
    2. The text is not already uppercase

    Args:
        text: The text to format

    Returns:
        The formatted text
    """
    if STYLE_CONFIG["uppercase_headers"] and not text.isupper():
        return text.upper()
    return text


# ==========================================================================================
# Header and Section functions
# ==========================================================================================


def header(text: str) -> None:
    """Display a main section header.

    Args:
        text: Header text to display
    """
    # Only transform to uppercase if it's not already uppercase and the config says to do so
    formatted_text = _format_heading_case(text)

    click.secho(
        f"\n{STYLE_CONFIG['header_prefix']}{formatted_text}",
        fg=COLORS["header"],
        bold=True,
    )


def subheader(text: str) -> None:
    """Display a subsection header.

    Args:
        text: Subheader text to display
    """
    # Only transform to uppercase if it's not already uppercase and the config says to do so
    formatted_text = _format_heading_case(text)

    click.secho(
        f"\n{STYLE_CONFIG['header_prefix']}{formatted_text}",
        fg=COLORS["header"],
        bold=True,
    )


# ==========================================================================================
# Status message functions
# ==========================================================================================


def status(text: str, value: str) -> None:
    """Display a primary status message.

    Args:
        text: Status label
        value: Status value
    """
    click.secho(
        f"{STYLE_CONFIG['status_prefix']}{text}", fg=COLORS["subheader"], nl=False
    )
    click.echo(f"{STYLE_CONFIG['separator']}{value}")


def info(text: str, value: str) -> None:
    """Display an informational message.

    Args:
        text: Info label
        value: Info value
    """
    click.secho(f"{STYLE_CONFIG['status_prefix']}{text}", fg=COLORS["info"], nl=False)
    click.echo(f"{STYLE_CONFIG['separator']}{value}")


def detail(text: str, value: str) -> None:
    """Display a detail message (sub-info).

    Args:
        text: Detail label
        value: Detail value
    """
    click.secho(f"{STYLE_CONFIG['detail_prefix']}{text}", fg=COLORS["info"], nl=False)
    click.echo(f"{STYLE_CONFIG['separator']}{value}")


def success(text: str, value: Optional[str] = None) -> None:
    """Display a success message.

    Args:
        text: Success message
        value: Optional additional information
    """
    click.secho(
        f"{STYLE_CONFIG['success_prefix']}{text}", fg=COLORS["success"], nl=False
    )
    if value:
        click.echo(f"{STYLE_CONFIG['separator']}{value}")
    else:
        click.echo("")


def error(text: str, details: Optional[str] = None) -> None:
    """Display an error message with optional details.

    Args:
        text: Error message
        details: Optional error details
    """
    click.secho(
        f"{STYLE_CONFIG['error_prefix']}{text}", fg=COLORS["error"], bold=True, nl=False
    )
    click.echo(f"{STYLE_CONFIG['separator']}{details}" if details else "")


def warning(text: str, details: Optional[str] = None) -> None:
    """Display a warning message with optional details.

    Args:
        text: Warning message
        details: Optional warning details
    """
    click.secho(
        f"{STYLE_CONFIG['status_prefix']}Warning", fg=COLORS["warning"], nl=False
    )
    click.echo(f"{STYLE_CONFIG['separator']}{text}")
    if details:
        click.secho(
            f"{STYLE_CONFIG['detail_prefix']}Detail", fg=COLORS["info"], nl=False
        )
        click.echo(f"{STYLE_CONFIG['separator']}{details}")


# ==========================================================================================
# Progress indicator functions
# ==========================================================================================


def spinner(text: str, callback: Callable, color: str = "blue") -> Any:
    """Run a function with a spinner and return its result.

    Args:
        text: Text to display alongside spinner
        callback: Function to call while spinner is active
        color: Spinner color

    Returns:
        The return value from the callback function
    """

    sp = yaspin_func(Spinners.dots, text=text)
    sp.start()

    try:
        result = callback()
        sp.stop()
        return result
    except Exception as e:
        sp.stop()
        raise e


def async_spinner(text: str) -> Any:
    """Create and start a spinner, returning the spinner object to be stopped later.

    Args:
        text: Text to display alongside spinner

    Returns:
        The started yaspin spinner object
    """

    spnr = yaspin_func(Spinners.dots, text=text)
    spnr.start()
    return spnr


# ==========================================================================================
# Table and structured output functions
# ==========================================================================================


def property_list(properties: Dict[str, str], title: Optional[str] = None) -> None:
    """Display a list of properties (key-value pairs).

    Args:
        properties: Dictionary of property names and values
        title: Optional title for the property list
    """
    if title:
        click.secho(f"\n> {title}", fg=COLORS["subheader"])

    for key, value in properties.items():
        click.secho(f">   {key}", fg=COLORS["info"], nl=False)
        click.echo(f" | {value}")


def command_output(command: str, output: Optional[str] = None) -> None:
    """Display a command and its output.

    Args:
        command: The command that was run
        output: Command output (optional)
    """
    click.secho("> Command", fg=COLORS["subheader"], nl=False)
    click.echo(f" | {command}")

    if output:
        click.secho("> Output", fg=COLORS["info"], nl=False)
        click.echo(" |")
        click.echo(output)


# ==========================================================================================
# GitHub Actions specific utilities
# ==========================================================================================


def github_summary_table(properties: Dict[str, str], title: str) -> str:
    """Generate a Markdown table for GitHub job summaries.

    Args:
        properties: Dictionary of property names and values
        title: Title for the summary table

    Returns:
        Markdown formatted string for GitHub summary
    """
    summary = [
        f"## {title}",
        "| Property | Value |",
        "| --- | --- |",
    ]

    for key, value in properties.items():
        formatted_value = f"`{value}`" if value and not value.startswith("|") else value
        summary.append(f"| {key} | {formatted_value} |")

    return "\n".join(summary)


# ==========================================================================================
# Additional Formatting Utilities
# ==========================================================================================


def format_table(
    headers: List[str], rows: List[List[str]], title: Optional[str] = None
) -> None:
    """Display a formatted table with aligned columns.

    Args:
        headers: List of column headers
        rows: List of rows, where each row is a list of column values
        title: Optional table title
    """
    if not rows or not headers:
        warning("Cannot format empty table", "No data provided")
        return

    # Make sure all rows have the same number of columns as headers
    rows = [row + [""] * (len(headers) - len(row)) for row in rows if row]

    # Calculate column widths based on the headers and row values
    col_widths = [
        max(len(str(h)), max(len(str(row[i])) for row in rows))
        for i, h in enumerate(headers)
    ]

    # Print table title if provided
    if title:
        click.secho(f"\n{STYLE_CONFIG['status_prefix']}{title}", fg=COLORS["subheader"])

    # Print headers
    header_row = STYLE_CONFIG["table"]["column_separator"].join(
        str(h).ljust(w) for h, w in zip(headers, col_widths)
    )
    click.secho(f"{STYLE_CONFIG['detail_prefix']}{header_row}", fg=COLORS["subheader"])

    # Print separator row
    sep_char = STYLE_CONFIG["table"]["header_separator"]
    sep_row = sep_char + sep_char + sep_char.join(sep_char * w for w in col_widths)
    click.secho(f"{STYLE_CONFIG['detail_prefix']}{sep_row}", fg=COLORS["info"])

    # Print data rows
    for row in rows:
        data_row = STYLE_CONFIG["table"]["column_separator"].join(
            str(c).ljust(w) for c, w in zip(row, col_widths)
        )
        click.secho(f"{STYLE_CONFIG['detail_prefix']}{data_row}", fg=COLORS["info"])


def progress_bar(
    current: int, total: int, width: int = None, prefix: str = "", suffix: str = ""
) -> None:
    """Display a progress bar at the current progress level.

    Args:
        current: Current progress value
        total: Total progress value
        width: Width of the progress bar in characters (defaults to config value)
        prefix: Text to display before the progress bar
        suffix: Text to display after the progress bar
    """
    if width is None:
        width = STYLE_CONFIG["progress_bar"]["width"]

    percent = min(1.0, current / total) if total > 0 else 0
    filled_len = int(width * percent)

    # Use characters from config
    filled_char = STYLE_CONFIG["progress_bar"]["filled_char"]
    empty_char = STYLE_CONFIG["progress_bar"]["empty_char"]

    bar = filled_char * filled_len + empty_char * (width - filled_len)
    percent_str = f"{percent * 100:.1f}%"

    # Format: > Progress [███████░░░░░░░] 50.0% | 5/10
    progress_text = f"{STYLE_CONFIG['status_prefix']}{prefix} [{bar}] {percent_str}"
    if suffix:
        progress_text += f" | {suffix}"

    # Use carriage return to update in-place without newline
    click.echo(progress_text, nl=False)

    # Add newline if complete
    if current >= total:
        click.echo()


class StepTracker:
    """A multi-step progress tracker for complex operations.

    This class maintains state for multi-step operations and provides methods
    to update the display as steps are completed or failed.

    Example usage:
        ```
        tracker = StepTracker([
            "Cloning repository",
            "Building package",
            "Uploading to AWS"
        ])

        # First step
        tracker.start_step(0)
        # ... do work ...
        tracker.complete_step(0)

        # Second step
        tracker.start_step(1)
        # ... do work ...
        tracker.fail_step(1, "Build failed")
        ```
    """

    def __init__(self, steps: List[str], title: Optional[str] = None):
        """Initialize a new step tracker.

        Args:
            steps: List of step descriptions
            title: Optional title for the tracker
        """
        self.steps = steps
        self.title = title
        self.status = ["pending"] * len(
            steps
        )  # "pending", "running", "complete", "failed"
        self.messages = [""] * len(steps)

        # Status symbols from configuration
        self.symbols = {
            "pending": STYLE_CONFIG["steps"]["pending_symbol"],
            "running": STYLE_CONFIG["steps"]["running_symbol"],
            "complete": STYLE_CONFIG["steps"]["complete_symbol"],
            "failed": STYLE_CONFIG["steps"]["failed_symbol"],
        }

        # Status colors (using our existing color palette)
        self.colors = {
            "pending": "bright_black",  # Dim/Gray
            "running": "white",  # Active white
            "complete": "white",  # Success white
            "failed": "bright_white",  # Error white
        }

        # Display initial state
        self._render()

    def _render(self):
        """Render the current state of all steps."""
        # Display title if provided
        if self.title:
            click.echo()
            click.secho(
                f"{STYLE_CONFIG['header_prefix']}{_format_heading_case(self.title)}",
                fg=COLORS["header"],
                bold=True,
            )

        # Render each step
        for i, step in enumerate(self.steps):
            status = self.status[i]
            symbol = self.symbols[status]
            message = f" - {self.messages[i]}" if self.messages[i] else ""

            # Format the step line with appropriate styling
            click.secho(
                f"{STYLE_CONFIG['detail_prefix']}{symbol} {step}{message}",
                fg=self.colors[status],
                bold=(status == "failed"),
            )

    def start_step(self, index: int):
        """Mark a step as started.

        Args:
            index: Index of the step to start
        """
        if 0 <= index < len(self.steps):
            self.status[index] = "running"
            self.messages[index] = ""
            self._render()

    def complete_step(self, index: int, message: str = ""):
        """Mark a step as completed successfully.

        Args:
            index: Index of the step to complete
            message: Optional success message
        """
        if 0 <= index < len(self.steps):
            self.status[index] = "complete"
            self.messages[index] = message
            self._render()

    def fail_step(self, index: int, message: str = ""):
        """Mark a step as failed.

        Args:
            index: Index of the step that failed
            message: Optional failure message
        """
        if 0 <= index < len(self.steps):
            self.status[index] = "failed"
            self.messages[index] = message
            self._render()

    def update_step(self, index: int, message: str):
        """Update the message for a step without changing its status.

        Args:
            index: Index of the step to update
            message: New message
        """
        if 0 <= index < len(self.steps):
            self.messages[index] = message
            self._render()


# ==========================================================================================
# Logging and Debug Utilities
# ==========================================================================================


def log(message: str, level: str = "info", verbose_only: bool = False) -> None:
    """Log a message with appropriate styling based on the level.

    This is particularly useful for debug and verbose output that should only
    be displayed when a verbose flag is set.

    Args:
        message: The message to log
        level: Log level (debug, info, warning, error)
        verbose_only: Only log if verbose mode is enabled
    """
    # Early return if this is verbose-only and verbose mode is not enabled
    # This requires the calling script to set this global variable
    global VERBOSE_MODE
    if verbose_only and not globals().get("VERBOSE_MODE", False):
        return

    # Set default prefix and color based on level
    prefix = STYLE_CONFIG["detail_prefix"]
    color = COLORS.get("info")

    if level == "debug":
        prefix = f"{STYLE_CONFIG['detail_prefix']}DEBUG: "
        color = "cyan"  # Use cyan for debug messages
    elif level == "warning":
        prefix = f"{STYLE_CONFIG['detail_prefix']}WARNING: "
        color = COLORS.get("warning")
    elif level == "error":
        prefix = f"{STYLE_CONFIG['detail_prefix']}ERROR: "
        color = COLORS.get("error")

    click.secho(f"{prefix}{message}", fg=color)


# Global flag for verbose mode, can be set by scripts
VERBOSE_MODE = False


def set_verbose_mode(enabled: bool = True) -> None:
    """Enable or disable verbose mode globally.

    Args:
        enabled: Whether verbose mode should be enabled
    """
    global VERBOSE_MODE
    VERBOSE_MODE = enabled
    if enabled:
        log("Verbose mode enabled", "debug")


def debug(message: str) -> None:
    """Log a debug message (only shown in verbose mode).

    Args:
        message: Debug message to log
    """
    log(message, level="debug", verbose_only=True)
