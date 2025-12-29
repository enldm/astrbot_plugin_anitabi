from astrbot.api.all import *
import os
import json
import time
import random
import asyncio
from PIL import Image, ImageDraw, ImageFont
import io

from astrbot.api.star import Star, register, Context
from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger
import aiohttp

CACHE_FILE = "anitabi.json"
CACHE_EXPIRE_HOURS = 24
API_BASE = "https://api.anitabi.cn/bangumi"
LITE_API = f"{API_BASE}/{{}}/lite"


@register("圣地巡礼", "enldm", "圣地巡礼查询插件", "1.0.0")
class SacredJourneyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.session = None
        self.font = self._load_font()
        self.waiting_for_input = {}

    async def initialize(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        await self.ensure_cache()

    async def shutdown(self):
        if self.session:
            await self.session.close()

    def _load_font(self):
        try:
            if os.name == 'nt':
                return ImageFont.truetype("msyh.ttc", 16)
            else:
                return ImageFont.load_default()
        except:
            return ImageFont.load_default()

    async def ensure_cache(self):
        need_fetch = False
        if not os.path.exists(CACHE_FILE):
            logger.info("anitabi.json 不存在，开始首次下载。")
            need_fetch = True
        else:
            mod_time = os.path.getmtime(CACHE_FILE)
            if time.time() - mod_time > CACHE_EXPIRE_HOURS * 3600:
                logger.info("anitabi.json 已过期，重新下载。")
                need_fetch = True

        if need_fetch:
            try:
                logger.info(f"正在异步请求 {API_BASE} ...")
                async with self.session.get(API_BASE) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP {resp.status}")
                    data = await resp.json()
                with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.info("anitabi.json 更新成功。")
            except Exception as e:
                logger.error(f"下载 anitabi.json 失败: {e}")
                if not os.path.exists(CACHE_FILE):
                    raise RuntimeError("无法获取初始数据，请检查网络或 API 状态。")

    def load_bangumi_list(self):
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    @command("圣地巡礼")
    async def sj_command(self, event: AstrMessageEvent, arg: str = ""):
        if not arg:
            help_text = (
                "圣地巡礼插件帮助：\n"
                "• /圣地巡礼 随机作品\n"
                "• /圣地巡礼 随机地点\n"
                "• (不可用)/圣地巡礼 搜寻\n"
                "• (不可用)/圣地巡礼 <作品ID>"
            )
            yield event.plain_result(help_text)
            return

        arg = arg.strip()
        if arg == "随机作品":
            async for msg in self.random_work(event):
                yield msg
        elif arg == "随机地点":
            async for msg in self.random_point(event):
                yield msg
        elif arg == "搜寻":
            async for msg in self.search_work(event):
                yield msg
        elif arg.isdigit():
            async for msg in self.query_by_id(event, arg):
                yield msg
        else:
            yield event.plain_result("无效参数。请输入：随机作品 / 随机地点 / 搜寻 / <作品ID>")

    async def random_work(self, event: AstrMessageEvent):
        try:
            bangumi_list = self.load_bangumi_list()
            item = random.choice(bangumi_list)
            async for msg in self._send_work_detail(event, item):
                yield msg
        except Exception as e:
            logger.error(f"随机作品出错: {e}")
            yield event.plain_result("获取随机作品失败，请稍后再试。")

    async def query_by_id(self, event: AstrMessageEvent, subject_id: str):
        try:
            url = LITE_API.format(subject_id)
            async with self.session.get(url) as resp:
                if resp.status == 404:
                    yield event.plain_result("未找到该作品ID。")
                    return
                resp.raise_for_status()
                data = await resp.json()
            points = data.get('litePoints', [])
            if not points:
                yield event.plain_result("该作品暂无圣地信息。")
                return
            img_bytes = await self._generate_image_grid(points)
            yield event.image_result(img_bytes)
            self.waiting_for_input[event.get_sender_id()] = {
                'type': 'select_point',
                'data': {'points': points},
                'timeout': time.time() + 30
            }
            yield event.plain_result("请继续输入地点ID或者数字序号查询地点详情（30秒内有效）")
        except Exception as e:
            logger.error(f"查询作品 {subject_id} 出错: {e}")
            yield event.plain_result("查询失败，请检查ID是否正确。")

    async def random_point(self, event: AstrMessageEvent):
        bangumi_list = self.load_bangumi_list()
        for _ in range(10):
            item = random.choice(bangumi_list)
            sid = item.get('id')
            if not sid:
                continue
            try:
                async with self.session.get(LITE_API.format(sid), timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        points = data.get('litePoints', [])
                        if points:
                            point = random.choice(points)
                            geo = point.get('geo', [])
                            image_url = point.get('image')
                            geo_str = f"({geo[0]}, {geo[1]})" if geo else "(无坐标)"
                            name = f"{point.get('cn', '')}（{point.get('name', '')}）"
                            pid = point['id']
                            
                            # 返回地点图片
                            if image_url:
                                yield event.image_result(image_url)
                            else:
                                yield event.plain_result("该地点暂无图片")
                            
                            # 构造链接
                            location_link = f"https://www.anitabi.cn/map?bangumiId={sid}&pid={pid}"
                            work_link = f"https://www.anitabi.cn/map?bangumiId={sid}"

                            # 返回地点信息 location_info = f"\n{name}\n地点ID: {pid}\n经纬度: {geo_str}\n地点直链: {location_link}"
                            location_info = f"\n{name}\n地图: {location_link}"
                            
                            # 返回作品信息
                            title = item.get('cn') or item.get('title', '未知')
                            work_info = f"\n所属作品：{title} (ID: {sid})\n作品直链: {work_link}"
                            
                            yield event.plain_result(location_info + work_info)
                            return
            except Exception as e:
                logger.info(f"随机地点尝试失败 (作品ID: {sid}): {e}")
                continue
        yield event.plain_result("未能找到有效的随机地点，请稍后再试。")

    async def search_work(self, event: AstrMessageEvent):
        yield event.plain_result("请输入要搜寻的作品名称：")
        self.waiting_for_input[event.get_sender_id()] = {
            'type': 'search_keyword',
            'timeout': time.time() + 30
        }

    async def on_message(self, event: AstrMessageEvent):
        user_id = event.get_sender_id()
        if user_id not in self.waiting_for_input:
            return

        wait_info = self.waiting_for_input[user_id]
        if time.time() > wait_info['timeout']:
            del self.waiting_for_input[user_id]
            yield event.plain_result("等待超时，操作已取消。")
            return

        msg = event.message_str.strip()
        try:
            if wait_info['type'] == 'select_work':
                idx = int(msg) - 1
                candidates = wait_info['data']
                if 0 <= idx < len(candidates):
                    async for msg in self._send_work_detail(event, candidates[idx]):
                        yield msg
                    del self.waiting_for_input[user_id]
                    return
                else:
                    yield event.plain_result("序号超出范围！")
            elif wait_info['type'] == 'select_point':
                points = wait_info['data']['points']
                point_map = {}
                for i, p in enumerate(points):
                    point_map[str(i + 1)] = p
                    point_map[p['id']] = p
                if msg in point_map:
                    point = point_map[msg]
                    geo = point.get('geo', [])
                    geo_str = f"({geo[0]}, {geo[1]})" if geo else "(无坐标)"
                    name = f"{point.get('cn', '')}（{point.get('name', '')}）"
                    yield event.image_result(point.get('image'))
                    yield event.plain_result(f"\n{name}\n经纬度: {geo_str}")
                    del self.waiting_for_input[user_id]
                    return
                else:
                    yield event.plain_result("请输入正确的地点 ID 或序号！")
            elif wait_info['type'] == 'search_keyword':
                keyword = msg
                bangumi_list = self.load_bangumi_list()
                matches = [item for item in bangumi_list
                          if keyword.lower() in (item.get('title', '') + item.get('cn', '')).lower()]
                if not matches:
                    yield event.plain_result("未找到相关作品。")
                else:
                    img_bytes = await self._generate_cover_grid(matches[:20])
                    yield event.image_result(img_bytes)
                    self.waiting_for_input[user_id] = {
                        'type': 'select_work',
                        'data': matches[:20],
                        'timeout': time.time() + 30
                    }
                    yield event.plain_result("请继续输入序号查询作品详情（30秒内有效）")
                del self.waiting_for_input[user_id]
        except Exception as e:
            logger.error(f"处理用户输入时出错: {e}")
            yield event.plain_result("输入处理出错，请重试。")
            if user_id in self.waiting_for_input:
                del self.waiting_for_input[user_id]

    # ========== 图片生成部分 ==========
    async def _fetch_image(self, url):
        try:
            if not url.startswith('http'):
                return None
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return None
                img = Image.open(io.BytesIO(await resp.read())).convert("RGB")
                return img.resize((280, 160))
        except Exception as e:
            logger.debug(f"图片加载失败: {url}, error: {e}")
            return None

    async def _generate_cover_grid(self, items):
        tasks, labels = [], []
        for i, item in enumerate(items):
            cover = item.get('cover', '')
            if cover.startswith('/'):
                cover = 'https://api.anitabi.cn' + cover
            elif not cover.startswith('http'):
                cover = 'https://lain.bgm.tv/pic/cover/l/9b/e7/59392_05W7s.jpg'
            tasks.append(self._fetch_image(cover))
            cn = item.get('cn') or item.get('title', '未知')
            labels.append(f"{i + 1}. {cn[:15]} ({item['id']})")
        
        # 正确处理异步任务结果
        fetched_images = await asyncio.gather(*tasks)
        imgs = []
        valid_labels = []
        for img, label in zip(fetched_images, labels):
            if img is not None:
                imgs.append(img)
                valid_labels.append(label)
        return self._build_grid_image(imgs, valid_labels)

    async def _generate_image_grid(self, points):
        tasks, labels = [], []
        for i, p in enumerate(points):
            img_url = p.get('image', '')
            if not img_url.startswith('http'):
                img_url = 'https://image.anitabi.cn/points/115908/qys7fu.jpg?plan=h160'
            tasks.append(self._fetch_image(img_url))
            cn = p.get('cn', '')
            name = p.get('name', '')
            labels.append(f"{i + 1}. {cn or name} ({p['id']})")
        
        # 正确处理异步任务结果
        fetched_images = await asyncio.gather(*tasks)
        imgs = []
        valid_labels = []
        for img, label in zip(fetched_images, labels):
            if img is not None:
                imgs.append(img)
                valid_labels.append(label)
        return self._build_grid_image(imgs, valid_labels)

    def _build_grid_image(self, imgs, labels):
        if not imgs:
            img = Image.new('RGB', (1500, 160), (200, 200, 200))
            draw = ImageDraw.Draw(img)
            draw.text((10, 70), "无有效图片", fill=(0, 0, 0), font=self.font)
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        cols, rows = 5, (len(imgs) + 4) // 5
        canvas = Image.new('RGB', (1500, rows * 190), (255, 255, 255))
        for i, (img, label) in enumerate(zip(imgs, labels)):
            x, y = (i % cols) * 300, (i // cols) * 190
            canvas.paste(img, (x, y))
            draw = ImageDraw.Draw(canvas)
            draw.text((x + 5, y + 165), label, fill=(0, 0, 0), font=self.font)
        buf = io.BytesIO()
        canvas.save(buf, format='PNG')
        return buf.getvalue()

    async def _send_work_detail(self, event: AstrMessageEvent, item):
        cover = item.get('cover', '')
        if cover.startswith('/'):
            cover = 'https://api.anitabi.cn' + cover
        elif not cover.startswith('http'):
            cover = 'https://lain.bgm.tv/pic/cover/l/9b/e7/59392_05W7s.jpg'
        title = item.get('cn') or item.get('title', '未知')
        yield event.image_result(cover)
        yield event.plain_result(f"ID：{item['id']}\n标题：{title}")


