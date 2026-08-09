#!/usr/bin/env python3
"""Compatibility wrapper: DE+FR-only publication has been retired.
Always publish the complete Europe map instead.
"""
from publish_europe_station_records import main

if __name__ == "__main__":
    raise SystemExit(main())
