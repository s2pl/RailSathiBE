# auth_models.py
from pydantic import BaseModel
from typing import Optional, Dict

class RailSathiComplainResponse(BaseModel):
    message: str
    data: Optional[Dict] = None
