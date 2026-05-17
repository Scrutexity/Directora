"""Exclude load-test scripts from pytest collection.

`sign_off_load_test.py` ends in `_test.py`, which matches pytest's
default discovery pattern. The script is a locust file, not a unit
test, and importing locust at collection time would fail in CI without
the dev dependency installed. The collect_ignore hook keeps pytest
from touching it.
"""
collect_ignore = ["sign_off_load_test.py"]
