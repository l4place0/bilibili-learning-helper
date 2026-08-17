"""video-sum CLI — lightweight orchestration layer for video summarization."""

import click


@click.group()
@click.version_option(version="0.3.1")
def main():
    """Video Summarizer CLI — structured JSON output for skill integration."""
    pass


from cli.commands import (  # noqa: E402
    asr_commands,
    capture,
    cache_commands,
    comment_commands,
    danmaku_commands,
    doctor,
    frame_commands,
    library_commands,
    resource_commands,
)

main.add_command(asr_commands)
main.add_command(capture)
main.add_command(cache_commands)
main.add_command(comment_commands)
main.add_command(danmaku_commands)
main.add_command(doctor)
main.add_command(frame_commands)
main.add_command(library_commands)
main.add_command(resource_commands)
