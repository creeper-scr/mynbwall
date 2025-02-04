from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""

class Conf():
    def __init__(self):
        self.checkgroup = 624678719
        self.bot_id = 2702185024
        self.send_text = 'test'

