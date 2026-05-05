# PQ-BitEdu

一个教学型、类比特币、抗量子签名可插拔的区块链基座实现。

## 当前状态

已完成的基座能力：

- UTXO 模型
- 交易输入输出与手续费
- `pubkey_hash` 锁定
- SOIBS 同拥有者输入打包签名
- 区块、Merkle Root、PoW
- 最长链 / 累计工作量优先
- coinbase 奖励
- 单机节点与最小演示流程

签名层设计为可插拔：

- 默认提供一个**纯 Python 手写的教学版 `ML-DSA-44` 风格后端**
- 它保留了模格矩阵、短秘密向量、Fiat-Shamir 挑战和有界签名向量这些核心逻辑
- 同时保留 `Merkle-Lamport` 作为额外的后量子备用方案，方便做对照实验

说明：

- 当前 `ml-dsa-44` 是**教学实现**，用于展示 ML-DSA 的核心签名逻辑，而不是严格按 FIPS 204 位级兼容的工业实现
- 如果后续你还想切回 `liboqs` 之类的标准库后端，接口层已经是可插拔的

授权组织支持两种模式：

- `soibs`：同拥有者输入打包签名
- `per_input`：逐输入见证基线模式，便于做实验对比

## 多智能体环境

项目现在已经包含一个本地多智能体仿真层：

- `MultiAgentEnvironment`：统一管理区块链、节点、钱包、事件流和回合推进
- `AgentToolbox`：向 Agent 暴露 `inspect_chain`、`inspect_wallet`、`send_transaction`、`mine_block` 等工具
- `scripted controllers`：提供本地可跑的矿工/交易者策略，方便在不接真实模型时先调系统
- `ProviderConfig`：预留 DeepSeek / Gemini 的模型配置位，下一阶段只需补真实 API adapter

当前边界：

- 这一层已经能做**单机多智能体仿真**
- 还没有接入真实 DeepSeek / Gemini API
- 还没有做多进程、多节点网络广播或线上部署

## 运行多智能体 demo

```powershell
python -m pq_bitedu.agent_demo
```

## 运行 demo

```powershell
python -m pq_bitedu.demo
```

## 运行测试

```powershell
python -m unittest discover -s tests -v
```
