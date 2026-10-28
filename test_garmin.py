"""Manual read-only smoke test; importing this file does not authenticate."""
from garmin_connector.cli import show_activities

if __name__ == '__main__':
    show_activities()
