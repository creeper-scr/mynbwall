from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""

class Conf():
    def __init__(self):
        self.checkgroup = 
        self.bot_id = 
        self.send_text = 'test'
        self.help_msg_admin = '输入/跟上命令以使用插件，当前支持的命令有：\n是 [id]：通过稿件\n拒 [id]：拒绝稿件\n查看 [id]：查看指定id的稿件\n删 [id]：删除指定id的稿件\n待处理：查看待处理的稿件\n回复：' 
        self.help_msg = '输入“/投稿”以投稿'
        self.out_id = 1
