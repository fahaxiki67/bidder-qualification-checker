# 浏览器离线审查

这是投标审查器的纯浏览器界面，对应仓库主线的离线审查规则（F/E/S/P）。

- 文件在当前浏览器内存里解析，不上传
- 支持 txt / md / csv / json / xlsx / **xls** / pdf / **docx**
- 扫描件 PDF 只读文本层，没有 OCR
- 资格核查仍是演示数据；官方源一律「待人工核查」
- 输出仅为人工复核线索，不构成串通投标或投标无效认定

主线 Python CLI（`bqc review-bids`）不变。本目录不替换 `app/web/` 的本地服务端页面。

## 本地运行

```bash
cd web
npm install
npm run dev
```

打开提示的本地地址。点「载入演示样本」可直接看到预警。

```bash
npm test    # 金额解析与 F-01/F-07
npm run build
```

## 上传方式

推荐「一级文件夹名 = 投标人」，或文件名写成 `投标人__文件名.ext`。
可选粘贴关联线索 CSV/JSON（`bidder_a,bidder_b,relation`）。
