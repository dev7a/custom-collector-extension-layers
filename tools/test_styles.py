#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["click", "yaspin"]
# ///
"""
test_styles.py

A demonstration of different styling options for CLI tools.
Run this script to see different macOS-inspired styling approaches.
"""

import click
import time
from yaspin import yaspin
from yaspin.spinners import Spinners


def simulate_command(duration: float = 0.3, success: bool = True) -> bool:
    """Simulate a command execution."""
    time.sleep(duration)
    return success


# Style 1: Minimalist - Very subtle, using only basic formatting
def style_minimalist():
    """Minimalist style with subtle formatting."""
    click.echo("\n=== Style 1: Minimalist ===\n")

    # Heading examples
    click.echo("MAIN HEADING")
    click.echo("------------")
    click.echo("Section Heading")
    click.echo("- Subheading")
    click.echo()

    # Command execution
    click.echo("Running command: make build")
    success = simulate_command(0.2)
    if success:
        click.echo("Command completed successfully")
    else:
        click.echo("Command failed")

    # Success/warning/error messages
    click.echo("\nStatus Messages:")
    click.echo("Success: Build completed")
    click.echo("Warning: File already exists")
    click.echo("Error: Failed to connect to server")

    # Long-running process with spinner
    click.echo("\nLong-running process:")
    with yaspin(text="Processing"):
        simulate_command(0.5)
    click.echo("Process completed")


# Style 2: Modern macOS - Clean with subtle intensity variations
def style_macos():
    """macOS style with subtle intensity variations."""
    click.echo("\n=== Style 2: Modern macOS ===\n")

    # Heading examples
    click.secho("MAIN HEADING", bold=True)
    click.secho("Section Heading", dim=False)
    click.secho("Subheading", dim=True)
    click.echo()

    # Command execution
    click.secho("Running command:", dim=True)
    click.secho("make build", bold=True)
    success = simulate_command(0.2)
    if success:
        click.secho("Command completed successfully", dim=True)
    else:
        click.secho("Command failed", bold=True)

    # Success/warning/error messages
    click.echo("\nStatus Messages:")
    click.secho("Success: Build completed", dim=True)
    click.secho("Warning: File already exists", bold=True)
    click.secho("Error: Failed to connect to server", bold=True, underline=True)

    # Long-running process with spinner
    click.echo("\nLong-running process:")
    with yaspin(text="Processing"):
        simulate_command(0.5)
    click.secho("Process completed", dim=True)


# Style 3: Professional - Clean with clear visual hierarchy
def style_professional():
    """Professional style with clear visual hierarchy using grayscale."""
    click.echo("\n=== Style 3: Professional ===\n")

    # Heading examples
    click.secho("- MAIN HEADING", fg="bright_white", bold=True)
    click.secho("> Section Heading", fg="white")
    click.secho(">   Subheading", fg="bright_black")
    click.echo()

    # Command execution
    click.secho("$ make build", fg="bright_black")
    success = simulate_command(0.2)
    if success:
        click.secho("✓ Command completed", fg="white")
    else:
        click.secho("✗ Command failed", fg="bright_white")

    # Success/warning/error messages
    click.echo("\nStatus Messages:")
    click.secho("- SUCCESS  ", fg="white", nl=False)
    click.echo("> Build completed")

    click.secho("- WARNING  ", fg="bright_black", nl=False)
    click.echo("> File already exists")

    click.secho("- ERROR    ", fg="bright_white", bold=True, nl=False)
    click.echo("> Failed to connect to server")

    # Long-running process with spinner
    click.echo("\nLong-running process:")
    with yaspin(Spinners.dots, text="Processing"):
        simulate_command(0.5)
    click.secho("✓ Process completed", fg="white")


# Style 4: Elegant - Understated with thoughtful spacing and separation
def style_elegant():
    """Elegant style with understated formatting and thoughtful spacing."""
    click.echo("\n=== Style 4: Elegant ===\n")

    # Heading examples
    click.secho("> MAIN HEADING", fg="bright_black", bold=True)
    click.secho(">  Section Heading", fg="bright_black")
    click.secho(">   Subheading", fg="bright_black", dim=True)
    click.echo()

    # Command execution
    click.secho("Command", fg="bright_black", nl=False)
    click.echo(" | make build")
    success = simulate_command(0.2)
    if success:
        click.secho("Result ", fg="bright_black", nl=False)
        click.echo(" | Completed successfully")
    else:
        click.secho("Result ", fg="bright_black", nl=False)
        click.echo(" | Failed to complete")

    # Success/warning/error messages
    click.echo("\nStatus Messages:")
    click.secho("Success ", fg="bright_black", nl=False)
    click.echo(" | Build completed")

    click.secho("Warning ", fg="bright_black", nl=False)
    click.echo(" | File already exists")

    click.secho("Error   ", fg="bright_black", nl=False)
    click.secho(" | Failed to connect to server", bold=True)

    # Long-running process with spinner
    click.echo("\nLong-running process:")
    with yaspin(Spinners.dots, text="Processing"):
        simulate_command(0.5)
    click.secho("Finished", fg="bright_black", nl=False)
    click.echo(" | Process completed")


# Style 5: Modern Terminal - Inspired by modern terminal designs
def style_modern_terminal():
    """Modern terminal style with borders and clean layout."""
    click.echo("\n=== Style 5: Modern Terminal ===\n")

    # Heading examples
    click.secho("┏━━ MAIN HEADING ━━━━━━━━━━━━━━━━━━━━━━━━━━━┓", fg="blue")
    click.secho("┃ Section Heading                           ┃", fg="blue")
    click.secho("┗━━ Subheading ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛", fg="blue")
    click.echo()

    # Command execution
    click.secho("⚡", fg="yellow", nl=False)
    click.echo(" Running: make build")
    success = simulate_command(0.2)
    if success:
        click.secho("✅ ", fg="green", nl=False)
        click.echo("Command completed successfully")
    else:
        click.secho("❌ ", fg="red", nl=False)
        click.echo("Command failed")

    # Success/warning/error messages
    click.echo("\nStatus Messages:")
    click.secho("✅ ", fg="green", nl=False)
    click.echo("Build completed")

    click.secho("⚠️  ", fg="yellow", nl=False)
    click.echo("File already exists")

    click.secho("❌ ", fg="red", nl=False)
    click.echo("Failed to connect to server")

    # Long-running process with spinner
    click.echo("\nLong-running process:")
    with yaspin(Spinners.clock, text="Processing", color="blue"):
        simulate_command(0.5)
    click.secho("✅ ", fg="green", nl=False)
    click.echo("Process completed")


# Style 6: GitHub Actions - Inspired by GitHub CI output
def style_github_actions():
    """GitHub Actions style with fold markers and CI-like output."""
    click.echo("\n=== Style 6: GitHub Actions ===\n")

    # Heading examples
    click.secho("::group::MAIN HEADING", fg="cyan", bold=True)
    click.secho("  Section Heading", fg="cyan")
    click.secho("    Subheading", fg="cyan", dim=True)
    click.secho("::endgroup::", fg="cyan")
    click.echo()

    # Command execution
    click.secho("##[command]make build", fg="magenta")
    success = simulate_command(0.2)
    if success:
        click.secho("##[section]Command completed successfully", fg="green")
    else:
        click.secho("##[error]Command failed", fg="red")

    # Success/warning/error messages
    click.echo("\nStatus Messages:")
    click.secho("##[section]", fg="green", nl=False)
    click.echo(" Build completed")

    click.secho("##[warning]", fg="yellow", nl=False)
    click.echo(" File already exists")

    click.secho("##[error]", fg="red", nl=False)
    click.echo(" Failed to connect to server")

    # Long-running process with spinner
    click.echo("\nLong-running process:")
    with yaspin(Spinners.line, text="Processing", color="cyan"):
        simulate_command(0.5)
    click.secho("##[section]", fg="green", nl=False)
    click.echo(" Process completed")


# Style 7: Colorful Minimal - Minimal with strategic color usage
def style_colorful_minimal():
    """Colorful minimal style with focused color usage."""
    click.echo("\n=== Style 7: Colorful Minimal ===\n")

    # Heading examples
    click.secho("MAIN HEADING", fg="bright_blue")
    click.echo("━━━━━━━━━━━━━")
    click.secho("Section Heading", fg="blue")
    click.secho("• Subheading", fg="cyan")
    click.echo()

    # Command execution
    click.echo("$ make build")
    success = simulate_command(0.2)
    if success:
        click.secho("→ Command completed successfully", fg="green")
    else:
        click.secho("→ Command failed", fg="red")

    # Success/warning/error messages
    click.echo("\nStatus Messages:")
    click.secho("OK ", fg="green", nl=False)
    click.echo("Build completed")

    click.secho("WARN ", fg="yellow", nl=False)
    click.echo("File already exists")

    click.secho("FAIL ", fg="red", nl=False)
    click.echo("Failed to connect to server")

    # Long-running process with spinner
    click.echo("\nLong-running process:")
    with yaspin(Spinners.noise, text="Processing", color="cyan"):
        simulate_command(0.5)
    click.secho("→ Process completed", fg="blue")


if __name__ == "__main__":
    click.clear()
    click.echo("# CLI Styling Options - macOS Inspired\n")
    click.echo("This script demonstrates different styling options for CLI tools.")
    click.echo("Choose the style that best matches your desired aesthetic.")

    style_minimalist()
    style_macos()
    style_professional()
    style_elegant()
    style_modern_terminal()
    style_github_actions()
    style_colorful_minimal()

    click.echo("\nEnd of demonstration. Run with 'python3 test_styles.py'")
