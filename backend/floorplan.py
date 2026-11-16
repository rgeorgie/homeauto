import json
import os
from typing import Dict, List, Literal

from pydantic import BaseModel, Field

FLOORPLAN_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "floorplan.json")

# All coordinates are fractions (0-1) of the plan's width/height, so the plan scales with the screen.
class FloorRoom(BaseModel):
    name: str  # matches the device "room" name
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)

class DevicePlacement(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    kind: Literal["lamp", "vent"] = "lamp"  # how a switch / relay is shown on the plan

class HomeFloorPlan(BaseModel):
    rooms: List[FloorRoom] = Field(default_factory=list)
    devices: Dict[str, DevicePlacement] = Field(default_factory=dict)  # device id -> position

class FloorPlan(BaseModel):
    # One plan per Tuya home, because room names repeat across homes (e.g. "Living Room")
    homes: Dict[str, HomeFloorPlan] = Field(default_factory=dict)

def get_floorplan() -> FloorPlan:
    if not os.path.exists(FLOORPLAN_PATH):
        return FloorPlan()
    try:
        with open(FLOORPLAN_PATH, "r", encoding="utf-8") as f:
            return FloorPlan(**json.load(f))
    except Exception:
        return FloorPlan()

def save_floorplan(plan: FloorPlan):
    tmp = FLOORPLAN_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(plan.model_dump(), f, ensure_ascii=False, indent=2)
    os.replace(tmp, FLOORPLAN_PATH)
