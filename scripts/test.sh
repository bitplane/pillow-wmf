#!/usr/bin/env bash

set -e
source .venv/bin/activate

suite=${1:-unit}

case "$suite" in
    unit|compatibility)
        pytest "test/$suite"
        ;;
    all)
        pytest test
        ;;
    *)
        echo "Unknown test suite: $suite" >&2
        exit 2
        ;;
esac
