from pydantic import BaseModel
from typing import Optional


class RuneSlot(BaseModel):
    rune_id: Optional[str] = None


class RunePage(BaseModel):
    reds: list[RuneSlot] = []
    yellows: list[RuneSlot] = []
    blues: list[RuneSlot] = []
    quints: list[RuneSlot] = []

    def model_post_init(self, __context):
        while len(self.reds) < 9:
            self.reds.append(RuneSlot())
        while len(self.yellows) < 9:
            self.yellows.append(RuneSlot())
        while len(self.blues) < 9:
            self.blues.append(RuneSlot())
        while len(self.quints) < 3:
            self.quints.append(RuneSlot())
