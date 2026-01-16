# AstrBot 圣地巡礼查询插件

基于 [Anitabi](https://www.anitabi.cn) API 的动漫圣地巡礼查询插件，支持随机作品、随机地点和猜地点游戏功能。

## 功能特性

- **随机作品**：随机获取一个动漫作品信息
- **随机地点**：随机获取一个圣地巡礼地点（含图片、坐标、地图链接）
- **猜地点游戏**：查看地点图片，从三个选项中猜出正确答案（三次机会）

## 安装方法

0. 直接在商店进行安装。

1. 将插件克隆到 AstrBot 的 `plugins` 目录：

```bash
git clone https://github.com/enldm/astrbot_plugin_anitabi.git
```

2. 确保 AstrBot 已安装以下依赖：

```
aiohttp
Pillow
```

3. 重启 AstrBot 或使用插件管理命令加载插件

## 使用命令

```
/圣地巡礼                # 显示帮助信息
/圣地巡礼 随机作品       # 随机获取一个动漫作品
/圣地巡礼 随机地点       # 随机获取一个圣地巡礼地点
/圣地巡礼 猜地点         # 开始猜地点游戏
```

## 数据说明

- 插件首次运行时会从 Anitabi API 下载 `anitabi.json` 缓存文件
- 缓存文件默认每 24 小时更新一次
- 如需立即更新，可删除 `anitabi.json` 文件后重启插件

## API 接口

- 数据来源：[Anitabi API](https://api.anitabi.cn)
- 官网：[https://www.anitabi.cn](https://www.anitabi.cn)

## 作者

enldm

## 许可证

本项目遵循 AstrBot 插件开发规范

## 相关链接

- [AstrBot 官方文档](https://astrbot.app)
- [Anitabi 官网](https://www.anitabi.cn)

## 已知问题

首次获取 json 时可能需要的时间较长，可手动访问https://api.anitabi.cn/bangumi 将 json 保存到 data\plugin_data\astrbot_plugin_anitabi。
