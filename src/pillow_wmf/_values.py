"""Snapshot sequence inputs so recorded commands cannot change underneath us."""

from dataclasses import fields


def freeze(value):
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    return value


def freeze_fields(instance):
    for field in fields(instance):
        object.__setattr__(instance, field.name, freeze(getattr(instance, field.name)))
