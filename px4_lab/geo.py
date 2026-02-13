from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class GlobalPosition:
    lat_deg: float
    lon_deg: float
    abs_alt_m: float


def add_ned_offset_to_gps(home_lat_deg: float, home_lon_deg: float, north_m: float, east_m: float) -> tuple[float, float]:
    """Approximate conversion from N/E offset (meters) to lat/lon (degrees).

    Good enough for small offsets (tens to hundreds of meters), which is exactly
    what we want for SITL missions.
    """
    # WGS84-ish meters per degree
    meters_per_deg_lat = 111_111.0
    lat_rad = math.radians(home_lat_deg)
    meters_per_deg_lon = meters_per_deg_lat * math.cos(lat_rad)

    dlat = north_m / meters_per_deg_lat
    dlon = east_m / meters_per_deg_lon if meters_per_deg_lon != 0 else 0.0

    return home_lat_deg + dlat, home_lon_deg + dlon
