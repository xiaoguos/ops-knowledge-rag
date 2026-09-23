import {
  $,
  api,
  post,
  esc,
  date,
  badge,
  empty,
  stat,
  table,
  head,
  start,
  bindForm,
  on,
  currentUser,
  icon,
} from "./common.js";
let conversationId = null;
let workspaceUserId = null;

document.addEventListener("click", async (event) => {
  const button = event.target.closest(".source-page");
  if (!button) return;
  button.disabled = true;
  const identity = currentUser()?.id;
  try {
    const blob = await api(button.dataset.path, { responseType: "blob" });
    if (!button.isConnected || currentUser()?.id !== identity) return;
    const img = new Image();
    const url = URL.createObjectURL(blob);
    img.alt = "引用对应的PDF原始页面";
    img.style.cssText = "max-width:100%;height:auto";
    img.onload = img.onerror = () => URL.revokeObjectURL(url);
    img.src = url;
    button.replaceWith(img);
  } catch (error) {
    button.textContent = error.message;
    button.disabled = false;
  }
});
document.addEventListener("click", (event) => {
  const citation = event.target.closest(".citation-link");
  if (!citation) return;
  const evidence = Array.from(
    document.querySelectorAll("[data-evidence-id]"),
  ).find((element) => element.dataset.evidenceId === citation.dataset.citation);
  if (!evidence) return;
  evidence.open = true;
  evidence.scrollIntoView({ behavior: "smooth", block: "center" });
  evidence.querySelector("summary").focus();
});
async function documents() {
  const rows = await api("/documents"),
    admin = currentUser().role === "admin";
  $("#view").innerHTML =
    head(
      "KNOWLEDGE OPERATIONS",
      "知识资产",
      "接入企业文档，管理索引版本与部门访问范围。",
    ) +
    '<div class="stats">' +
    stat("文档总数", rows.length, "当前权限可见的知识资产") +
    stat("可检索", rows.filter((r) => r.searchable).length, "已有生效索引") +
    stat(
      "待处理",
      rows.filter((r) => ["queued", "running", "pending"].includes(r.status))
        .length,
      "由后台 Worker 持续处理",
    ) +
    stat(
      "处理失败",
      rows.filter((r) => r.status === "failed").length,
      "支持保留旧版本后重试",
    ) +
    '</div><div class="card"><div class="toolbar"><h2>文档管理</h2><div class="actions" style="margin:0"><input id="filter" class="search" placeholder="搜索文档名称或部门" aria-label="搜索文档"><button id="refresh" class="btn small">' +
    icon("arrow") +
    ' 刷新状态</button></div></div><div id="document-table"></div></div>' +
    (admin
      ? '<div class="card"><h2>导入文档 / 更新版本</h2><p class="muted">支持 PDF、DOCX、Markdown、TXT，单文件不超过 16MB。新版本索引完成后才替换当前可检索版本。</p><form id="upload"><div class="grid2"><div><label>文件</label><input name="file" type="file" accept=".pdf,.docx,.md,.txt" required></div><div><label>更新对象</label><select name="document_id"><option value="">作为新文档接入</option>' +
        rows
          .map(
            (r) => '<option value="' + r.id + '">' + esc(r.title) + "</option>",
          )
          .join("") +
        '</select></div><div><label>所属部门</label><input name="department" required maxlength="80" placeholder="如：运维"></div><div><label>业务版本</label><input name="version" required maxlength="80" placeholder="如：2026.09"></div></div><div class="actions"><button class="btn primary" type="submit">提交索引任务</button><span class="muted">上传内容保存在企业后端，不发送到 GitHub Pages。</span></div></form></div>'
      : "");
  function draw(filter = "") {
    const filtered = rows.filter((r) =>
      (r.title + r.department).toLowerCase().includes(filter.toLowerCase()),
    );
    $("#document-table").innerHTML = table(
      [
        "文档名称",
        "部门 / 版本",
        "索引状态",
        "生效状态",
        "接入时间",
        ...(admin ? ["操作"] : []),
      ],
      filtered.map((r) => [
        icon("file") + " " + esc(r.title),
        esc(r.department) + " / " + esc(r.version),
        badge(r.status),
        r.searchable
          ? '<span class="badge good">已有可用索引</span>'
          : '<span class="muted">等待索引</span>',
        date(r.updated_at),
        ...(admin
          ? [
              '<div class="actions" style="margin:0">' +
                (r.review_required ? '<button class="btn small review-document" data-id="' + r.id + '">解析复核</button>' : "") +
                (r.status === "failed"
                  ? '<button class="btn small retry" data-id="' +
                    r.id +
                    '">重试</button>'
                  : "") +
                '<button class="btn small danger remove" data-id="' +
                r.id +
                '">删除</button></div>',
            ]
          : []),
      ]),
    );
    on(".review-document", async (el) => reviewDocument(el.dataset.id));
    on(".retry", async (el) => {
      await post("/documents/" + el.dataset.id + "/retry", {});
      await documents();
    });
    on(".remove", async (el) => {
      if (
        !confirm(
          "确认删除？此文档将立即从检索范围移除，历史版本按服务端保留策略处理。",
        )
      )
        return;
      await api("/documents/" + el.dataset.id, { method: "DELETE" });
      await documents();
    });
  }
  draw();
  $("#filter").addEventListener("input", (e) => draw(e.target.value));
  on("#refresh", documents);
  bindForm("#upload", async (data) => {
    if (!data.get("document_id")) data.delete("document_id");
    await api("/documents", { method: "POST", body: data });
    await documents();
  });
}
async function reviewDocument(id) {
  const identity = currentUser()?.id;
  const data = await api("/documents/" + id + "/processing");
  if (currentUser()?.id !== identity) return;
  const pages = data.report.pages || [];
  if (data.state !== "awaiting_review" || !pages.length) {
    await documents();
    return;
  }
  let index = 0;
  const edits = pages.map((p) => ({ page: p.page, text: p.text, blank: false }));
  $("#view").innerHTML = head("DOCUMENT REVIEW", "解析质量复核", "逐页对照原图修订；提交后才构建新索引，旧有效版本不受影响。") +
    '<div class="card"><div class="actions"><button class="btn" id="review-back">返回文档</button><button class="btn" id="review-prev">上一页</button><span id="review-position"></span><button class="btn" id="review-next">下一页</button></div><div id="review-warning" class="notice warning"></div><div class="grid2"><div><h2>原始页面</h2><div id="source-preview"></div></div><div><label for="review-text">确认后的正文 / Markdown表格</label><textarea id="review-text" maxlength="32000" style="min-height:420px"></textarea><label><input id="review-blank" type="checkbox">确认此页没有需入库的内容</label></div></div><div class="actions"><button id="review-submit" class="btn primary">确认全部页面并提交索引</button><span class="muted">机器识别分数不等于事实正确率；无法核验的资料请勿提交。</span></div></div>';
  const seen = new Set();
  const preview = $("#source-preview");
  function save() {
    edits[index].text = $("#review-text").value;
    edits[index].blank = $("#review-blank").checked;
  }
  async function show() {
    const number = index;
    seen.add(number);
    $("#review-position").textContent = `第 ${number + 1} / ${pages.length} 页`;
    $("#review-warning").textContent = `${pages[number].method}：${pages[number].warnings.join("；") || "请核对文字和顺序"}`;
    $("#review-text").value = edits[number].text;
    $("#review-blank").checked = edits[number].blank;
    $("#source-preview").innerHTML = empty("正在加载授权页面");
    const blob = await api(`/documents/${id}/versions/${data.version_id}/pages/${pages[number].page}`, { responseType: "blob" });
    if (!preview.isConnected || currentUser()?.id !== identity || index !== number) return;
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.alt = `原始PDF第${pages[number].page}页`;
    img.style.cssText = "max-width:100%;height:auto";
    img.onload = img.onerror = () => URL.revokeObjectURL(url);
    img.src = url;
    preview.replaceChildren(img);
  }
  on("#review-back", documents);
  on("#review-prev", async () => { save(); index = Math.max(0, index - 1); await show(); });
  on("#review-next", async () => { save(); index = Math.min(pages.length - 1, index + 1); await show(); });
  on("#review-submit", async () => {
    save();
    if (seen.size !== pages.length) throw new Error("请查看并核对全部页面后提交");
    await post(`/documents/${id}/review`, { version_id: data.version_id, digest: data.digest, pages: edits });
    await documents();
  });
  await show();
}

function renderAnswer(answer) {
  return (
    '<div class="notice ' +
    (answer.refused ? "warning" : "") +
    '">' +
    (answer.refused
      ? "本次证据不足，系统已拒绝生成确定性结论。"
      : "回答基于下方检索证据生成，请点击引用核对原文。") +
    '</div><div class="bodytext">' +
    (answer.refused
      ? esc(answer.answer)
      : answer.claims
          .map(
            (claim, index) =>
              esc(claim.text) +
              ' <button type="button" class="citation-link" data-citation="' +
              esc(claim.citation_id) +
              '" aria-label="查看第' +
              (index + 1) +
              '条结论的原文依据">[' +
              (index + 1) +
              "]</button>",
          )
          .join("\n\n")) +
    '</div><div class="actions"><span class="badge">' +
    esc(answer.latency_ms) +
    ' ms</span><span class="muted">会话已保存在服务端</span></div>'
  );
}
function renderEvidence(evidence) {
  return evidence.length
    ? evidence
        .map(
          (e, i) =>
            '<details class="evidence" data-evidence-id="' +
            esc(e.id) +
            '" ' +
            (i === 0 ? "open" : "") +
            "><summary><strong>" +
            esc(e.title) +
            '</strong> <span class="badge">' +
            esc(e.department) +
            '</span></summary><p class="muted">版本 ' +
            esc(e.version) +
            " · " +
            esc(e.heading) +
            (e.page ? " · 第 " + e.page + " 页" : "") +
            "</p>" +
            (e.page && e.version_id ? '<button class="btn small source-page" data-path="/documents/' + esc(e.document_id) + '/versions/' + esc(e.version_id) + '/pages/' + e.page + '">查看原始页</button>' : "") +
            "<pre>" +
            esc(e.text) +
            '</pre><p class="muted">引用 ID：' +
            esc(e.id) +
            "</p></details>",
        )
        .join("")
    : empty("本次没有检索到有权访问的证据");
}
async function ask() {
  $("#view").innerHTML =
    head(
      "EVIDENCE-FIRST ASSISTANT",
      "知识问答",
      "基于企业资料回答，检索范围由登录账号的部门权限决定。",
      '<button id="new-chat" class="btn">新建会话</button>',
    ) +
    '<div class="columns"><div><div class="card"><h2>向知识库提问</h2><form id="ask"><textarea name="query" required minlength="2" maxlength="2000" placeholder="描述你遇到的问题，或输入错误码、接口名称…"></textarea><div class="grid2"><div><label>指定部门（可选）</label><input name="department" placeholder="留空检索全部授权部门"></div><div><label>指定版本（可选）</label><input name="version" placeholder="留空检索生效版本"></div></div><div class="actions"><button class="btn primary" type="submit">检索并回答 ' +
    icon("arrow") +
    '</button><span id="conversation-status" class="muted">' +
    (conversationId ? "继续当前会话" : "新的知识问答") +
    '</span></div></form></div><div class="card"><h2>回答</h2><div id="answer">' +
    empty("提交问题后，回答与引用证据将在这里展示") +
    '</div></div></div><div class="card"><div class="cardhead"><h2>参考资料</h2><span class="badge">权限过滤</span></div><p class="muted">资料中的指令不被作为系统命令执行。原文引用可追溯，不代表模型结论一定正确。</p><div id="evidence">' +
    empty("等待本次检索结果") +
    "</div></div></div>";
  on("#new-chat", async () => {
    conversationId = null;
    await ask();
  });
  bindForm("#ask", async (data) => {
    const payload = { query: data.get("query") };
    if (conversationId) payload.conversation_id = conversationId;
    for (const k of ["department", "version"])
      if (data.get(k).trim()) payload[k] = data.get(k).trim();
    $("#answer").innerHTML =
      '<div class="loading"><div class="spinner"></div>正在检索授权资料并生成回答</div>';
    let result;
    try {
      result = await post("/ask", payload);
    } catch (e) {
      $("#answer").innerHTML = empty(
        "本次未生成回答，请解决上方错误后重新提交。",
      );
      $("#evidence").innerHTML = empty("未展示未经验证的结果");
      throw e;
    }
    conversationId = result.conversation_id;
    $("#answer").innerHTML = renderAnswer(result);
    $("#evidence").innerHTML = renderEvidence(result.evidence);
    $("#conversation-status").textContent = "继续当前会话";
  });
}
async function history() {
  const rows = await api("/conversations");
  $("#view").innerHTML =
    head("CONVERSATION HISTORY", "问答记录", "仅显示当前账号创建的会话。") +
    '<div class="columns"><div class="card"><h2>我的会话</h2>' +
    (rows.length
      ? rows
          .map(
            (r) =>
              '<button class="listbutton conversation" data-id="' +
              r.id +
              '">' +
              esc(r.title) +
              "<small>" +
              date(r.created_at) +
              "</small></button>",
          )
          .join("")
      : empty("还没有问答记录")) +
    '</div><div class="card"><h2>会话详情</h2><div id="messages">' +
    empty("选择一个会话查看问答和引用") +
    "</div></div></div>";
  on(".conversation", async (el) => {
    const messages = await api("/conversations/" + el.dataset.id);
    $("#messages").innerHTML = messages
      .map(
        (m) =>
          "<h3>" +
          esc(m.question) +
          "</h3>" +
          renderAnswer(m.response) +
          renderEvidence(m.response.evidence),
      )
      .join("");
  });
}
start({
  id: "knowledge",
  brand: "企业内部知识库智能问答平台",
  title: "企业内部知识库智能问答平台",
  seal: "知",
  workspaceLabel: "知识服务 · 资料与证据",
  loginLabel: "企业资料，统一查阅",
  loginHeading: "进入知识工作区",
  loginFootnote: "检索范围由部门授权决定 · 回答支持原文核对",
  footer: "资料有版本 · 回答有依据",
  steps: ["接入与更新企业资料", "查找授权范围内的证据", "核对回答与文档原文"],
  symbol: "file",
  tagline: "查资料，<br>也查清依据。",
  description:
    "统一管理知识资产，以权限为边界，以证据为依据，让每一次检索与问答都有迹可循。",
  defaultPage: "ask",
  navigation: [
    { id: "ask", label: "知识问答", icon: "chat" },
    { id: "documents", label: "知识资产", icon: "file" },
    { id: "history", label: "问答记录", icon: "task" },
    { id: "users", label: "成员与权限", icon: "users", admin: true },
    { id: "audit", label: "审计日志", icon: "shield", admin: true },
  ],
  render: (page) => {
    if (workspaceUserId !== currentUser().id) {
      workspaceUserId = currentUser().id;
      conversationId = null;
    }
    return { ask, documents, history }[page]();
  },
});
