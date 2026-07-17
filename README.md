# 低价机票微信监控器

每 15 分钟在云端执行一次，分批扫描未来 180 天内从杭州、上海及周边机场出发的单程经济舱。只有在实时确认 **2 名成人均不超过 ¥300/人、两人含税费总价不超过 ¥600** 后，才通过 PushPlus 推送到微信。

## 已落实的需求

- 出发优先级：杭州萧山 > 上海浦东/虹桥 > 宁波/义乌 > 南京/温州/无锡/台州。
- 国内、国际目的地均不限；一次任务扫描一个机场，32 个时段构成加权循环。
- Travelpayouts 发现任意目的地的缓存低价，Amadeus 再检查两张成人票的实时座位和最终价格。
- 最终价格使用 Amadeus Flight Offers Price 二次确认，按 `grandTotal` 判断。
- 行李额有数据就展示；没有行李或接口未提供时明确标注。
- 同一航班不会重复轰炸微信；降价至少 ¥1，或消失 24 小时后重新出现，才再次推送。
- 候选航线默认 3 小时复核一次，以控制免费 API 用量；每轮最多复核 4 个候选。
- 程序密钥只放在 GitHub Secrets，不写进代码或配置文件。

## 必须知道的边界

这不是对携程、飞猪、同程页面进行违规爬取的程序。航空价格接口不可能免费、合法且完整覆盖所有中国 OTA：

- Travelpayouts 价格是用于“发现”的近期缓存价，不能直接触发通知。
- Amadeus 实时复核覆盖大量传统航司，但官方说明不覆盖部分廉航及少数航空公司；因此可能漏掉 OTA 独家价、会员价、青年/学生专享价。
- 青年/学生价可以作为未来数据源的候选，但当前 Amadeus 成人搜索通常只返回公开成人价，程序不会伪装学生身份。
- 推送中的携程和 Google Flights 是方便复查的搜索入口，并不代表数据来自它们。付款页价格仍可能在几分钟内变化。
- `AMADEUS_ENVIRONMENT=test` 只有有限缓存测试数据，不能用于正式监控；正式运行应设为 `production`。

代码已做成可扩展结构。以后取得 Skyscanner、航司或其他正规 API 权限后，可在 `src/flight_monitor/providers/` 增加数据源，不需要重写通知和去重逻辑。

## 免费云端方案

推荐使用一个**公开的 GitHub 仓库**。GitHub 标准托管运行器对公开仓库免费；私有免费账户每月只有有限分钟数，而 15 分钟一次至少约 2,880 次/月，通常会超过私有仓库免费额度。

注意：GitHub 官方会在公开仓库连续 60 天没有任何活动后停用定时工作流。届时进入 Actions 页面重新启用，或正常提交一次代码即可。定时任务也可能因平台繁忙延迟几分钟，不是严格实时服务器。

## 第一步：申请三个免费凭证

### 1. PushPlus 微信通知

1. 打开 [PushPlus 官网](https://www.pushplus.plus/)，使用微信登录。
2. 关注其微信公众号并完成绑定。
3. 在个人中心复制“消息 token”（推荐单独创建一个机票监控消息 token）。
4. 记为 `PUSHPLUS_TOKEN`。

### 2. Travelpayouts 低价发现

1. 注册 [Travelpayouts](https://www.travelpayouts.com/)。
2. 打开开发者/API 页面申请 Data API token。
3. 记为 `TRAVELPAYOUTS_TOKEN`。

没有这个 token 也能运行，但会改用 Amadeus 缓存发现候选，API 用量更高、覆盖可能更少。

### 3. Amadeus 实时复核

1. 注册 [Amadeus for Developers](https://developers.amadeus.com/)。
2. 创建 Self-Service 应用，先取得测试环境的 API Key 和 API Secret。
3. 在后台申请/切换到 Production，取得生产环境 Key 和 Secret。
4. 分别记为 `AMADEUS_CLIENT_ID`、`AMADEUS_CLIENT_SECRET`。

Amadeus 生产环境有每月免费调用额度，超额规则可能变化。请在 Amadeus 后台查看当前额度和账单设置；本项目通过候选冷却和单轮上限降低用量，但第三方政策变化时无法保证永远零费用。若平台要求绑定付款方式，请在其后台设置可用的消费限制，或先不要启用生产环境。

## 第二步：部署到 GitHub

1. 新建一个公开仓库，例如 `flight-deal-monitor`。
2. 将 `flight-deal-monitor` 目录**里面的全部文件**上传到仓库根目录；上传后应能直接看到 `README.md`、`config.json` 和 `.github`。
3. 打开仓库 `Settings → Secrets and variables → Actions`。
4. 新增四个 Repository secrets：

   - `PUSHPLUS_TOKEN`
   - `TRAVELPAYOUTS_TOKEN`
   - `AMADEUS_CLIENT_ID`
   - `AMADEUS_CLIENT_SECRET`

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
$env:AMADEUS_CLIENT_ID="你的ID"
$env:AMADEUS_CLIENT_SECRET="你的Secret"
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
- `origin_cycle`：机场加权循环；重复越多，扫描优先级越高。
- `candidate_recheck_minutes`：同一路线日期的实时复核间隔。
- `max_candidates_to_verify_per_run`：每轮最多实时复核数量。

不要把任何 token 或 secret 写入 `config.json`。
