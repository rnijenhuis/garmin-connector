from pathlib import Path


def connect(email, password, *, token_dir=None, prompt_mfa=None):
    """Authenticate only when explicitly called."""
    from garminconnect import Garmin
    client = Garmin(email, password, prompt_mfa=prompt_mfa)
    client.login(str(Path(token_dir or '~/.garminconnect').expanduser()))
    return client
