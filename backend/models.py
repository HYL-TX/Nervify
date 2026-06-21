# backend/models.py
#
# Pydantic request bodies for the HTTP API.

from typing import Optional

from pydantic import BaseModel, Field

from . import config


class SetupRequest(BaseModel):
    target_percentage: float = Field(default=config.TARGET_PERCENTAGE, gt=0, le=100)
    load_cell_calibration_factor: Optional[float] = Field(
        default=None,
        gt=0,
        description="Newton-per-ADC calibration factor saved by the device, if known.",
    )


class StartSessionRequest(BaseModel):
    patient_id: Optional[str] = None


class PreparationRequest(BaseModel):
    skin_cleaned: bool = False
    electrode_on_apb: bool = False
    skin_marked: bool = False
    hand_positioned: bool = False
    notes: Optional[str] = None


class ManualSampleRequest(BaseModel):
    force: float
    emg: float
