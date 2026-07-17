# 低价机票微信监控器

每 15 分钟在云端执行一次，分批扫描未来 180 天内从杭州、上海及周边机场出发的单程经济舱。当 Aviasales Data API 的近期缓存搜索记录显示 **每名成人不超过 ¥300、两人估算总价不超过 ¥600** 时，通过 PushPlus 推送到微信，并要求用户在下单前复核实时价格和座位。

## 已落实的需求

- 出发优先级：杭州萧山 > 上海浦东/虹桥 > 宁波/义乌 > 南京/温州/无锡/台州。
- 国内、国际目的地均不限；HGH、SHA、PVG 每 15 分钟都扫描，其他机场每轮轮换一个。
- Travelpayouts / Aviasales Data API 同时查询中国、美国和新加坡市场，发现任意目的地的近期缓存低价。
- 缓存单人价不超过 ¥300 才进入通知；两人估算总价按单人价乘以 2 展示。
- 行李、两张座位和最终含税结算价均标注为“下单前确认”。
- 同一航班不会重复轰炸微信；降价至少 ¥1，或消失 24 小时后重新出现，才再次推送。
- 候选航线默认 3 小时复核一次，以控制免费 API 用量；每轮最多复核 4 个候选。
- 程序密钥只放在 GitHub Secrets，不写进代码或配置文件。

## 必须知道的边界

这不是对携程、飞猪、同程页面进行违规爬取的程序。航空价格接口不可能免费、合法且完整覆盖所有中国 OTA：

- Travelpayouts 价格来自 Aviasales 用户最近搜索形成的缓存，通常保存 2–7 天，不是实时库存。
- 推送不代表当前仍有两张票，也不能保证付款页最终含税价不超过 ¥300/人。
- 青年/学生专享价不一定进入公开缓存，程序不会伪装学生身份。
- 推送中的 Aviasales 和 Google Flights 链接只用于人工复核；付款前必须检查两名成人总价、座位、行李和退改规则。

代码已做成可扩展结构。以后取得 Skyscanner、航司或其他正规 API 权限后，可在 `src/flight_monitor/providers/` 增加数据源，不需要重写通知和去重逻辑。

## 免费云端方案

推荐使用一个**公开的 GitHub 仓库**。GitHub 标准托管运行器对公开仓库免费；私有免费账户每月只有有限分钟数，而 15 分钟一次至少约 2,880 次/月，通常会超过私有仓库免费额度。

北京时间 01:00–06:59 暂停监控，07:00 恢复。GitHub 官方会在公开仓库连续 60 天没有任何活动后停用定时工作流；届时进入 Actions 页面重新启用，或正常提交一次代码即可。定时任务也可能因平台繁忙延迟几分钟，不是严格实时服务器。

## 第一步：申请两个免费凭证

### 1. PushPlus 微信通知

1. 打开 [PushPlus 官网](https://www.pushplus.plus/)，使用微信登录。
2. 关注其微信公众号并完成绑定。
3. 在个人中心复制“消息 token”（推荐单独创建一个机票监控消息 token）。
4. 记为 `PUSHPLUS_TOKEN`。

### 2. Travelpayouts 低价发现

1. 注册 [Travelpayouts](https://www.travelpayouts.com/)。
2. 打开开发者/API 页面申请 Data API token。
3. 记为 `TRAVELPAYOUTS_TOKEN`。

这是运行价格发现所必需的 token。

## 第二步：部署到 GitHub

1. 新建一个公开仓库，例如 `flight-deal-monitor`。
2. 将 `flight-deal-monitor` 目录**里面的全部文件**上传到仓库根目录；上传后应能直接看到 `README.md`、`config.json` 和 `.github`。
3. 打开仓库 `Settings → Secrets and variables → Actions`。
4. 新增两个 Repository secrets：

   - `PUSHPLUS_TOKEN`
   - `TRAVELPAYOUTS_TOKEN`

5. 打开 `Actions → 低价机票监控 → Run workflow`，先勾选“只测试微信通知”。
6. 微信收到测试消息后，再手动运行一次正常监控。
7. 后续工作流会在每小时第 7、22、37、52 分钟自动运行。

状态通过 GitHub Actions Cache 保存，不会提交到公开仓库。若缓存被平台清理，最坏结果是少量旧优惠可能重新通知一次，不影响价格判断。

## 本地测试（可选）

PowerShell：

```powershell
cd C:\path\to\flight-deal-monitor
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
$env:TRAVELPAYOUTS_TOKEN="你的Token"
$env:PUSHPLUS_TOKEN="你的Token"
python -m flight_monitor.app --test-notification
python -m flight_monitor.app --dry-run
```

正式执行：

```powershell
python -m flight_monitor.app
```

## 调整规则

编辑 `config.json`：

- `max_price_per_adult`：每人最高含税价，当前为 300。
- `days_ahead`：未来监控天数，当前为 180。
- `every_run_origins`：每轮都扫描的机场，当前为 HGH、SHA、PVG。
- `rotating_origins`：低优先级轮换机场，当前每轮扫描其中一个。
- `travelpayouts_markets`：并行查询的市场缓存，默认 `cn`、`us`、`sg`。
- `candidate_recheck_minutes`：同一路线日期的实时复核间隔。
- `max_candidates_to_verify_per_run`：每轮最多实时复核数量。

不要把任何 token 或 secret 写入 `config.json`。
