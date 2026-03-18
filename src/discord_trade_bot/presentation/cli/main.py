import asyncio
import multiprocessing
import signal
import subprocess
import sys

import typer

from discord_trade_bot.main.bootstrap import run_application
from discord_trade_bot.main.runners.discord import DiscordRunner
from discord_trade_bot.main.runners.tracker import PositionTrackerRunner

app = typer.Typer(help="Discord Trade Bot Management Utility", add_completion=False)


@app.command()
def discord():
    """Start the Discord Listener process"""
    asyncio.run(run_application(DiscordRunner, "Discord Listener"))


@app.command()
def tracker():
    """Start the WebSocket Tracker process"""
    asyncio.run(run_application(PositionTrackerRunner, "WebSocket Tracker"))


@app.command()
def worker():
    """Start the Taskiq Worker"""
    subprocess.run(
        [
            sys.executable,
            "-m",
            "taskiq",
            "worker",
            "discord_trade_bot.infrastructure.taskiq.broker:broker",
            "discord_trade_bot.infrastructure.taskiq.events",
            "discord_trade_bot.infrastructure.taskiq.tasks",
        ]
    )


@app.command()
def all():
    """Start all components concurrently (for local development)"""
    processes = []

    # List of functions to run in separate processes
    targets = [discord, tracker, worker]

    for target in targets:
        p = multiprocessing.Process(target=target)
        p.start()
        processes.append(p)

    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        print("\nStopping all processes...")
        for p in processes:
            p.terminate()


if __name__ == "__main__":
    app()
