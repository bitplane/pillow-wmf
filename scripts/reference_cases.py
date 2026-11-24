"""Filesystem-only reference discovery, shared by Linux preflight and tests.

Each directory containing metafiles (WMF or EMF) has WIDTHxHEIGHT reference
subdirectories. Every active profile requires every local metafile.
"""

import argparse
import re
from pathlib import Path


def image_size(value):
    if not re.fullmatch(r"[1-9][0-9]*x[1-9][0-9]*", value):
        raise argparse.ArgumentTypeError("Expected positive WIDTHxHEIGHT, e.g. 257x193")
    return tuple(map(int, value.split("x")))


METAFILE_SUFFIXES = (".wmf", ".emf")


def sources(root):
    return sorted(p for p in Path(root).rglob("*") if p.is_file() and p.suffix.lower() in METAFILE_SUFFIXES)


def reference_cases(root, size=None):
    """Yield (metafile, PNG, generation size), including absent expected PNGs."""
    inputs = sources(root)
    groups = {}
    for source in inputs:
        groups.setdefault(source.parent, []).append(source)
    for directory, local_sources in sorted(groups.items()):
        if len({p.stem.casefold() for p in local_sources}) != len(local_sources):
            raise ValueError(f"Ambiguous metafile basenames in {directory}")
        if size is not None:
            profiles = [(directory / f"{size[0]}x{size[1]}", size)]
        else:
            profiles = []
            for child in sorted(directory.iterdir()):
                if child.is_dir() and re.fullmatch(r"[1-9][0-9]*x[1-9][0-9]*", child.name):
                    profiles.append((child, image_size(child.name)))
            if not profiles:
                raise ValueError(f"No size profiles in {directory}; generate references with --size WIDTHxHEIGHT")
        for profile, dimensions in profiles:
            for source in local_sources:
                yield source, profile / f"{source.stem}.png", dimensions


def discover_pairs(root):
    """Require missing references and reject orphan PNGs rather than skip them."""
    pairs = [(source, png) for source, png, _ in reference_cases(root)]
    expected = {png for _, png in pairs}
    orphans = sorted(p for p in Path(root).rglob("*") if p.suffix.lower() == ".png" and p not in expected)
    if orphans:
        raise ValueError(f"PNG without a matching metafile/profile: {orphans[0]}")
    return pairs


def selected_pairs(paths):
    """Resolve selected inputs across all their directory's size profiles."""
    paths = set(paths)
    return sorted({pair for root in {p.parent for p in paths} for pair in discover_pairs(root) if pair[0] in paths})
