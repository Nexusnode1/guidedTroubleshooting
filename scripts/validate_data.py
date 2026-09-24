"""Validate the presence and JSON syntax of supplied official datasets."""

from dataclasses import dataclass, field
import argparse
from pathlib import Path
import sys
from typing import Iterable

# Support direct execution (`python scripts/validate_data.py`) without a
# machine-specific path. Module execution remains supported as well.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.data_loader import DataLoadError, load_json


EXPECTED_DATASETS = ("queries.json", "responses.json", "deeplinks.json")


@dataclass
class ValidationReport:
    """Non-destructive report for available official input files."""

    checked: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        """Return whether expected datasets exist and parse as JSON."""
        return not self.missing and not self.invalid


def validate_data(data_dir: Path, expected: Iterable[str] = EXPECTED_DATASETS) -> ValidationReport:
    """Check expected JSON files without changing source data.

    Field-level validation is intentionally deferred until the official
    schema is supplied.
    """
    report = ValidationReport()
    for filename in expected:
        source = Path(data_dir) / filename
        if not source.exists():
            report.missing.append(str(source))
            continue
        try:
            load_json(source)
        except DataLoadError as exc:
            report.invalid.append(str(exc))
        else:
            report.checked.append(str(source))
    return report


def main(argv: list[str] | None = None) -> int:
    """Print a validation report and return a process status code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data" / "original")
    args = parser.parse_args(argv)
    report = validate_data(args.data_dir)
    print(f"Checked: {len(report.checked)}")
    print(f"Missing: {len(report.missing)}")
    for item in report.missing:
        print(f"  - {item}")
    print(f"Invalid: {len(report.invalid)}")
    for item in report.invalid:
        print(f"  - {item}")
    if not report.valid:
        print("Dataset validation: unresolved source files or invalid JSON.", file=sys.stderr)
    else:
        print("Dataset validation: passed")
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
