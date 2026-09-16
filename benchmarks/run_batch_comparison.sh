#!/bin/bash
# Retired historical batch entry point. No API calls or filesystem changes.
printf '%s\n' 'Retired: this wrapper used a machine-specific Python and could copy stale results after failure. See benchmarks/README.md.' >&2
exit 2
