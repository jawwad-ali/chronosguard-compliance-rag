"""Organization API shapes."""

import datetime as dt

from pydantic import BaseModel, ConfigDict


class OrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    home_jurisdiction: str
    created_at: dt.datetime
