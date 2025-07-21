"""Main entry point for the IPC CLI."""

import typer

app = typer.Typer()


@app.command()  # type: ignore[misc]
def version() -> None:
    """Show the IPC CLI version."""
    typer.echo("IPC CLI version 0.1.0")


@app.command()  # type: ignore[misc]
def hello() -> None:
    """Say hello from IPC CLI."""
    typer.echo("Hello from AegisIPC CLI!")


if __name__ == "__main__":
    app()
