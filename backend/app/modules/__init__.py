"""Bounded modules for BrainBuddy vNext.

Each module owns its domain records and transitions. Cross-module writes
go through application services that invoke ports, never through direct
repository imports.
"""
