"""Read an interactive password with visible masking on Windows."""

from __future__ import annotations

import getpass
import os
import sys


def read_password(prompt: str) -> str:
    if os.name != "nt":
        return getpass.getpass(prompt)

    import msvcrt

    characters: list[str] = []
    sys.stdout.write(prompt)
    sys.stdout.flush()
    while True:
        key = msvcrt.getwch()
        if key in ("\r", "\n"):
            sys.stdout.write("\n")
            sys.stdout.flush()
            return "".join(characters)
        if key == "\x03":
            raise KeyboardInterrupt
        if key in ("\x00", "\xe0"):
            msvcrt.getwch()  # Discard the second code from a special key.
            continue
        if key in ("\b", "\x7f"):
            if characters:
                characters.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
            continue
        if key.isprintable():
            characters.append(key)
            sys.stdout.write("*")
            sys.stdout.flush()
