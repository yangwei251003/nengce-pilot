"""能策 Pilot: auditable local-first research prototype."""
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(key, '1')
__version__ = '2.0.0'
