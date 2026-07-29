"""Home Assistant dependent tests.

Skipped automatically when Home Assistant is unavailable (notably on Windows,
where homeassistant.runner imports POSIX-only fcntl). CI runs these on Ubuntu.
"""
