
#!/usr/bin/env python3
"""
This script prints a greeting message.
It demonstrates a simple execution tool within the 3-Layer Architecture.
"""

import sys

def main():
    try:
        print("Hello, user! The Agent Architecture is set up correctly.")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
