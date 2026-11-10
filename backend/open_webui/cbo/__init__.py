"""Central Bank of Oman (CBO) customisations for CBO AI.

Everything in this package is CBO-specific and must stay additive: no upstream
module may import from here at module scope, so that ``git merge upstream/main``
keeps working without conflicts. The only upstream touch points are isolated
single-line hooks guarded by a runtime config check.
"""
