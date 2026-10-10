"""Implementation macOS de beheread.platforms (voir __init__.py)."""

from beheread.platforms.generic import (  # noqa: F401  (provisoire)
    GLOBAL_HOTKEY,
    RAR_HELP,
    GlobalHotkey,
    allow_foreground,
    before_app_start,
    data_dir,
    discard_secret,
    is_cloud_placeholder,
    protect_secret,
    rar_tools,
    reveal_in_file_manager,
    unprotect_secret,
)

NAME = "macos"
