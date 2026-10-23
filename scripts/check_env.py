"""Stage 0: print the Python and library versions this project runs on."""
import sys
from importlib.metadata import PackageNotFoundError, version

PACKAGES = ["fastmcp", "openai-agents", "mcp", "openai", "httpx", "pydantic", "python-dotenv"]


def main() -> None:
    print(f"python         {sys.version.split()[0]}  ({sys.executable})")
    for name in PACKAGES:
        try:
            print(f"{name:<14} {version(name)}")
        except PackageNotFoundError:
            print(f"{name:<14} NOT INSTALLED")


if __name__ == "__main__":
    main()
