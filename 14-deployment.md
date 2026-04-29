# 14. Deployment

## 14.1 Các môi trường

| Env | Mục đích | Risk | dry_run |
|---|---|---|---|
| `dev` | Lập trình, unit test | 0 | true |
| `dry_run` | Pipeline chạy nhưng không gửi lệnh | 0 | true |
| `demo` | MT5 demo account, lệnh thật trên demo | 0 (broker demo) | false |
| `staging` | Demo account riêng, identical với live | 0 | false |
| `live` | Real money | thật | false |

Promotion chỉ một chiều: `dev → dry_run → demo → staging → live`. Không skip.

---

## 14.2 Hardware / hosting

### Option 1 — Single Windows VPS (đơn giản)

```text
- Windows VPS gần broker server (Tokyo/London/NY tùy broker)
- 4 vCPU, 8 GB RAM, 100 GB SSD
- Cài MT5 + Python 3.11
- Service Python chạy bằng nssm hoặc Task Scheduler
- Ưu: latency thấp với MT5, đơn giản
- Nhược: GPU yếu, model lớn chạy chậm
```

### Option 2 — Tách MT5 Windows + AI Linux (production)

```text
- Windows VPS: chỉ chạy MT5 + EA executor
- Linux GPU server: AI inference + storage
- Bridge: ZeroMQ / FastAPI HTTPS
- Ưu: GPU đầy đủ, scale model
- Nhược: cần thiết kế bridge, ops phức tạp hơn
```

### Option 3 — Cloud-managed (khi đã ổn)

```text
- AI server: cloud GPU (A10/A100)
- MT5 host: dedicated Windows VPS
- DB: managed Postgres + Timescale
- Monitoring: Grafana Cloud / managed Prometheus
- Secrets: cloud secret manager
```

---

## 14.3 Process supervision

### Linux (systemd)

```ini
[Unit]
Description=AI MT5 Multi-Model Bot
After=network-online.target

[Service]
Type=simple
User=ai-mt5
WorkingDirectory=/opt/ai-mt5-multimodel-bot
EnvironmentFile=/opt/ai-mt5-multimodel-bot/.env
ExecStart=/opt/ai-mt5-multimodel-bot/.venv/bin/python -m src.main
Restart=on-failure
RestartSec=10
StandardOutput=append:/var/log/ai-mt5/runner.log
StandardError=append:/var/log/ai-mt5/runner.err

[Install]
WantedBy=multi-user.target
```

### Windows (nssm)

```text
nssm install AI-MT5-Bot "C:\path\to\python.exe" "-m src.main"
nssm set AI-MT5-Bot AppDirectory "C:\path\to\repo"
nssm set AI-MT5-Bot AppStdout "C:\logs\ai-mt5\runner.log"
nssm set AI-MT5-Bot AppStderr "C:\logs\ai-mt5\runner.err"
nssm set AI-MT5-Bot Start SERVICE_AUTO_START
```

---

## 14.4 Pre-deploy checklist

Trước khi promote môi trường:

```text
[ ] Tất cả tests xanh (unit, integration, property)
[ ] Backtest report up-to-date trong reports/
[ ] Config validate qua pydantic không lỗi
[ ] Secrets đã set trong env (không có placeholder)
[ ] Disk space >= 20 GB free
[ ] Log rotation đã config
[ ] Monitoring + alert hoạt động (test alert thủ công)
[ ] Kill switch file path đã tồn tại và writable
[ ] Reconcile sau restart đã test
[ ] DB schema migrate
[ ] Backup DB lần cuối
```

---

## 14.5 Deploy quy trình

### MVP (rsync hoặc git pull)

```bash
# trên server
cd /opt/ai-mt5-multimodel-bot
git fetch && git checkout <commit-hash>
uv sync --frozen           # hoặc poetry install --no-dev
sudo systemctl restart ai-mt5-bot
sudo systemctl status ai-mt5-bot
tail -f /var/log/ai-mt5/runner.log
```

### Production (Docker cho AI server, native cho MT5)

```bash
docker build -t ai-mt5-server:1.2.3 .
docker push registry/.../ai-mt5-server:1.2.3
ssh ai-server "docker pull ... && docker compose up -d"
```

MT5 host vẫn deploy native (Windows + nssm) vì không docker hóa được terminal.

---

## 14.6 Promotion từ dry_run sang demo

```text
1. Soak ở dry_run >= 3 ngày
2. So sánh forecast vs giá thực sau 3-7 ngày
3. Set DRY_RUN=false trong env demo
4. Restart service
5. Monitor sát 24h đầu, sẵn sàng kill switch
6. Sau 1 tuần ổn định, mở thêm symbol nếu cần
```

---

## 14.7 Promotion từ demo sang live

```text
1. Demo soak >= 2-4 tuần, không lỗi nghiêm trọng
2. Backtest report up-to-date, OOS positive
3. Risk officer + quant lead approve
4. Switch broker_profile sang live broker
5. Set risk.base_risk_per_trade = 0.001 (0.1%)
6. Set max_total_drawdown = 0.03 (3%)
7. Bật alert nghiêm ngặt 24/7
8. Operator on-call đầu tuần đầu
```

---

## 14.8 Rollback

```text
- Mỗi deploy lưu git commit hash + config snapshot vào DB
- Rollback = checkout commit cũ + restart
- Nếu config gây kill switch -> set kill_switch.manual_file, debug, fix, redeploy
- Không rollback bằng force-push hay sửa git history
```

---

## 14.9 Thay đổi config trên live

```text
- Quy trình:
    1. Mở PR thay đổi config
    2. Code review + risk officer review (4-eyes cho file risk.yaml)
    3. Merge
    4. Deploy theo quy trình thường
- KHÔNG sửa trực tiếp file config trên server (mất audit trail)
- Mọi thay đổi log vào DB và Telegram alert
```

---

## 14.10 DB migration

```text
- Sử dụng Alembic (Postgres) hoặc tự script SQL idempotent (SQLite)
- Migration test trên staging trước
- Backup DB trước migration trong production
- Migration phải reversible
```

---

## 14.11 Time sync

Timezone và clock drift là bug-source phổ biến:

```text
- Server UTC, OS time sync NTP
- Dữ liệu MT5 lưu UTC
- Display có thể local nhưng store UTC
- Mỗi tick, kiểm tra (server_time - bar_time) hợp lý
- Drift > 5s -> alert, dừng trade
```

---

## 14.12 Secrets rotation

```text
- MT5 password đổi 90 ngày
- API key (news, OpenAI) rotate khi nghi rò rỉ
- Telegram bot token rotate khi đổi operator
- Tất cả thay đổi qua secret manager / env update + restart, không hard-code
```

---

## 14.13 Disaster recovery

```text
- Backup DB hàng ngày (Postgres dump / SQLite copy)
- Backup logs/ rotated, giữ >= 90 ngày
- Backup config snapshots
- Document quy trình restore trên runbook
- Test restore mỗi quý
- Có sẵn instance dự phòng (cold standby cho production)
```

---

## 14.14 SLO mục tiêu

| Metric | Target |
|---|---|
| Pipeline tick latency | < 5s (Option A) / < 1s (Option B) |
| MT5 connection uptime | >= 99.5% trading hours |
| Order_check pass rate | >= 99% |
| Order_send success rate | >= 98% |
| Telegram alert latency | <= 30s |
| Kill switch response | <= 10s |

Nếu vi phạm SLO 2 ngày liên tiếp -> incident review.
