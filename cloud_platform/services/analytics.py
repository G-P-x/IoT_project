"""
Analytics Service Module
=========================
Provides an AggregationService that computes basic statistics (mean, min, max,
standard deviation) across measurements stored in Digital Replicas.

Architecture reasoning (from the lecture):
- The AggregationService is a concrete implementation of BaseService.
- It operates on the 'digital_replicas' list provided by the DT core and can
  optionally filter by DR type and measurement attribute.
- This keeps the service decoupled from any specific domain — it works on any
  DR whose 'data.measurements' follows the standard measurement dict format:
    { "measure_type": str, "value": numeric, "timestamp": str|datetime }
- In our IoT monitoring domain the measure_type values include 'temperature',
  'air_quality', 'seismic_waves', etc.
"""

from typing import Dict
import statistics
from cloud_platform.services.base import BaseService


class AggregationService(BaseService):
    """
    Service for aggregating measurements across Digital Replicas.

    Given the DT data (list of DRs), this service:
        1. Filters DRs by type (optional).
        2. Collects all measurements, optionally filtering by attribute.
        3. Groups values by measure_type.
        4. Computes count, mean, min, max, and stddev for each group.
    """

    def execute(self, data: Dict, dr_type: str = None, attribute: str = None) -> Dict:
        """
        Run aggregation on measurements from the DT's Digital Replicas.

        Args:
            data:      Dict containing 'digital_replicas' (list of DR dicts).
            dr_type:   Optional — only aggregate DRs of this type (e.g. 'sensor').
            attribute: Optional — only aggregate measurements with this measure_type
                       (e.g. 'temperature').

        Returns:
            A dict mapping each measure_type to its computed statistics, e.g.:
            {
                "temperature": {"count": 10, "mean": 23.5, "min": 18.0, ...},
                ...
            }
        """
        if not data or "digital_replicas" not in data:
            raise ValueError("Invalid data: missing 'digital_replicas' key")

        # Step 1 — Filter DRs by type if specified
        drs = [
            dr for dr in data["digital_replicas"]
            if dr_type is None or dr.get("type") == dr_type
        ]

        if not drs:
            return {"error": f"No digital replicas found of type '{dr_type}'"}

        # Step 2 — Collect measurements, optionally filtering by attribute
        all_measurements = []
        for dr in drs:
            measurements = dr.get("data", {}).get("measurements", [])
            if attribute:
                measurements = [m for m in measurements if m.get("measure_type") == attribute]
            all_measurements.extend(measurements)

        if not all_measurements:
            return {"error": f"No measurements found for attribute '{attribute}'"}

        # Step 3 — Group numeric values by measure_type
        grouped: Dict[str, list] = {}
        for m in all_measurements:
            mtype = m.get("measure_type", "unknown")
            grouped.setdefault(mtype, []).append(float(m["value"]))

        # Step 4 — Compute statistics per group
        stats = {}
        for mtype, values in grouped.items():
            try:
                stats[mtype] = {
                    "count": len(values),
                    "mean": round(statistics.mean(values), 4),
                    "min": min(values),
                    "max": max(values),
                    "stddev": round(statistics.stdev(values), 4) if len(values) > 1 else 0,
                }
            except (statistics.StatisticsError, ValueError) as e:
                stats[mtype] = {"error": str(e), "count": len(values)}

        return stats
