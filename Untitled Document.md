# PQ-BitEdu：一种基于 ML-DSA 与同拥有者输入打包签名的类比特币教学型区块链系统设计
## 摘要
本文设计并实现一个面向教学与实验的类比特币区块链系统 **PQ-BitEdu**。该系统尽量保留比特币的核心机制，包括 **UTXO 模型、交易输入输出结构、coinbase 区块奖励、PoW 挖矿、Merkle Root、最长链/累计工作量优先** 等，只对签名认证层进行替换：将传统椭圆曲线签名替换为后量子数字签名 **ML-DSA**。ML-DSA 已被 NIST 最终标准化，属于可重复使用的格基后量子签名方案，适合作为椭圆曲线签名的后量子替代。

针对 ML-DSA 在 UTXO 区块链中“公钥和签名体积显著增大、逐输入见证开销过高”的问题，本文进一步提出一个系统层小改动：**同拥有者输入打包签名（Same-Owner Input Bundle Signature, SOIBS）**。该机制允许一笔交易中由同一公钥哈希控制的多个输入共享一份公钥与一份 ML-DSA 签名，从而显著降低后量子签名在链上带来的体积与验证开销。ML-DSA-44 的公钥长度为 1312 bytes、签名长度为 2420 bytes，而 Bitcoin 的 BIP340 Schnorr 公钥与签名分别仅为 32 bytes 和 64 bytes，因此在不改变 UTXO 核心语义的前提下，见证压缩具有明确工程意义。

本文目标不是提出工业级新密码算法，而是在尽量保持比特币机制不变的前提下，构建一个具有真实后量子特征、可运行、可实验、可攻防分析的教学型区块链系统。

---

## 1. 研究背景与动机
比特币的安全体系由多个层面共同支撑：交易认证依赖数字签名，账本一致性依赖 PoW 与最长链规则，防篡改依赖区块哈希链与 Merkle 树。在这些机制中，**签名层**负责回答一个最基本的问题：**一笔交易是否确实由 UTXO 所属者授权发起**。

传统比特币体系依赖椭圆曲线密码学。该体系在经典计算环境下高效而成熟，但其安全性依赖离散对数难题；一旦量子计算条件成熟，相关基础困难问题将面临明显风险。因此，后量子数字签名成为区块链体系中一个自然且重要的替代方向。NIST 已最终发布 ML-DSA 与 SLH-DSA 等后量子数字签名标准，其中 ML-DSA 属于格基签名方案，支持可重复签名，适合承担类似比特币交易认证这种高频签名任务。

但是，将后量子签名直接“硬替换”到比特币式 UTXO 系统中，会遇到一个非常现实的问题：**链上见证膨胀**。ML-DSA 的公钥和签名远大于传统椭圆曲线签名；在 UTXO 体系中，如果仍采用“每个输入单独携带一份公钥和签名”的结构，则交易体积会迅速上升，区块可容纳的交易数量下降，节点验证负担也会增大。ML-DSA 的 rejection sampling 特性与侧信道实现注意事项，也说明其工程集成复杂度高于传统签名。

因此，本文的核心思路不是重新发明底层密码学，而是：

1. **在密码学层面，采用标准后量子签名 ML-DSA；**
2. **在系统层面，设计一种适合 UTXO 交易结构的轻量改进，用于缓解后量子签名的链上开销。**

---

## 2. 设计目标
PQ-BitEdu 的设计目标如下：

### 2.1 保留比特币核心机制
系统必须尽可能保留比特币的核心机制，而不是退化成一个“只有区块外壳”的简化账本。具体要求包括：

+  使用 **UTXO** 模型 
+  使用 **输入引用旧输出** 的交易结构 
+  输出锁定到 `pubkey_hash`
+  花费时提供 `public_key` 与 `signature`
+  使用 **PoW 挖矿**
+  使用 **coinbase 交易** 发放区块奖励 
+  使用 **手续费 = 输入总额 - 输出总额**
+  使用 **Merkle Root**
+  使用 **最长链 / 累计工作量优先**

### 2.2 签名层必须具备真实后量子特征
签名算法不能再使用 ECDSA、Schnorr 或 RSA 过渡方案，而应直接使用**真正进入标准化流程的后量子签名算法**。因此本文选择 **ML-DSA-44** 作为默认实现方案。

### 2.3 工程可实现
系统需适合作为课程项目实现，因此：

+  不做真实 P2P 网络，可采用单机多节点模拟 
+  不实现完整 Bitcoin Script VM，只保留固定语义的支付脚本 
+  不实现 SegWit、Taproot、多签、时间锁等扩展特性 
+  签名库优先调用 `liboqs` / `liboqs-python`，不手写 ML-DSA 数学细节。 

### 2.4 有明确原创点
项目不能只是“把 GitHub 仓库跑起来”。因此需要一个与后量子签名引入直接相关、但又不破坏比特币机制本质的小创新。本文提出的 SOIBS 就承担这一角色。

---

## 3. 总体系统架构
系统可分为四层：

### 3.1 账户与密钥层
每个用户持有一组 ML-DSA 密钥对：

+ `private_key`
+ `public_key`

地址不直接等于公钥，而是：

pubkey_hash=SHA256(public_key)pubkey\_hash = SHA256(public\_key)pubkey_hash=SHA256(public_key)

这与比特币“输出锁定到公钥哈希，而非直接锁定到公钥”的思路一致。

### 3.2 交易层
交易由输入和输出组成：

+  输入引用旧输出 `(prev_txid, prev_vout)`
+  输出包含金额 `value` 与 `pubkey_hash`

系统使用固定支付语义，相当于教学版的：

```plain
pay-to-public-key-hash
```

但不实现完整脚本指令集。

### 3.3 区块层
区块由区块头和交易列表组成。区块头至少包括：

+ `version`
+ `prev_block_hash`
+ `merkle_root`
+ `timestamp`
+ `target`
+ `nonce`

### 3.4 共识层
采用 PoW 与最长链规则：

+  矿工不断调整 `nonce`
+  满足 `block_hash < target` 的区块视为有效 
+  节点优先接受累计工作量更大的链 

---

## 4. 交易与 UTXO 机制
## 4.1 UTXO 定义
系统维护一个全局 UTXO 集：

UTXOSet={(txid,vout)↦TxOutput}UTXOSet = \{ (txid, vout) \mapsto TxOutput \}UTXOSet={(txid,vout)↦TxOutput}

每个 `TxOutput` 包含：

+ `value`
+ `pubkey_hash`

只有对应私钥持有者能够构造合法签名并花费该 UTXO。

## 4.2 交易结构
一笔普通交易可定义为：

+ `version`
+ `inputs`
+ `outputs`
+ `locktime`
+ `auth_bundles`（后文 SOIBS 新增） 

其中每个输入包含：

+ `prev_txid`
+ `prev_vout`
+  不直接携带单独签名字段，而是由 `auth_bundles` 授权 

每个输出包含：

+ `value`
+ `pubkey_hash`

## 4.3 手续费规则
普通交易的手续费为：

fee=∑input_value−∑output_valuefee = \sum input\_value - \sum output\_valuefee=∑input_value−∑output_value

若结果为负，则交易非法。

---

## 5. 使用 ML-DSA 替换椭圆曲线签名
## 5.1 选择理由
本文选择 **ML-DSA-44** 作为默认参数集，原因如下：

1.  它是 **NIST 最终发布的后量子数字签名标准**之一； 
2.  属于**可重复签名**方案，适合比特币式高频交易签名； 
3.  比哈希基一次性签名更适合承担“长期账户控制”角色； 
4.  已有成熟实现可通过 `liboqs` 调用。 

## 5.2 接口抽象
系统中定义统一签名接口：

+ `keygen()`
+ `sign(private_key, msg)`
+ `verify(public_key, msg, signature)`

默认实现绑定 ML-DSA-44。

## 5.3 被签名消息
为了保持比特币风格，签名不应只绑定“地址”，而必须绑定具体花费上下文。  
因此，定义每个授权组的签名消息为：

msg=H(version∥ordered_inputs∥ordered_outputs∥bundle_input_indices∥referenced_utxo_values∥referenced_utxo_pubkey_hash)msg = H( version \parallel ordered\_inputs \parallel ordered\_outputs \parallel bundle\_input\_indices \parallel referenced\_utxo\_values \parallel referenced\_utxo\_pubkey\_hash )msg=H(version∥ordered_inputs∥ordered_outputs∥bundle_input_indices∥referenced_utxo_values∥referenced_utxo_pubkey_hash)

这意味着签名同时绑定：

+  当前整笔交易的输入输出结构 
+  本 bundle 授权的输入编号集合 
+  这些输入所引用的 UTXO 金额和锁定哈希 

这样可避免重放和简单替换攻击。

---

## 6. ML-DSA 的主要缺点
将 ML-DSA 直接引入 Bitcoin-like 系统后，会出现以下问题：

### 6.1 公钥和签名体积显著增大
ML-DSA-44 参数下：

+  公钥：1312 bytes 
+  签名：2420 bytes 

相比之下，Bitcoin 现有 Schnorr 的公钥和签名分别只有 32 bytes 和 64 bytes。  
这意味着如果仍按“每个输入单独携带公钥和签名”的方式构造见证，交易体积会急剧膨胀。

### 6.2 验签与签名实现复杂度更高
ML-DSA 引入 rejection sampling，签名过程并非完全线性直接完成；同时实现层需要特别注意常数时间与侧信道问题。NIST 与相关研究均已讨论 Dilithium/ML-DSA 的工程实现难点。

### 6.3 UTXO 逐输入见证模式放大缺点
Bitcoin 的 UTXO 模型本身会鼓励“多输入合并花费”。如果多个输入都来自同一地址，而每个输入都重复携带一份大型公钥和签名，则后量子签名的劣势会被进一步放大。

因此，本文创新点应放在**系统层见证组织方式**，而不是修改 ML-DSA 数学本体。

---

## 7. 本文创新：SOIBS（同拥有者输入打包签名）
## 7.1 设计动机
在一笔 UTXO 交易中，多个输入可能都来自同一拥有者。  
如果这些输入所引用的旧输出锁定到同一个 `pubkey_hash`，那么实际上它们都需要同一个公钥来证明控制权。

在传统逐输入见证模式下，会出现大量重复：

+  重复公开相同公钥 
+  重复进行相同拥有者的多次签名 
+  重复消耗区块空间与节点验签成本 

SOIBS 的核心思想是：

**将同一笔交易中、由同一 **`**pubkey_hash**`** 控制的多个输入打包成一个 bundle，只用一份 **`**public_key**`** 和一份 ML-DSA 签名完成授权。**

## 7.2 结构定义
在交易中新增字段：

+ `auth_bundles: list[AuthBundle]`

每个 `AuthBundle` 包含：

+ `public_key`
+ `input_indices`
+ `signature`

其中：

+ `public_key`：该组输入共享的公钥 
+ `input_indices`：该 bundle 授权的输入编号列表 
+ `signature`：对该组输入和整笔交易生成的一份 ML-DSA 签名 

## 7.3 合法性条件
一个 bundle 必须满足：

1. `input_indices` 非空 
2.  这些输入引用的 UTXO 全部存在 
3.  这些 UTXO 的 `pubkey_hash` 必须完全相同 
4.  且该共同 `pubkey_hash == SHA256(public_key)`

否则该 bundle 非法。

## 7.4 验签流程
验证一笔交易时：

1.  按输入找到所有引用的 UTXO 
2.  根据 `auth_bundles` 检查每个输入是否被且仅被一个 bundle 覆盖 
3.  对每个 bundle： 
    -  验证公钥哈希是否与对应 UTXO 匹配 
    -  构造 bundle 消息 `msg`
    -  调用 ML-DSA `verify(public_key, msg, signature)`
4.  若所有 bundle 均验证通过，则该交易在授权层合法 

## 7.5 优点
### 7.5.1 缓解体积膨胀
这是最直接的收益。  
若一笔交易中有 `n` 个来自同一地址的输入：

+  原始逐输入模式：需要 `n` 份公钥 + `n` 份签名 
+  SOIBS：只需要 `1` 份公钥 + `1` 份签名 

对于 ML-DSA-44，这一差距非常明显。

### 7.5.2 降低验签次数
一个 bundle 只需一次 ML-DSA 验签。  
在多输入来自同一拥有者的常见支付场景中，节点验证开销显著下降。

### 7.5.3 不破坏 UTXO 本质
SOIBS 并不改变：

+  输入引用旧输出 
+  输出形成新 UTXO 
+  手续费计算 
+  coinbase 
+  PoW 
+  最长链 

它只改变“见证如何组织”，因此仍然是 Bitcoin-like 机制，而不是换成账户模型或其他完全不同的系统。

## 7.6 原创性定位
本文不宣称 SOIBS 是密码学意义上的首创。  
事实上，Bitcoin 生态中长期存在关于跨输入聚合、半聚合等思路的研究和提案。

但本文的 SOIBS 具有明确的系统原创性：

+  它不是 Schnorr 多方聚合 
+  它不是修改共识层 
+  它不是改变 UTXO 语义 
+  它是**专门面向 ML-DSA 引入后的 UTXO 见证膨胀问题而设计的、教学型交易级输入打包授权机制**

对课程项目来说，这样的原创点已经足够自然、明确且合理。

---

## 8. 区块、挖矿与共识
## 8.1 区块结构
每个区块包含：

+ `header`
+ `transactions`

区块头字段：

+ `version`
+ `prev_block_hash`
+ `merkle_root`
+ `timestamp`
+ `target`
+ `nonce`

其中 `merkle_root` 由区块内全部交易的 `txid` 构成。

## 8.2 挖矿的本质
在本系统中，“挖矿”与比特币保持一致：

**矿工挖的不是密钥、不是签名，而是一个满足难度目标的合法新区块。**

矿工流程为：

1.  从 mempool 收集交易 
2.  验证每笔交易 
3.  统计总手续费 
4.  构造 coinbase 交易 
5.  计算 Merkle Root 
6.  反复改变 `nonce`

寻找满足：

7. block_hash<targetblock\_hash < targetblock_hash<target

找到后即可获得：

+  记账权 
+  区块奖励 
+  区块中交易的手续费 

因此，签名层替换成 ML-DSA 不改变挖矿本质。  
签名层解决“谁有权花钱”，PoW 层解决“谁有权写入下一页账本”。

## 8.3 Coinbase 与奖励
每个合法区块第一笔交易必须是 coinbase。  
coinbase 没有正常输入，其输出总额不得超过：

base_reward+total_feesbase\_reward + total\_feesbase_reward+total_fees

教学实现中可采用固定区块奖励，如 50；也可模拟减半。

## 8.4 链选择规则
系统采用最长链或累计工作量优先规则。  
在教学实现中，若精确累计工作量实现较繁琐，可先采用“最长合法链”近似。

---

## 9. 安全实验设计
本系统可用于进行以下实验。

## 9.1 交易合法性实验
验证：

+  合法交易可通过 
+  篡改输出金额后签名失效 
+  更换 `public_key` 后哈希不匹配 
+  伪造签名无法通过 ML-DSA 验证 

## 9.2 SOIBS 效率实验
对比两种交易格式：

+  基线：逐输入见证 
+  改进：SOIBS 

对比指标：

+  单笔交易大小 
+  单区块可容纳交易数 
+  节点总验签次数 
+  平均打包效率 

## 9.3 51% 攻击实验
设置攻击者节点具有更高算力：

1.  向商家广播一笔付款交易 
2.  同时私下构造冲突交易 
3.  私下挖私链 
4.  若私链超过公链则发布 
5.  观察商家收款是否回滚 

该实验可展示：

+  PoW 共识安全边界 
+  签名层与共识层是正交模块 
+  后量子签名不会自动消除 51% 攻击 

---

## 10. 工程实现建议
## 10.1 技术路线
建议采用 Python 实现主逻辑：

+  数据结构清晰 
+  适合快速实验与可视化 
+  易接入 `liboqs-python`

签名层通过 `SignatureScheme` 抽象，默认实现为 `MLDSASignature`。

## 10.2 模块划分
建议目录如下：

+ `crypto/`
    - `signature.py`
    - `mldsa.py`
    - `hashing.py`
+ `core/`
    - `tx.py`
    - `block.py`
    - `merkle.py`
    - `utxo.py`
    - `validation.py`
    - `blockchain.py`
+ `node/`
    - `mempool.py`
    - `miner.py`
    - `node.py`
    - `attacker.py`
+ `simulation/`
    - `network.py`
    - `scenarios.py`

## 10.3 开发顺序
1.  哈希、序列化、txid、merkle root 
2.  ML-DSA 接口封装 
3.  UTXO 与普通交易验证 
4.  SOIBS 见证结构 
5.  区块与区块验证 
6.  PoW 挖矿 
7.  多节点模拟 
8.  51% 攻击实验 
9.  性能对比实验 

---

## 11. 系统局限性
本文必须明确承认以下局限性：

### 11.1 不是工业级比特币实现
系统不实现：

+  完整 Bitcoin Script VM 
+  SegWit 
+  Taproot 
+  P2P 网络协议 
+  网络同步与磁盘优化 

因此它是教学型系统，不是生产级客户端。

### 11.2 ML-DSA 只是替换签名层
后量子签名只能替代“交易授权”这一部分。  
它不能解决：

+  51% 攻击 
+  共识自私挖矿 
+  经济模型投机性 
+  网络分区问题 

### 11.3 SOIBS 不是新密码算法
SOIBS 是系统级见证组织优化，不是新的后量子签名算法。  
它的创新点在于**适配 ML-DSA 进入 UTXO 链时的工程组织方式**，而不是试图自行发明底层密码学。

---

## 12. 结论
本文提出了一个尽量保留比特币核心机制的教学型后量子区块链系统 PQ-BitEdu。系统保留 UTXO、PoW、coinbase、手续费、Merkle Root 和最长链等关键机制，仅在交易认证层将椭圆曲线签名替换为 NIST 标准后量子签名 **ML-DSA**。这一替换使系统具备了明确的后量子特征。

同时，针对 ML-DSA 公钥和签名体积远大于传统比特币签名、在 UTXO 逐输入见证模式下开销被显著放大的问题，本文提出 **SOIBS（同拥有者输入打包签名）**。SOIBS 在不改变 UTXO 机制本质的前提下，将同一拥有者控制的多个输入合并授权，以减少链上见证体积与节点验签次数。该改动具有明确的工程意义，也使整个项目不再只是简单替换签名库，而是形成了一个完整、合理且具有个人设计痕迹的系统方案。

因此，PQ-BitEdu 既可以作为后量子区块链方向的课程大作业原型，也适合作为后续 PPT 展示、实验对比和安全分析的平台。

