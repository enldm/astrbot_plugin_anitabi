import os
import json
import time
import random
import asyncio
from pathlib import Path

from astrbot.api.star import Star, register, Context, StarTools
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api import logger
import aiohttp

# 常量定义
CACHE_EXPIRE_HOURS = 24
API_BASE = "https://api.anitabi.cn/bangumi"
LITE_API = f"{API_BASE}/{{}}/lite"
SESSION_TIMEOUT = 30
REQUEST_TIMEOUT = 10
CACHE_FETCH_TIMEOUT = 120  # 首次下载缓存文件的超时时间（秒）


@register("圣地巡礼", "enldm", "圣地巡礼查询插件", "1.0.0")
class SacredJourneyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.session = None
        self.waiting_for_input = {}
        self.cache_dir = StarTools.get_data_dir("astrbot_plugin_anitabi")
        self.cache_file = self.cache_dir / "anitabi.json"
        self.loop = asyncio.get_event_loop()

    async def initialize(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=SESSION_TIMEOUT))
        await self.ensure_cache()

    async def shutdown(self):
        if self.session:
            await self.session.close()

    async def ensure_cache(self):
        need_fetch = False
        if not self.cache_file.exists():
            logger.info("anitabi.json 不存在，开始首次下载。")
            need_fetch = True
        else:
            mod_time = await self.loop.run_in_executor(None, os.path.getmtime, str(self.cache_file))
            if time.time() - mod_time > CACHE_EXPIRE_HOURS * 3600:
                logger.info("anitabi.json 已过期，重新下载。")
                need_fetch = True

        if need_fetch:
            try:
                logger.info(f"正在异步请求 {API_BASE} ...")
                async with self.session.get(API_BASE, timeout=aiohttp.ClientTimeout(total=CACHE_FETCH_TIMEOUT)) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP {resp.status}")
                    data = await resp.json()
                # 确保目录存在
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                # 在线程池中执行文件写入
                await self.loop.run_in_executor(None, self._write_cache_file, data)
                logger.info("anitabi.json 更新成功。")
            except Exception as e:
                logger.error(f"下载 anitabi.json 失败: {e}")
                if not self.cache_file.exists():
                    raise RuntimeError("无法获取初始数据，请检查网络或 API 状态。")

    def _write_cache_file(self, data):
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    async def load_bangumi_list(self):
        def _load():
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return await self.loop.run_in_executor(None, _load)

    @filter.command("圣地巡礼")
    async def sj_command(self, event: AstrMessageEvent, arg: str = ""):
        if not arg:
            help_text = (
                "圣地巡礼插件帮助：\n"
                "• /圣地巡礼 随机作品\n"
                "• /圣地巡礼 随机地点\n"
                "• /圣地巡礼 猜地点"
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
        elif arg == "猜地点":
            async for msg in self.guess_location(event):
                yield msg
        else:
            yield event.plain_result("无效参数。请输入：随机作品 / 随机地点 / 猜地点")

    async def random_work(self, event: AstrMessageEvent):
        try:
            bangumi_list = await self.load_bangumi_list()
            item = random.choice(bangumi_list)
            async for msg in self._send_work_detail(event, item):
                yield msg
        except Exception as e:
            logger.error(f"随机作品出错: {e}")
            yield event.plain_result("获取随机作品失败，请稍后再试。")

    async def random_point(self, event: AstrMessageEvent):
        bangumi_list = await self.load_bangumi_list()
        for _ in range(10):
            item = random.choice(bangumi_list)
            sid = item.get('id')
            if not sid:
                continue
            try:
                async with self.session.get(LITE_API.format(sid), timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as resp:
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
                                # 尝试在 URL 后面添加 ?plan=h360
                                if '?' not in image_url:
                                    image_url = image_url + '?plan=h360'
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

    async def guess_location(self, event: AstrMessageEvent):
        """猜地点游戏：显示图片，让用户从三个选项中猜出正确答案"""
        bangumi_list = await self.load_bangumi_list()
        for _ in range(10):
            item = random.choice(bangumi_list)
            sid = item.get('id')
            if not sid:
                continue
            try:
                async with self.session.get(LITE_API.format(sid), timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        points = data.get('litePoints', [])
                        if points:
                            # 随机选择一个正确答案
                            correct_point = random.choice(points)
                            correct_geo = correct_point.get('geo', [])
                            correct_name = f"{correct_point.get('cn', '')}（{correct_point.get('name', '')}）"

                            # 获取两个不同的干扰项
                            distractors = []
                            temp_bangumi = [b for b in bangumi_list if b.get('id') != sid]
                            random.shuffle(temp_bangumi)

                            for other_item in temp_bangumi:
                                if len(distractors) >= 2:
                                    break
                                try:
                                    other_sid = other_item.get('id')
                                    async with self.session.get(LITE_API.format(other_sid), timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as other_resp:
                                        if other_resp.status == 200:
                                            other_data = await other_resp.json()
                                            other_points = other_data.get('litePoints', [])
                                            if other_points:
                                                other_point = random.choice(other_points)
                                                other_name = f"{other_point.get('cn', '')}（{other_point.get('name', '')}）"
                                                distractors.append((other_name, other_item))
                                except Exception:
                                    continue

                            if len(distractors) < 2:
                                continue

                            # 创建选项列表
                            options = [
                                (correct_name, item),
                                (distractors[0][0], distractors[0][1]),
                                (distractors[1][0], distractors[1][1])
                            ]

                            # 随机打乱选项，记住正确答案的位置
                            random.shuffle(options)
                            correct_index = options.index((correct_name, item)) + 1

                            # 显示图片
                            image_url = correct_point.get('image')
                            if image_url:
                                # 尝试在 URL 后面添加 ?plan=h360
                                if '?' not in image_url:
                                    image_url = image_url + '?plan=h360'
                                yield event.image_result(image_url)
                            else:
                                yield event.plain_result("该地点暂无图片")

                            # 显示选项
                            options_text = "🎮 猜猜这是哪里？（输入 1/2/3）\n"
                            for i, (name, _) in enumerate(options):
                                options_text += f"{i + 1}. {name}\n"

                            yield event.plain_result(options_text.strip())

                            # 设置等待用户输入
                            self.waiting_for_input[event.get_sender_id()] = {
                                'type': 'guess_location',
                                'attempts': 0,
                                'correct_index': correct_index,
                                'point': correct_point,
                                'item': item,
                                'timeout': time.time() + 60  # 60秒超时
                            }
                            return
            except Exception as e:
                logger.info(f"猜地点尝试失败 (作品ID: {sid}): {e}")
                continue
        yield event.plain_result("未能找到有效的地点，请稍后再试。")

    async def _send_location_result(self, event: AstrMessageEvent, point, item):
        """发送地点详情结果（参考随机地点的结构）"""
        geo = point.get('geo', [])
        geo_str = f"({geo[0]}, {geo[1]})" if geo else "(无坐标)"
        name = f"{point.get('cn', '')}（{point.get('name', '')}）"
        pid = point['id']
        sid = item['id']

        # 返回地点图片
        image_url = point.get('image')
        if image_url:
            # 尝试在 URL 后面添加 ?plan=h360
            if '?' not in image_url:
                image_url = image_url + '?plan=h360'
            yield event.image_result(image_url)
        else:
            yield event.plain_result("该地点暂无图片")

        # 构造链接
        location_link = f"https://www.anitabi.cn/map?bangumiId={sid}&pid={pid}"
        work_link = f"https://www.anitabi.cn/map?bangumiId={sid}"

        # 返回地点信息
        location_info = f"\n{name}\n地图: {location_link}"

        # 返回作品信息
        title = item.get('cn') or item.get('title', '未知')
        work_info = f"\n所属作品：{title} (ID: {sid})\n作品直链: {work_link}"

        yield event.plain_result(location_info + work_info)

    @filter.event_message_type(filter.EventMessageType.ALL)
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
            if wait_info['type'] == 'guess_location':
                attempts = wait_info['attempts']
                correct_index = wait_info['correct_index']
                point = wait_info['point']
                item = wait_info['item']

                if msg not in ['1', '2', '3']:
                    yield event.plain_result("请输入 1、2 或 3 来选择答案！")
                    return

                guess = int(msg)
                attempts += 1

                if guess == correct_index:
                    # 答对了
                    del self.waiting_for_input[user_id]
                    yield event.plain_result("🎉 恭喜你答对了！")
                    async for result in self._send_location_result(event, point, item):
                        yield result
                elif attempts >= 3:
                    # 三次都答错了
                    del self.waiting_for_input[user_id]
                    yield event.plain_result(f"很遗憾，三次机会用完了。正确答案是 {correct_index}。")
                    async for result in self._send_location_result(event, point, item):
                        yield result
                else:
                    # 继续尝试
                    self.waiting_for_input[user_id]['attempts'] = attempts
                    yield event.plain_result(f"答错了！还剩 {3 - attempts} 次机会，请继续猜：")
        except Exception as e:
            logger.error(f"处理用户输入时出错: {e}")
            yield event.plain_result("输入处理出错，请重试。")
            if user_id in self.waiting_for_input:
                del self.waiting_for_input[user_id]