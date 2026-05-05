# PQ-BitEdu

一个用于课程展示的教学型区块链项目，主题是：

- Bitcoin-like 链基座
- 抗量子签名
- SOIBS 交易授权优化
- 多智能体市场模拟
- 轻量多节点攻击演示

## 当前已经实现

### 链基座

- UTXO 模型
- 交易输入 / 输出
- `pubkey_hash` 锁定
- coinbase 奖励
- Merkle Root
- PoW 挖矿
- 最长累计工作量选链
- 区块奖励减半
- 难度调整

### 抗量子签名

- 项目默认签名后端是项目内置的教学型 `ML-DSA` 风格实现
- 默认标识为 `ml-dsa-44`
- 另带一个 `Merkle-Lamport` 后备后量子签名方案

注意：

- 当前不是 `liboqs` 的工业级 FIPS 204 落地
- 当前是为了课程展示而写的可解释教学实现

### SOIBS

- 支持 `per_input` 基线模式
- 支持 `SOIBS` 合并同拥有者输入签名
- 可以直接做交易体积、签名大小、验签次数对照

### 多智能体市场模拟

- 单机多智能体环境
- 现金账户 + 持币账户
- 外部资本买入机制
- 实时市场页面
- DeepSeek 与 Gemini 双厂商对照

### 已接入真实 API

当前项目已经接入真实模型 API，不是只做本地脚本假人：

- DeepSeek API
- Gemini API

对应适配层在：

- `pq_bitedu/agentic/providers.py`

Hosted 市场模拟入口在：

- `pq_bitedu/market_simulation.py`
- `pq_bitedu/live_dashboard.py`

### 攻击演示

- 双花攻击演示
- 51% 私链重组演示
- 独立攻击演示页面

## 页面入口

### 主市场页面

- `reports/market_dashboard_hosted.html`
- `reports/market_dashboard_scripted.html`

### 攻击演示页面

- `reports/attack_dashboard.html`

### 三方案对照页面

- `reports/quantum_dashboard.html`

## 运行方式

### 运行测试

```powershell
python -m unittest discover -s tests -v
```

### 运行基础链 demo

```powershell
python -m pq_bitedu.demo
```

### 运行多智能体实时市场

离线 scripted 版：

```powershell
python -m pq_bitedu.live_dashboard --mode scripted --autostart
```

真实 hosted 版：

```powershell
python -m pq_bitedu.live_dashboard --mode hosted --model deepseek-v4-flash --autostart
```

### 生成攻击演示页

```powershell
python -m pq_bitedu.attack_dashboard --output reports/attack_dashboard.html
```

### 生成三方案对照页

```powershell
python -m pq_bitedu.quantum_dashboard --output reports/quantum_dashboard.html
```

## 环境变量

项目会从 `.env` 读取 API key。

常用项：

- `DEEPSEEK_API_KEY`
- `GEMINI_API_KEY`

`.env` 不应提交到仓库。
