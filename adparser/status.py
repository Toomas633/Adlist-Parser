"""Terminal status spinners and grouped displays."""

from __future__ import annotations

from asyncio import create_task, to_thread
from sys import stdout
from time import sleep


class StatusSpinner:
    """Simple spinner for live status updates."""

    def __init__(self, line_number: int = 0):
        self.spinner_chars = "|/-\\"
        self.index = 0
        self.line_number = line_number
        self.last_message_length = 0
        self.current_progress = None

    async def show_progress(self, message: str, operation):
        """Animate a spinner while awaiting the given async operation."""
        task = create_task(operation)

        base_message = message
        self.current_progress = None
        self._update_line(f'⚡ {base_message}')

        while not task.done():
            spinner = f" {self.spinner_chars[self.index]}"
            progress_text = f" {self.current_progress}" if self.current_progress else ""
            status_line = f'{spinner} {base_message}{progress_text}'
            self._update_line(status_line)
            self.index = (self.index + 1) % len(self.spinner_chars)
            await to_thread(sleep, 0.1)

        result = await task

        return result

    def update_progress(self, completed: int, total: int):
        """Update the progress display with a completed/total ratio."""
        if total > 0:
            percentage = (completed * 100) // total
            self.current_progress = f"{completed}/{total} ({percentage}%)"

    def update_status(self, message: str):
        """Replace the current line with the given message."""
        self._update_line(message)

    def _update_line(self, message: str):
        """Efficiently render a single line, minimizing flicker."""
        if self.line_number > 0:
            stdout.write(f'\033[{self.line_number}A')

        stdout.write(f'\r\033[K{message}')

        self.last_message_length = len(message)

        if self.line_number > 0:
            stdout.write(f'\033[{self.line_number}B')

        stdout.flush()

    def clear_and_print(self, final_message: str = ""):
        """Clear the spinner line and optionally print a final message."""
        if final_message:
            self._update_line(final_message)
        stdout.flush()


class GroupedStatusDisplay:
    """Manage multiple spinner lines as a grouped display."""

    def __init__(self, initial_lines_offset: int = 0):
        self.lines_allocated = initial_lines_offset
        self.initial_offset = initial_lines_offset
        self.initialized = False

    def allocate_line(self) -> StatusSpinner:
        """Allocate a new status line and return its spinner."""
        print()
        if not self.initialized:
            self.initialized = True

        relative_line = self.lines_allocated - self.initial_offset + 1
        self.lines_allocated += 1

        return StatusSpinner(line_number=relative_line)

    def finalize(self):
        """Move the cursor to the end after all operations complete."""
        total_lines = self.lines_allocated - self.initial_offset
        if total_lines > 0:
            stdout.write(f'\033[{total_lines}B\r')
        stdout.flush()
