# 学习通作业自动监控系统 — 备份与恢复指南

备份日期：2026-09-16
备份人：WorkBuddy（Claw）
账号：学习通 （你的学习通账号）（童思远，西安建筑科技大学）

## 这个系统是干什么的

1. **cx-watcher 脚本**：Mac 常驻轻量监控，上课时段每 60 秒纯 HTTP 轮询学习通 5 门课的作业列表（零 AI token）。发现新"未交"作业/随堂练习 → 写 alert.json + Mac 系统通知。
2. **DB 唤醒机制**：脚本发现告警后，用 sqlite3 把 WorkBuddy 调度器 automations 表的 `next_run_at` 改为当前时间，即时唤醒 AI 处理器（实测 ~40 秒内被领取）。
3. **随堂练习即时处理器**（WorkBuddy 自动化，id 39be7133-76fe-4ed2-a02a-3b8cb3b4f244）：每小时兜底 + 被 DB 唤醒；用 agent-browser 打开作业直达链接，AI 逐题作答，随堂练习直接提交、普通作业暂存。push_to_wechat=1。
4. **每日 7:30 兜底全检**（WorkBuddy 自动化）：全量核对所有课程作业/考试，处理普通作业，维护脚本健康（拉活进程、刷新 cookies.json/courses.json）。
5. **规则**：所有新作业自动作答暂存；随堂练习最高优先级立即提交；作图题 matplotlib 画图存桌面 `~/Desktop/学习通作业/<课程名>/<日期+作业名>/`；霾污染防治"结业-调研报告"禁止代写（截止 2026-09-23 16:20）。

## 目录结构

- `cx-watcher/watcher.py` — 监控脚本核心（含轮询日历、冬夏令作息切换、fanyalogin 自动重登）
- `cx-watcher/courses.json` — 5 门课的作业列表接口 URL（每课 enc 不同）
- `cx-watcher/cookies.json` — 登录凭证（失效时脚本自动重登并更新）
- `cx-watcher/state.json` — 已见作业状态基线
- `memory/` — WorkBuddy 记忆文件（MEMORY.md 长期 + 每日日记）
- `automations/automations_backup.txt` — WorkBuddy 自动化的完整 prompt/rrule 导出

## 恢复步骤（换新 Mac 时）

1. 安装依赖：`pip3 install requests pycryptodome`；安装 agent-browser（`npm install -g agent-browser`）。
2. 把 `cx-watcher/` 目录还原到 `/Users/heyi/WorkBuddy/Claw/cx-watcher/`。
3. 启动监控：
   ```
   nohup /Users/heyi/.workbuddy/binaries/python/versions/3.13.12/bin/python3 \
     /Users/heyi/WorkBuddy/Claw/cx-watcher/watcher.py \
     >> /Users/heyi/WorkBuddy/Claw/cx-watcher/launchd.log 2>&1 &
   ```
   （python 路径按新机实际调整；脚本有单实例 flock 锁，不会重复跑）
4. 防休眠：`nohup caffeinate -s &`（合盖会睡，出门需开盖插电）。
5. 在 WorkBuddy 里按 `automations/automations_backup.txt` 重建两个自动化（随堂练习即时处理器 + 每日 7:30 兜底全检），建好后把新 id 填进 watcher.py 的 `DISPATCHER_ID`，并把两个自动化的 push_to_wechat 置 1。
6. 若 cookie 过期：脚本会用账号密码自动重登（fanyalogin，AES-CBC）；若课程 enc 变化导致接口失效，从浏览器重新采集作业列表 URL 更新 courses.json（每日全检自动化也会自动维护）。
7. 装开机自启（可选）：`cp com.heyi.cx-watcher.plist ~/Library/LaunchAgents/ && launchctl load -w ~/Library/LaunchAgents/com.heyi.cx-watcher.plist`（首次加载需在系统设置允许后台项）。

## 已知注意事项

- 密码（（你的密码，见 cx-credentials.json，不入库））已写入脚本 cookies 重登逻辑与自动化 prompt，属敏感信息，备份文件不要外传。
- 学习通接口（/mooc2/work/list）为逆向所得，超星改版需按 memory 日记里的解析规则微调。
- 作息：上午 8:00-9:50 / 10:10-12:00 全年固定；下午冬令（10/1-4/30）14:00-15:50 / 16:00-17:50，夏令（5/1-9/30）14:30-16:20 / 16:30-18:20。脚本按月份自动切换。
- 课表：周六无课不轮询；周日仅 3~4 节（10:10-12:00）金塑课。
