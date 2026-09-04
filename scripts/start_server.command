#!/bin/bash
# BQC local web UI launcher for macOS (P9). Data goes to
# ~/Library/Application Support/bqc/data/
cd "$(dirname "$0")" || exit 1
./bqc serve
