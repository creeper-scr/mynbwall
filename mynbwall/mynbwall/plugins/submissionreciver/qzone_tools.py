import os
import sys
import json
import asyncio
import base64
import httpx
from httpx import Cookies
from typing import Optional, List, Dict, Callable, Awaitable
import traceback
import requests

# 常量定义
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
QRCODE_URL = "https://ssl.ptlogin2.qq.com/ptqrshow?appid=549000912&e=2&l=M&s=3&d=72&v=4&t=0.31232733520361844&daid=5&pt_3rd_aid=0"
UPLOAD_IMAGE_URL = "https://up.qzone.qq.com/cgi-bin/upload/cgi_upload_image"
EMOTION_PUBLISH_URL = "https://user.qzone.qq.com/proxy/domain/taotao.qzone.qq.com/cgi-bin/emotion_cgi_publish_v6"

class QzoneLogin:
    def __init__(self):
        self.cookies = {}

    def getptqrtoken(self, qrsig: str) -> str:
        e = 0
        for c in qrsig:
            e += (e << 5) + ord(c)
        return str(2147483647 & e)

    async def login_via_qrcode(self, qrcode_callback: Callable[[bytes], Awaitable[None]]) -> Dict:
        for _ in range(3):
            response = requests.get(QRCODE_URL)
            qrsig = next((c.split("=")[1] for c in response.headers["Set-Cookie"].split("; ") if c.startswith("qrsig")), "")
            if not qrsig:
                raise Exception("Failed to get qrsig")
            
            await qrcode_callback(response.content)
            
            ptqrtoken = self.getptqrtoken(qrsig)
            check_url = f"https://xui.ptlogin2.qq.com/ssl/ptqrlogin?ptqrtoken={ptqrtoken}&ptredirect=0&h=1&t=1&g=1&from_ui=1&ptlang=2052&action=0-0-1656992258324&js_ver=22070111&js_type=1&login_sig=&pt_uistyle=40&aid=549000912&daid=5&has_onekey=1"
            
            while True:
                await asyncio.sleep(2)
                response = requests.get(check_url, cookies={"qrsig": qrsig})
                if "二维码已失效" in response.text:
                    break
                if "登录成功" in response.text:
                    # 提取关键cookie信息
                    final_cookies = {}
                    for cookie in response.headers.get("Set-Cookie", "").split("; "):
                        if "=" in cookie:
                            key, value = cookie.split("=", 1)
                            final_cookies[key] = value
                    return final_cookies
        raise Exception("QR code login failed after 3 attempts")

class QzoneAPI:
    def __init__(self, cookies: Dict):
        self.cookies = cookies
        self.uin = int(cookies.get("uin", "0")[1:])
        self.gtk = self.generate_gtk(cookies.get("p_skey", ""))

    @staticmethod
    def generate_gtk(skey: str) -> str:
        hash_val = 5381
        for c in skey:
            hash_val += (hash_val << 5) + ord(c)
        return str(hash_val & 0x7FFFFFFF)

    async def upload_image(self, image_data: bytes) -> Dict:
        base64_img = base64.b64encode(image_data).decode()
        async with httpx.AsyncClient() as client:
            response = await client.post(
                UPLOAD_IMAGE_URL,
                data={
                    "picfile": base64_img,
                    "uin": str(self.uin),
                    "skey": self.cookies.get("skey", ""),
                    "p_skey": self.cookies.get("p_skey", ""),
                },
                headers={"Referer": f"https://user.qzone.qq.com/{self.uin}"}
            )
            return response.json()

    async def publish_emotion(self, content: str, images: List[bytes]) -> str:
        uploaded = []
        for img in images:
            res = await self.upload_image(img)
            if res.get("ret") != 0:
                raise Exception("Image upload failed")
            uploaded.append(res["data"]["url"])
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                EMOTION_PUBLISH_URL,
                params={"g_tk": self.gtk},
                data={
                    "con": content,
                    "pic_bo": ",".join(uploaded),
                    "richtype": "1",
                    "qzreferrer": f"https://user.qzone.qq.com/{self.uin}"
                },
                cookies=self.cookies
            )
            return response.json()["tid"]

async def renewcookies(qq_number: str, qrcode_callback: Optional[Callable[[bytes], Awaitable[None]]] = None) -> Dict:
    """更新或获取QQ空间Cookies"""
    try:
        # 尝试自动获取cookies
        async with httpx.AsyncClient() as client:
            # 获取clientkey
            response = await client.get(
                "https://xui.ptlogin2.qq.com/cgi-bin/xlogin?appid=715021417",
                headers={"User-Agent": UA}
            )
            pt_local_token = response.cookies.get("pt_local_token")
            
            clientkey_resp = await client.get(
                f"https://localhost.ptlogin2.qq.com:4301/pt_get_st?clientuin={qq_number}&pt_local_tk={pt_local_token}",
                headers={"Referer": "https://ssl.xui.ptlogin2.qq.com/"}
            )
            clientkey = clientkey_resp.cookies.get("clientkey")
            
            # 获取最终cookies
            login_resp = await client.get(
                f"https://ssl.ptlogin2.qq.com/jump?clientuin={qq_number}&clientkey={clientkey}",
                follow_redirects=False
            )
            return login_resp.cookies
    except Exception:
        # 自动获取失败，使用二维码登录
        login = QzoneLogin()
        if not qrcode_callback:
            async def default_callback(qr_data: bytes):
                with open("qrcode.png", "wb") as f:
                    f.write(qr_data)
                print("二维码已保存到 qrcode.png，请扫描登录")
        
        cookies = await login.login_via_qrcode(qrcode_callback or default_callback)
        with open(f"cookies-{qq_number}.json", "w") as f:
            json.dump(cookies, f)
        return cookies

async def send_qzone(qq_number: str, content: str, folder_id: str) -> str:
    """发送QQ空间动态，图片顺序按照 submission.json 中的 files 字段排列"""
    # 加载cookies
    try:
        with open(f"cookies-{qq_number}.json") as f:
            cookies = json.load(f)
    except FileNotFoundError:
        cookies = await renewcookies(qq_number)
    
    # 初始化API
    api = QzoneAPI(cookies)
    
    # 读取 submission.json 文件
    folder_path = os.path.join("temp", folder_id)
    submission_file = os.path.join(folder_path, "submission.json")
    
    try:
        with open(submission_file, "r", encoding="utf-8") as f:
            submission_data = json.load(f)
            files = submission_data.get("files", [])
    except FileNotFoundError:
        return f"错误：{submission_file} 文件不存在"
    except json.JSONDecodeError:
        return f"错误：{submission_file} 文件格式不正确"
    
    # 按照 submission.json 中的顺序加载图片
    images = []
    for filename in files:
        if filename.lower().endswith((".jpg", ".png", ".jpeg")):
            image_path = os.path.join(folder_path, filename)
            if os.path.exists(image_path):
                with open(image_path, "rb") as f:
                    images.append(f.read())
            else:
                print(f"警告：图片文件 {filename} 不存在，已跳过")
    
    # 发表动态
    try:
        tid = await api.publish_emotion(content, images)
        return f"动态发布成功！TID: {tid}"
    except Exception as e:
        # Cookies可能过期，尝试更新后重试
        cookies = await renewcookies(qq_number)
        api = QzoneAPI(cookies)
        tid = await api.publish_emotion(content, images)
        return f"动态发布成功（重试）！TID: {tid}"