# 商家退保 AI 审核系统

基于通义千问多模态 AI 的商家退保审核系统，支持营业执照注销证明 + 退款申请函的自动化审核。

## 架构

```
用户上传材料 → Agent 1 (AI材料审核员) → Agent 2 (置信度评估) → Agent 3 (工商信息核对) → Agent 4 (消息触达)
```

- **前端**: 单文件 `index.html` (iPhone 15 Pro Max phone demo wrapper)
- **后端**: `server.py` (port 8766, 静态文件 + AI API proxy)
- **AI Provider**: 通义千问 (dashscope.aliyuncs.com), 视觉模型 `qwen-vl-max`, 文本模型 `qwen-turbo/plus/max`

## 快速启动

```bash
cd merchant-withdrawal-review
python3 server.py
```

然后访问 `http://localhost:8766`

## 功能模块

### Tab 1: 场景决策树
根据商家属性（绑卡状态、商家类型、经营资质、对公卡状态）自动判断是否需要人审。

### Tab 2: 商家提交 & AI 预审
- 填写商家信息（名称、信用代码、收款账户等）
- 上传营业执照注销证明 + 退款申请函
- 4-Agent AI 流水线自动审核

### Tab 3: 人工审核
查看 AI 审核意见 + 企查查工商数据比对，人工做出通过/驳回决策。

### Tab 4: 流程失败通知
飞书卡片样式通知，自动生成审核/驳回通知模板。

### Tab 5: 当日审批汇总
每日审批记录汇总，支持 AI 自动生成汇总建议。

## 技术栈

- 前端: 原生 HTML/CSS/JS (无框架)
- 后端: Python 3 + http.server
- AI: 通义千问 API (DashScope)
- 工商查询: 企查查 MCP
