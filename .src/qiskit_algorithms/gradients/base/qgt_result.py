# This code is part of a Qiskit project.
#
# (C) Copyright IBM 2022, 2023.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.
"""
QGT result class
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from qiskit.providers import Options

from ..utils import DerivativeType


@dataclass(frozen=True)
class QGTResult:
    """Result of QGT."""

    qgts: list[np.ndarray]
    """The QGT."""
    derivative_type: DerivativeType
    """The type of derivative."""
    metadata: list[dict[str, Any]]
    """Additional information about the job."""
    options: Options
    """Primitive runtime options for the execution of the job."""
