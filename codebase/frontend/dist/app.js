const state = {
  cases: [],
  selectedCase: null,
  evaluation: null,
  loading: false,
};

const elements = {
  navItems: document.querySelectorAll(".nav-item"),
  views: document.querySelectorAll(".view"),
  providerStatus: document.querySelector("#providerStatus"),
  caseList: document.querySelector("#caseList"),
  caseCount: document.querySelector("#caseCount"),
  customCaseButton: document.querySelector("#customCaseButton"),
  messageInput: document.querySelector("#messageInput"),
  characterCount: document.querySelector("#characterCount"),
  ageChip: document.querySelector("#ageChip"),
  classifyButton: document.querySelector("#classifyButton"),
  resultIdle: document.querySelector("#resultIdle"),
  resultLoading: document.querySelector("#resultLoading"),
  resultContent: document.querySelector("#resultContent"),
  resultError: document.querySelector("#resultError"),
  retryButton: document.querySelector("#retryButton"),
  errorMessage: document.querySelector("#errorMessage"),
  traceId: document.querySelector("#traceId"),
  confidenceRing: document.querySelector("#confidenceRing"),
  confidenceValue: document.querySelector("#confidenceValue"),
  decisionLabel: document.querySelector("#decisionLabel"),
  decisionDescription: document.querySelector("#decisionDescription"),
  intentValue: document.querySelector("#intentValue"),
  priorityValue: document.querySelector("#priorityValue"),
  latencyValue: document.querySelector("#latencyValue"),
  modelValue: document.querySelector("#modelValue"),
  riskHints: document.querySelector("#riskHints"),
  toast: document.querySelector("#toast"),
};

const decisionCopy = {
  URGENT: "Cần TA kiểm tra sớm vì có dấu hiệu tắc nghẽn nhạy cảm thời gian.",
  NORMAL: "Câu hỏi cần hỗ trợ, có thể đưa vào digest bình thường.",
  IGNORE: "Không phải câu hỏi cần TA can thiệp.",
  NEEDS_REVIEW: "AI chưa đủ chắc chắn. Chuyển TA kiểm tra thủ công.",
};

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({ error: "INVALID_RESPONSE" }));
  if (!response.ok) {
    throw new Error(payload.error || `HTTP_${response.status}`);
  }
  return payload;
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => elements.toast.classList.remove("visible"), 2600);
}

function switchView(viewName) {
  elements.navItems.forEach((item) => {
    item.classList.toggle("active", item.dataset.view === viewName);
  });
  elements.views.forEach((view) => {
    view.classList.toggle("active", view.id === `${viewName}View`);
  });
}

function updateCharacterCount() {
  const count = elements.messageInput.value.length;
  elements.characterCount.textContent = `${count.toLocaleString("vi-VN")} / 2.000`;
}

function renderCases() {
  elements.caseCount.textContent = state.cases.length;
  elements.caseList.innerHTML = state.cases
    .map(
      (item) => `
        <button
          class="case-card ${state.selectedCase?.id === item.id ? "selected" : ""}"
          type="button"
          data-case-id="${escapeHtml(item.id)}"
          data-tone="${escapeHtml(item.tone)}"
        >
          <span class="case-tone"></span>
          <span>
            <strong>${escapeHtml(item.title)}</strong>
            <small>Kỳ vọng · ${escapeHtml(item.expected)}</small>
          </span>
        </button>
      `,
    )
    .join("");
  elements.caseList.querySelectorAll(".case-card").forEach((button) => {
    button.addEventListener("click", () => selectCase(button.dataset.caseId));
  });
}

function selectCase(caseId) {
  const selected = state.cases.find((item) => item.id === caseId);
  if (!selected) return;
  state.selectedCase = selected;
  elements.messageInput.value = selected.message;
  elements.ageChip.textContent = `${selected.age_minutes} phút`;
  renderCases();
  updateCharacterCount();
  showResultState("idle");
}

function showResultState(name) {
  elements.resultIdle.classList.toggle("hidden", name !== "idle");
  elements.resultLoading.classList.toggle("hidden", name !== "loading");
  elements.resultContent.classList.toggle("hidden", name !== "content");
  elements.resultError.classList.toggle("hidden", name !== "error");
}

function renderResult(result) {
  const confidencePercent = Math.round(result.confidence * 100);
  elements.resultContent.dataset.result = result.result;
  elements.resultContent.style.setProperty("--confidence-angle", `${confidencePercent * 3.6}deg`);
  elements.traceId.textContent = result.trace_id;
  elements.confidenceValue.textContent = `${confidencePercent}%`;
  elements.decisionLabel.textContent = result.result;
  elements.decisionDescription.textContent = decisionCopy[result.result] || "Đã phân loại.";
  elements.intentValue.textContent = result.intent;
  elements.priorityValue.textContent = result.priority || "—";
  elements.latencyValue.textContent = `${result.latency_ms.toLocaleString("vi-VN")} ms`;
  elements.modelValue.textContent = result.model;
  elements.riskHints.innerHTML = result.risk_hints.length
    ? result.risk_hints.map((hint) => `<span>${escapeHtml(hint)}</span>`).join("")
    : '<span class="no-risk">NO_RISK_HINT</span>';
  showResultState("content");
}

async function classifyCurrentMessage() {
  if (state.loading) return;
  const message = elements.messageInput.value.trim();
  if (!message) {
    showToast("Nhập nội dung message trước khi phân loại.");
    elements.messageInput.focus();
    return;
  }
  state.loading = true;
  elements.classifyButton.disabled = true;
  elements.classifyButton.querySelector(".button-text").textContent = "Đang gọi 9Router…";
  showResultState("loading");
  try {
    const result = await fetchJson("/api/classify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        age_minutes: state.selectedCase?.age_minutes ?? 60,
        has_attachment: false,
      }),
    });
    renderResult(result);
    showToast(`AI thật đã trả kết quả ${result.result}.`);
  } catch (error) {
    elements.errorMessage.textContent = `Mã lỗi: ${error.message}. Candidate được giữ an toàn để thử lại.`;
    showResultState("error");
  } finally {
    state.loading = false;
    elements.classifyButton.disabled = false;
    elements.classifyButton.querySelector(".button-text").textContent = "Phân loại bằng AI thật";
  }
}

function ratioText(metric) {
  return `${metric.found}/${metric.total}`;
}

function renderEvaluation(summary) {
  state.evaluation = summary;
  const metrics = summary.metrics;
  const total = metrics.total;
  const accuracyPercent = Math.round(metrics.accuracy * 100);

  document.querySelector("#proofCases").textContent = total;
  document.querySelector("#proofAccuracy").textContent = `${accuracyPercent}%`;
  document.querySelector("#proofUrgent").textContent = ratioText(metrics.urgent_recall);
  document.querySelector("#proofErrors").textContent = summary.provider_errors;
  document.querySelector("#evalAccuracy").textContent = `${accuracyPercent}%`;
  document.querySelector("#evalCorrect").textContent = `${Math.round(metrics.accuracy * total)}/${total}`;
  document.querySelector("#evalAccuracyBar").style.width = `${accuracyPercent}%`;
  document.querySelector("#evalUrgent").textContent = ratioText(metrics.urgent_recall);
  document.querySelector("#evalActionable").textContent = ratioText(metrics.actionable_recall);
  document.querySelector("#evalPrecision").textContent =
    `${metrics.notification_intent_precision.correct}/${metrics.notification_intent_precision.total}`;
  document.querySelector("#reportVersion").textContent = summary.prompt_version;

  const matrix = metrics.confusion_matrix;
  const columnOrder = ["IGNORE", "NORMAL", "URGENT", "REVIEW"];
  document.querySelector("#matrixBody").innerHTML = columnOrder
    .map((rowName) => {
      const cells = columnOrder
        .map((columnName) => {
          const value = matrix[rowName]?.[columnName] ?? 0;
          const cellClass = rowName === columnName && value > 0 ? "hit" : "";
          return `<td class="${cellClass}">${value}</td>`;
        })
        .join("");
      return `<tr><th>${rowName}</th>${cells}</tr>`;
    })
    .join("");
}

async function initialize() {
  elements.navItems.forEach((item) => {
    item.addEventListener("click", () => switchView(item.dataset.view));
  });
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.viewTarget));
  });
  elements.messageInput.addEventListener("input", () => {
    state.selectedCase = null;
    renderCases();
    updateCharacterCount();
  });
  elements.customCaseButton.addEventListener("click", () => {
    state.selectedCase = null;
    elements.messageInput.value = "";
    elements.ageChip.textContent = "60 phút";
    renderCases();
    updateCharacterCount();
    showResultState("idle");
    elements.messageInput.focus();
  });
  elements.classifyButton.addEventListener("click", classifyCurrentMessage);
  elements.retryButton.addEventListener("click", classifyCurrentMessage);

  const [healthResult, casesResult, evaluationResult] = await Promise.allSettled([
    fetchJson("/api/health"),
    fetchJson("/api/demo-cases"),
    fetchJson("/api/evaluation"),
  ]);

  if (healthResult.status === "fulfilled") {
    const health = healthResult.value;
    elements.providerStatus.classList.add("ready");
    elements.providerStatus.querySelector("span:last-child").textContent =
      `${health.provider} · ${health.model}`;
  } else {
    elements.providerStatus.classList.add("error");
    elements.providerStatus.querySelector("span:last-child").textContent = "AI chưa cấu hình";
  }

  if (casesResult.status === "fulfilled") {
    state.cases = casesResult.value.cases;
    state.selectedCase = state.cases[0] || null;
    renderCases();
    if (state.selectedCase) selectCase(state.selectedCase.id);
  }

  if (evaluationResult.status === "fulfilled") {
    renderEvaluation(evaluationResult.value);
  }
}

initialize().catch(() => {
  elements.providerStatus.classList.add("error");
  elements.providerStatus.querySelector("span:last-child").textContent = "Không tải được dashboard";
});
