# cx-watcher — 学习通作业自动监控系统

Mac 常驻轻量监控脚本：纯 HTTP 轮询学习通（超星）作业列表，发现新"未交"作业/随堂练习时写告警文件 + 弹 macOS 通知，并通过修改 WorkBuddy 调度器 `next_run_at` 即时唤醒 AI 自动作答提交（随堂练习 3~5 分钟内交掉，全程无需人工）。

## 特性

- **零 token 监控**：上课时段每 60 秒纯 HTTP 轮询，非上课时段每 10 分钟，凌晨休眠
- **按课表轮询**：周一~周六上课时段 + 周日 3~4 节，周六全天休
- **冬夏令作息自动切换**：上午 8:00-9:50 / 10:10-12:00 全年固定；下午按月份切换冬令（14:00/16:00 起）与夏令（14:30/16:30 起）
- **自动重登**：凭证失效时用超星 fanyalogin 接口自动重登（AES-CBC 加密）
- **即时唤醒 AI**：发现告警后 sqlite3 修改 WorkBuddy automations 表 `next_run_at`，实测 ~40 秒内被 AI 领取处理
- **单实例锁**：flock 防重复运行，可与 launchd 共存

## 文件说明

| 文件 | 说明 |
|------|------|
| `watcher.py` | 监控脚本核心 |
| `courses.example.json` | 课程接口 URL 模板（复制为 courses.json 填入自己的，真实文件不入库） |
| `state.example.json` | 作业状态基线模板（复制为 state.json 使用） |
| `credentials.example.json` | 凭证模板，复制为 `cx-credentials.json` 并填入真实账号（不入库） |
| `automations_backup.txt` | 配套 WorkBuddy 自动化的 prompt/rrule 导出 |
| `RESTORE.md` | 恢复指南 |

## 快速开始

```bash
pip3 install requests pycryptodome
cp credentials.example.json cx-credentials.json   # 填入学习通账号密码
python3 watcher.py                                # 或 nohup 后台运行
```

## 配套 WorkBuddy 自动化

- **随堂练习即时处理器**：每小时兜底 + 被 DB 唤醒，读 alert.json 认领处理（随堂练习直接提交、普通作业暂存、作图题 matplotlib 画图插入答题框）
- **每日 7:30 兜底全检**：全量核对、维护脚本健康、刷新过期接口 URL

## ⚠️ 安全提示

`cx-credentials.json` 和 `cookies.json` 含账号密码/会话凭证，已在 `.gitignore` 中排除，**不要提交到任何仓库**。

## License

MIT
