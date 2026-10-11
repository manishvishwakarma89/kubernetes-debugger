"""Local/CI validator: exit 0 valid, 1 invalid/incomplete, 2 input/config error."""
import argparse
import json
from pathlib import Path
import sys
from validator import analyze, InputError, VERSIONS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--kubernetes-version", choices=VERSIONS, default="1.34.0")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--fail-on-warnings", action="store_true")
    args = parser.parse_args()
    try:
        with args.manifest.open("rb") as handle:
            data = handle.read(512 * 1024 + 1)
        result = analyze(data.decode("utf-8"), args.kubernetes_version)
    except (OSError, UnicodeDecodeError, InputError) as error:
        print("Cannot validate input: " + (str(error) if isinstance(error, InputError) else "check file access and UTF-8 encoding."), file=sys.stderr)
        return 2
    report = json.dumps(result, indent=2)
    print(report)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report + "\n", encoding="utf-8")
    return int(result["outcome"] != "valid" or (args.fail_on_warnings and result["warning_count"] > 0))


if __name__ == "__main__":
    sys.exit(main())
