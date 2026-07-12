"""BrainBuddy vNext modular monolith modules.

Each module owns its domain records and transitions. Cross-module writes
go through application-level ports, not direct repository access.
"""
