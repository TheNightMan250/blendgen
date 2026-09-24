"""Immutable, validated configuration independent of Blender UI."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Range:
    low: float
    high: float

    def validate(self, name, positive=False):
        import math
        if not all(math.isfinite(v) for v in (self.low, self.high)):
            raise ValueError(f'{name} must be finite')
        if self.low > self.high or (positive and self.low <= 0):
            raise ValueError(f'Invalid {name} range')

    def sample(self, rng):
        return rng.uniform(self.low, self.high)


@dataclass(frozen=True)
class RunConfig:
    scale: Range
    yaw: Range
    light: Range
    distance: Range
    elevation: Range
    azimuth: Range
    seed: int = 1
    attempts: int = 160
    margin: float = .12
    clearance: float = .008
    focal_length: float = 48
    location_bounds: object = None
    camera_bounds: object = None

    def validate(self):
        for name in ('scale', 'light', 'distance'):
            getattr(self, name).validate(name, positive=True)
        for name in ('yaw', 'elevation', 'azimuth'):
            getattr(self, name).validate(name)
        if not 0 <= self.margin < .45 or self.attempts < 1:
            raise ValueError('Invalid frame margin or retry count')
        if self.clearance < 0 or self.focal_length <= 0:
            raise ValueError('Clearance must be nonnegative; focal length must be positive')
        for bounds in (self.location_bounds, self.camera_bounds):
            if bounds and any(a > b for a,b in zip(*bounds)):
                raise ValueError('Position bounds: minimum must not exceed maximum')
