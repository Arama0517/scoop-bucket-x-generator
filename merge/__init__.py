import contextlib

with contextlib.suppress(ModuleNotFoundError, FileNotFoundError):
    from dotenv import load_dotenv

    load_dotenv()
