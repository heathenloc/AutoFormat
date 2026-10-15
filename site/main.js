(() => {
  "use strict";

  document.documentElement.classList.add("js");

  const messages = {
    "zh-CN": {
      title: "AutoFormat · 论文格式，轻松掌握",
      description: "AutoFormat — 让论文格式调整更省时、更清楚、更可控。",
      product: "产品简介",
      workflow: "技术设计与产品 workflow",
      ai: "AI选型&产品调优",
      business: "商业分析",
      skip: "跳到主要内容",
      home: "AutoFormat，返回首页",
      "page.workflow.title": "AutoFormat · 技术设计与产品 Workflow",
      "page.workflow.description": "AutoFormat 的要求解析、格式编辑、预览与微调，以及编辑前确认与版本管理设计。",
      "page.ai.title": "AutoFormat · AI选型与产品调优",
      "page.ai.description": "AutoFormat 的模型策略与质量、可靠性、速度和 Token 用量优化。",
      "page.business.title": "AutoFormat · 商业分析",
      "page.business.description": "AutoFormat 的商业思考：免费预览、付费交付、校园机构合作，以及基于真实成本与订单的验证路径。",
      navigation: "主要导航",
      language: "切换语言",
      openMenu: "打开导航菜单",
      closeMenu: "关闭导航菜单",
      "formats.status": "已显示 {count} 个格式类别。",
      "formats.collapsed": "格式详情已收起，选择分类查看。",
      "technical.confirm.ready": "已选择“{choice}”。确认后，此示例才进入下一步。",
      "technical.confirm.confirmed.simsun": "示意：已确认采用宋体，下一步为格式编辑。",
      "technical.confirm.confirmed.simhei": "示意：已确认采用黑体，下一步为格式编辑。",
      "technical.confirm.confirmed.skip": "示意：已明确暂时忽略，此项不执行并保留在报告中；其余已验证规则继续。",
    },
    en: {
      title: "AutoFormat · Thesis formatting, made simple",
      description: "AutoFormat — thesis formatting that saves time and keeps you in control.",
      product: "Product Overview",
      workflow: "Technical Design & Workflow",
      ai: "AI Selection & Product Tuning",
      business: "Business Analysis",
      skip: "Skip to main content",
      home: "AutoFormat, return to home",
      "page.workflow.title": "AutoFormat · Technical Design & Workflow",
      "page.workflow.description": "Explore AutoFormat's requirement parsing, formatting, preview and refinement, confirmation, and version management.",
      "page.ai.title": "AutoFormat · AI Selection & Product Tuning",
      "page.ai.description": "AutoFormat's model strategy and improvements in quality, reliability, speed, and token usage.",
      "page.business.title": "AutoFormat · Business Analysis",
      "page.business.description": "AutoFormat's commercial thinking: free previews, paid delivery, campus partnerships, and validation through real costs and orders.",
      "business.kicker": "Commercial thinking",
      "business.title": "Clear value and cost for every formatting task.",
      "business.description": "AutoFormat plans to build trust with free previews, test its value through paid delivery, and gradually explore campus partnerships. Real orders and per-task costs will guide how quickly it expands.",
      "business.model.title": "Baseline estimates",
      "business.model.status": "A business model to validate",
      "business.metric.fixed.label": "Fixed operating costs",
      "business.metric.fixed.note": "Including technical maintenance labor",
      "business.metric.cost.label": "Average cost per task",
      "business.metric.cost.note": "Including allocated payment fees and after-sales support",
      "business.metric.balance.label": "Break-even task volume",
      "business.metric.balance.note": "Individual paid delivery only",
      "business.approx": "Approx.",
      "business.unit.month": "CNY / month",
      "business.unit.task": "CNY / task",
      "business.unit.volume": "tasks / month",
      "business.model.assumptions": "Based on a CNY 29.9 price, an 8% payment conversion rate, a 3% refund rate and the cost assumptions. These are planning estimates to validate, not achieved business results.",
      "business.strategy.title": "Commercial approach",
      "business.preview.title": "See the result before paying",
      "business.preview.description": "Show the changes and unresolved items to address quality concerns. Charge per thesis task, with evidence-based, verifiable delivery supporting the purchase.",
      "business.revenue.title": "Individual payments first, institutional partnerships next",
      "business.revenue.description": "Validate paid delivery for students first, then explore processing credits purchased by faculties and libraries. Advertising supplements revenue only if its net income exceeds the lost contribution from lower payment conversion.",
      "business.cost.title": "Calculate costs per task",
      "business.cost.description": "Separate monthly fixed costs from per-task processing costs. Reuse parsing results, limit unproductive retries, and account for the real costs of free users and after-sales support.",
      "business.season.title": "Plan around graduation season; validate over the full year",
      "business.season.description": "Account for seasonal, infrequent demand. Use actual payments, refunds, support hours and annual profit to decide whether the business should expand.",
      "business.formula.title": "Monthly profit model",
      "business.formula.profit": "Monthly profit",
      "business.formula.tasks": "individual upload tasks",
      "business.formula.institution": "net institutional contribution",
      "business.formula.ads": "net advertising income",
      "business.formula.fixed": "CNY 11,000",
      "business.formula.note": "Institutional and advertising amounts must each deduct their additional costs. Recalculate the model whenever its parameters change.",
      "business.validation.title": "Validation path",
      "business.validation.delivery": "Real deliveries at a small scale",
      "business.validation.payment": "Validate payments and profit per task",
      "business.validation.institution": "Paid institutional pilots",
      "business.validation.ads": "Compare net returns with and without ads",
      navigation: "Main navigation",
      language: "Switch language",
      openMenu: "Open navigation menu",
      closeMenu: "Close navigation menu",
      "hero.title": "“Format your thesis in one click with an AI assistant”",
      "hero.description": "After writing your thesis, fonts, headings, spacing, margins, contents and tables can still need repeated adjustments. AutoFormat frees you from tedious formatting work.",
      "hero.explore": "Explore formatting",
      "hero.flow": "View the process",
      "hero.impact.start": "With AutoFormat, formatting and review time can go from",
      "hero.impact.hours": " hrs",
      "hero.impact.to": "to",
      "hero.impact.minutes": " min",
      "hero.impact.resolution": ", resolving at least",
      "hero.impact.issues": "of formatting issues on the first pass.",
      "flow.kicker": "PROCESS",
      "flow.title": "Upload your draft and requirements to get started",
      "flow.description": "Clarify what matters, then format automatically. Refine individual details after the first pass.",
      "flow.upload.title": "Upload your files",
      "flow.upload.description": "Upload your thesis draft and formatting requirements",
      "flow.upload.formats": "(DOCX and PDF formats supported)",
      "flow.format.title": "Clarify, then format",
      "flow.format.description": "Extract the rules, confirm uncertainties and apply reliable changes. With no questions to resolve, processing continues directly.",
      "flow.refine.title": "Preview and refine",
      "flow.refine.description": "Get an editable document, report and preview. Select text and describe a change to refine a specific area.",
      "assurance.versions": "Roll back to any version",
      "assurance.evidence": "Preview the changes",
      "assurance.validation": "Get a stable, usable version",
      "formats.kicker": "FORMATTING CAPABILITIES",
      "formats.title": "From individual fonts to the entire layout.",
      "formats.description": "Bring common formal-document requirements into one workflow.",
      "formats.filterLabel": "Choose a formatting category",
      "formats.detailsLabel": "Formatting capability details",
      "formats.collapse": "Collapse",
      "formats.all": "All formats",
      "formats.text": "Text & paragraphs",
      "formats.layout": "Page & structure",
      "formats.academic": "Figures & academic",
      "formats.status": "{count} format categories shown.",
      "formats.collapsed": "Details collapsed. Choose a category to explore.",
      "formats.disclaimer": "Some features are still in development. Available functionality may change.",
      "format.font.title": "Fonts & characters",
      "format.font.description": "Font families and sizes, bold, italic, color, underline, strikethrough, superscript, subscript, character spacing and scaling; separate settings for Chinese, Latin text and numerals.",
      "format.paragraph.title": "Paragraphs",
      "format.paragraph.description": "Alignment, line and paragraph spacing, first-line, hanging and left/right indents, tab stops, leaders, borders, shading, widow/orphan control and pagination.",
      "format.heading.title": "Headings",
      "format.heading.description": "Fonts, sizes, styles, alignment, indents and spacing for each heading level; hierarchy, multilevel numbering, chapter starts and links to the table of contents.",
      "format.page.title": "Pages & sections",
      "format.page.description": "Paper size, orientation, margins, binding gutters, columns, text direction, mirrored margins, section breaks and chapter-specific settings.",
      "format.footer.title": "Headers, footers & pages",
      "format.footer.description": "Text appearance, position and offsets, page-number format and starting value, different first and odd/even pages, chapter headers and continuous numbering.",
      "format.contents.title": "Contents & references",
      "format.contents.description": "Contents levels and entry styles, conversion of manual contents, lists of figures and tables, cross-references and field updates.",
      "format.table.title": "Tables",
      "format.table.description": "Three-line, grid and borderless tables, cell text, row heights, column widths, cell margins and alignment, repeated header rows, page breaks and complex borders.",
      "format.image.title": "Images & captions",
      "format.image.description": "Image size, position, alignment and text wrapping; caption fonts, sizes, numbering, placement and spacing around figures.",
      "format.list.title": "Lists & numbering",
      "format.list.description": "Bullets, numbering styles, indents, numbering continuity, multilevel lists and list-text appearance.",
      "format.reference.title": "Notes, citations & bibliography",
      "format.reference.description": "Fonts, sizes, indents, spacing, footnote/endnote numbering, separator lines and visual consistency.",
      "format.equation.title": "Equations",
      "format.equation.description": "Fonts, sizes, alignment, numbering and spacing around equations.",
      "technical.title": "Consistent, repeatable results without hallucinations",
      "technical.description": "AutoFormat connects requirement parsing, document editing, preview and refinement in one workflow. AI interprets requirements, deterministic software applies changes, and evidence and versions follow every step.",
      "technical.architecture": "System architecture",
      "technical.parse.title": "Requirement parsing",
      "technical.edit.title": "Document editing",
      "technical.preview.title": "Preview & refinement",
      "technical.gate.link": "View confirmation example →",
      "technical.parse.subtitle": "Stable, efficient and reusable Brief Parsing.",
      "technical.parse.evidence.title": "Grounded in source evidence",
      "technical.parse.evidence.description": "Distinguish explicit requirements, template observations and examples. Link each candidate to real source evidence; missing or unsupported information remains pending clarification.",
      "technical.parse.schema.title": "Schema and semantic validation",
      "technical.parse.schema.description": "Constrain the output with JSON Schema, then verify objects, attributes, values, units, conditions and scope so software can process the rules.",
      "technical.parse.budget.title": "Separate stages, controlled cost",
      "technical.parse.budget.description": "Extraction, coverage auditing and dispute analysis have separate roles. Set timeouts, bounded retries and token budgets, and reuse validated parsing results.",
      "technical.parse.reuse.title": "Versioned interfaces for reuse",
      "technical.parse.reuse.description": "Pin model and prompt versions. Connect to different hosts through parse bundles, domain packs and model adapters, with clear input, output and validation boundaries.",
      "technical.proof.source": "SOURCE EVIDENCE · E-001",
      "technical.proof.quote": "“Use SimSun for body text.”",
      "technical.proof.description": "Candidate values need source support. Template observations retain their own provenance.",
      "technical.proof.schema": "STRUCTURED OUTPUT · SIMPLIFIED EXAMPLE",
      "technical.proof.code": "{\n  \"object\": \"body\",\n  \"attribute\": \"font\",\n  \"value\": \"SimSun\",\n  \"evidence\": \"E-001\"\n}",
      "technical.confirm.title": "Resolve questions before making changes.",
      "technical.confirm.badge": "Interactive example",
      "technical.confirm.question": "Two font requirements conflict. Which should apply to body text?",
      "technical.confirm.evidence1": "Requirement A: use SimSun.",
      "technical.confirm.evidence2": "Requirement B: use SimHei.",
      "technical.confirm.legend": "Choose a font requirement or explicitly skip",
      "technical.confirm.simsun": "Use SimSun",
      "technical.confirm.simhei": "Use SimHei",
      "technical.confirm.skip": "Skip this question for now",
      "technical.confirm.submit": "Confirm selection (demo)",
      "technical.confirm.reset": "Reset example",
      "technical.confirm.pending": "Choose an option. Editing waits while this question is unanswered.",
      "technical.confirm.ready": "Selected: {choice}. Confirm to continue this example.",
      "technical.confirm.confirmed.simsun": "Demo: SimSun confirmed. The next stage is document editing.",
      "technical.confirm.confirmed.simhei": "Demo: SimHei confirmed. The next stage is document editing.",
      "technical.confirm.confirmed.skip": "Demo: explicitly skipped. This item stays unchanged and is recorded in the report; other validated rules can proceed.",
      "technical.confirm.footnote": "Reliable explicit rules need no item-by-item approval. Skipping does not create a default rule; the item remains in the report.",
      "technical.edit.subtitle": "Deterministic edits. Individual validation.",
      "technical.edit.rules.title": "Only validated rules reach the editor",
      "technical.edit.rules.description": "Translate typed rules into object mapping and an edit plan. Apply specific properties within their scope, preserving meaning, table data and citation content.",
      "technical.edit.versions.title": "Every edit creates a separate version",
      "technical.edit.versions.description": "Keep V0 and published history unchanged. Create a new file from the selected parent version and bind its rule snapshot to the edit, preventing stale results after an answer changes.",
      "technical.edit.validation.title": "Reopen and validate after saving",
      "technical.edit.validation.description": "Check actual formatting, document structure and text again. Record the location, evidence and validation outcome of each change for traceability.",
      "technical.edit.efficiency.title": "Clear execution boundaries, less rework",
      "technical.edit.efficiency.description": "Separate rule interpretation from document execution. Clarify unreliable locations, ambiguous conditions or conflicts before submitting a reliable edit plan.",
      "technical.edit.sequenceLabel": "Document editing steps",
      "technical.edit.locate": "Locate objects",
      "technical.edit.plan": "Build the plan",
      "technical.edit.apply": "Edit a copy",
      "technical.edit.verify": "Reopen and validate",
      "technical.preview.subtitle": "See the result. Refine the details.",
      "technical.preview.visible.title": "Preview, report and version together",
      "technical.preview.visible.description": "Generate PDFs with LibreOffice and use PDF.js to browse, zoom and select text. Review the reasons for changes and download an editable DOCX.",
      "technical.preview.scope.title": "Start refining at your selection",
      "technical.preview.scope.description": "Select text and describe a change with a clear scope. Paragraph properties identify the containing paragraph; broader scope, ambiguous locations or conflicts require clarification.",
      "technical.preview.reuse.title": "Lightweight parsing, reusable results",
      "technical.preview.reuse.description": "Reuse formatting rules and validation for local feedback, alongside verified parsing results and decision snapshots, reducing repeated calls over the full requirements document.",
      "technical.preview.history.title": "Keep refining with traceable history",
      "technical.preview.history.description": "Publish a separate document, report and preview for every refinement. Review history and choose any version as the starting point for further changes.",
      "technical.preview.loop": "Selection and request → Lightweight parsing and scope checks → Necessary clarification → Document editing → New-version preview",
      "technical.prototype.title": "Product prototype showcase",
      "technical.prototype.launch": "Try the interactive prototype",
      "technical.chart.summary": "Upload a thesis draft and institution requirements, then extract evidence and validate. If questions remain, show evidence and options, collect an answer or explicit skip, and check again. Once no questions remain, locate objects, edit and validate. Publish a document version, preview and report. Download the result or submit local feedback, check its scope and clarify as needed, then return validated rules to document editing.",
      "technical.chart.upload": "Upload thesis draft and institution requirements",
      "technical.chart.extract": "Extract requirements and source evidence",
      "technical.chart.validate": "Schema and semantic validation",
      "technical.chart.question": "Questions remaining?",
      "technical.chart.show": "Show evidence and candidate answers",
      "technical.chart.show.detail": "Include an explicit skip option",
      "technical.chart.answer": "User answers each question",
      "technical.chart.answer.detail": "Or explicitly skips the item",
      "technical.chart.locate": "Locate objects and build an edit plan",
      "technical.chart.edit": "Edit a copy and validate",
      "technical.chart.preview": "Draft or new version, preview and report",
      "technical.chart.download": "Download result",
      "technical.chart.refine": "Local selection and refinement request",
      "technical.chart.feedback": "Lightweight parsing, scope checks and necessary clarification",
      "technical.chart.yes": "Yes",
      "technical.chart.no": "No questions remaining",
      "technical.chart.recheck": "Check again",
      "technical.chart.verified": "Validated rules",
      "technical.chart.legend.main": "Main workflow",
      "technical.chart.legend.confirm": "Pre-edit confirmation loop",
      "technical.chart.legend.refine": "Local refinement loop",
      "technical.dialog.kicker": "MODULE DETAILS",
      "technical.dialog.openHint": "(Click for details)",
      "technical.dialog.close": "Close module details",
      "technical.dialog.content": "Detailed module introduction",
      "technical.dialog.hint": "Click outside the card, or keep scrolling down after the content ends, to return to the workflow.",
      "benchmark.kicker": "AI SELECTION & PRODUCT TUNING",
      "benchmark.title": "Performance Improvement",
      "benchmark.subtitle": "More accurate. More reliable. Faster. More efficient.",
      "benchmark.context": "Use a fixed Qwen Flash version with an OpenAI adapter available. Tune domain vocabulary, prompts, context and evidence checks to improve quality, speed and token usage.",
      "benchmark.quality": "Quality & Reliability",
      "benchmark.efficiency": "Efficiency",
      "benchmark.note": "Data from 20 internal tests.",
    },
  };

  // Chinese copy lives in the HTML so it remains readable without JavaScript.
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    const key = element.dataset.i18n;
    if (!Object.hasOwn(messages["zh-CN"], key)) messages["zh-CN"][key] = element.textContent;
  });
  document.querySelectorAll("[data-i18n-aria]").forEach((element) => {
    const key = element.dataset.i18nAria;
    if (!Object.hasOwn(messages["zh-CN"], key)) messages["zh-CN"][key] = element.getAttribute("aria-label");
  });

  const header = document.querySelector(".site-header");
  const menuToggle = document.querySelector(".menu-toggle");
  const navigation = document.querySelector(".site-nav");
  const links = [...document.querySelectorAll(".nav-link")];
  const currentPage = document.body.dataset.page || "product";
  const languageButtons = [...document.querySelectorAll("[data-language]")];
  const filterButtons = [...document.querySelectorAll("[data-format-filter]")];
  const formatRows = [...document.querySelectorAll("[data-format-group]")];
  const productControls = document.querySelector(".hero-actions");
  const productToggles = [...document.querySelectorAll("[data-product-toggle]")];
  const flowPanel = document.getElementById("product-flow");
  const flowSteps = [...(flowPanel?.querySelectorAll(".flow-step") ?? [])];
  const productDisclosures = new Map(productToggles.map((trigger) => {
    const panel = document.getElementById(trigger.getAttribute("aria-controls"));
    panel.hidden = true;
    panel.inert = true;
    panel.setAttribute("aria-hidden", "true");
    return [trigger.dataset.productToggle, {
      panel, trigger, content: panel.querySelector(".product-disclosure-content"),
      open: false, animation: null, contentAnimation: null,
    }];
  }));
  const compactLayout = window.matchMedia("(max-width: 1120px)");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const storageKey = "autoformat-site-language";
  const confirmationForm = document.getElementById("confirmation-demo");
  let confirmedDemoChoice = null;
  let language = "zh-CN";
  let scrollQueued = false;
  let formatFilter = null;
  let flowConnectionObserver = null;

  function updateFormatStatus() {
    const status = document.getElementById("format-status");
    if (!status) return;
    const count = formatRows.filter((row) => !row.hidden).length;
    status.textContent = formatFilter === null
      ? messages[language]["formats.collapsed"]
      : messages[language]["formats.status"].replace("{count}", count);
  }

  function revealFlowConnections() {
    flowConnectionObserver?.disconnect();
    if (reducedMotion.matches || typeof IntersectionObserver !== "function") {
      flowSteps.slice(0, -1).forEach((step) => step.classList.add("is-connected"));
      return;
    }
    // Draw each link when its destination icon reaches the reading area.
    flowConnectionObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const index = flowSteps.findIndex((step) => step.contains(entry.target));
        flowSteps[index - 1].classList.add("is-connected");
        flowConnectionObserver.unobserve(entry.target);
      });
    }, { threshold: 1, rootMargin: "0px 0px -10% 0px" });
    flowSteps.slice(1).forEach((step) => flowConnectionObserver.observe(step.querySelector(".flow-icon")));
  }

  function setProductDetails(detail, open, nextFilter = "all") {
    const state = productDisclosures.get(detail);
    const { panel, content, trigger } = state;
    const wasOpen = state.open;
    // Capture the displayed height before cancelling, so rapid toggles remain continuous.
    const startHeight = panel.getBoundingClientRect().height;
    const startOpacity = panel.hidden ? 0 : Number(getComputedStyle(panel).opacity);
    state.animation?.cancel();
    state.contentAnimation?.cancel();
    state.animation = null;
    state.contentAnimation = null;
    state.open = open;
    if (detail === "formats") {
      formatFilter = open ? nextFilter : null;
      if (open) formatRows.forEach((row) => { row.hidden = formatFilter !== "all" && row.dataset.formatGroup !== formatFilter; });
      filterButtons.forEach((button) => {
        const expanded = button.dataset.formatFilter === formatFilter;
        button.setAttribute("aria-pressed", String(expanded));
        button.setAttribute("aria-expanded", String(expanded));
      });
      updateFormatStatus();
    }
    if (detail === "flow" && !open) {
      flowConnectionObserver?.disconnect();
      flowSteps.forEach((step) => step.classList.remove("is-connected"));
    }
    if (open) {
      panel.hidden = false;
      panel.classList.add("is-open");
    }
    panel.inert = !open;
    panel.setAttribute("aria-hidden", String(!open));
    trigger.setAttribute("aria-expanded", String(open));

    const finish = () => {
      panel.classList.remove("is-animating");
      if (!open) {
        panel.hidden = true;
        panel.classList.remove("is-open");
      } else if (detail === "flow" && !wasOpen) {
        revealFlowConnections();
      }
      // The cover fills one screen, so bring newly opened content into view.
      if (open && !wasOpen && panel.getBoundingClientRect().top > window.innerHeight - 120) {
        window.scrollTo({
          top: window.scrollY + panel.getBoundingClientRect().top - header.offsetHeight - 24,
          behavior: reducedMotion.matches ? "instant" : "smooth",
        });
      }
      queuePositionUpdate();
    };
    if (reducedMotion.matches || typeof panel.animate !== "function") {
      finish();
      return;
    }
    panel.classList.add("is-animating");
    const animation = panel.animate([
      { height: `${startHeight}px`, opacity: startOpacity },
      { height: `${open ? content.offsetHeight : 0}px`, opacity: open ? 1 : 0 },
    ], { duration: 420, easing: "cubic-bezier(0.22, 1, 0.36, 1)" });
    state.animation = animation;
    animation.onfinish = () => {
      if (state.animation !== animation) return;
      state.animation = null;
      finish();
    };
    if (open) {
      state.contentAnimation = content.animate([
        { opacity: 0.45, transform: "translateY(6px)" },
        { opacity: 1, transform: "translateY(0)" },
      ], { duration: 300, easing: "ease-out" });
    }
  }

  function finishProductTransition() {
    productDisclosures.forEach((state) => {
      state.animation?.finish();
      state.contentAnimation?.finish();
    });
  }

  function collapseProductDetails(detail) {
    productDisclosures.get(detail).trigger.focus({ preventScroll: true });
    const controlsTop = productControls.getBoundingClientRect().top;
    if (controlsTop < header.offsetHeight + 24) {
      window.scrollTo({ top: window.scrollY + controlsTop - header.offsetHeight - 24, behavior: reducedMotion.matches ? "instant" : "smooth" });
    }
    setProductDetails(detail, false);
  }

  function filterFormats(nextFilter) {
    if (nextFilter === null) collapseProductDetails("formats");
    else setProductDetails("formats", true, nextFilter);
  }

  function updateConfirmationDemo() {
    if (!confirmationForm) return;
    const selected = confirmationForm.querySelector('input[name="font-rule"]:checked');
    const copy = messages[language];
    const status = confirmationForm.querySelector(".confirmation-status");
    confirmationForm.querySelector('[type="submit"]').disabled = !selected;
    if (selected && confirmedDemoChoice === selected.value) {
      status.textContent = copy[`technical.confirm.confirmed.${selected.value}`];
      confirmationForm.dataset.state = "confirmed";
    } else if (selected) {
      status.textContent = copy["technical.confirm.ready"].replace("{choice}", copy[`technical.confirm.${selected.value}`]);
      confirmationForm.dataset.state = "ready";
    } else {
      status.textContent = copy["technical.confirm.pending"];
      confirmationForm.dataset.state = "pending";
    }
  }

  function setMenu(open, restoreFocus = false) {
    header.dataset.menuOpen = String(open);
    menuToggle.setAttribute("aria-expanded", String(open));
    menuToggle.setAttribute("aria-label", messages[language][open ? "closeMenu" : "openMenu"]);
    menuToggle.dataset.i18nAria = open ? "closeMenu" : "openMenu";
    if (restoreFocus) menuToggle.focus({ preventScroll: true });
  }

  function setLanguage(nextLanguage, persist = true) {
    if (!Object.hasOwn(messages, nextLanguage)) return;
    finishProductTransition();
    language = nextLanguage;
    const copy = messages[language];
    document.documentElement.lang = language;
    const title = copy[`page.${currentPage}.title`] ?? copy.title;
    const description = copy[`page.${currentPage}.description`] ?? copy.description;
    document.title = title;
    document.querySelector('meta[name="description"]').content = description;
    document.querySelectorAll('meta[property="og:title"], meta[name="twitter:title"]').forEach((meta) => { meta.content = title; });
    document.querySelectorAll('meta[property="og:description"], meta[name="twitter:description"]').forEach((meta) => { meta.content = description; });
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      const text = copy[element.dataset.i18n] ?? messages["zh-CN"][element.dataset.i18n];
      if (text) element.textContent = text;
    });
    document.querySelectorAll("[data-i18n-aria]").forEach((element) => {
      const text = copy[element.dataset.i18nAria] ?? messages["zh-CN"][element.dataset.i18nAria];
      if (text) element.setAttribute("aria-label", text);
    });
    languageButtons.forEach((button) => {
      button.disabled = false;
      button.setAttribute("aria-pressed", String(button.dataset.language === language));
    });
    updateFormatStatus();
    updateConfirmationDemo();
    queuePositionUpdate();
    document.dispatchEvent(new Event("autoformat:languagechange"));
    if (persist) {
      try { localStorage.setItem(storageKey, language); } catch { /* The switch still works without storage. */ }
    }
  }

  function updatePosition() {
    scrollQueued = false;
    header.dataset.scrolled = String(window.scrollY > 12);
    document.documentElement.dataset.section = currentPage;
    links.forEach((link) => {
      if (link.dataset.page === currentPage) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  function queuePositionUpdate() {
    if (scrollQueued) return;
    scrollQueued = true;
    requestAnimationFrame(updatePosition);
  }

  languageButtons.forEach((button) => {
    button.addEventListener("click", () => setLanguage(button.dataset.language));
  });
  filterButtons.forEach((button) => button.addEventListener("click", () => {
    filterFormats(button.dataset.formatFilter === formatFilter ? null : button.dataset.formatFilter);
  }));
  productToggles.forEach((button) => button.addEventListener("click", () => {
    const detail = button.dataset.productToggle;
    if (productDisclosures.get(detail).open) collapseProductDetails(detail);
    else setProductDetails(detail, true);
  }));
  document.querySelectorAll("[data-product-collapse]").forEach((button) => button.addEventListener("click", () => {
    const detail = button.getAttribute("aria-controls") === flowPanel.id ? "flow" : "formats";
    collapseProductDetails(detail);
  }));
  window.addEventListener("resize", finishProductTransition, { passive: true });
  reducedMotion.addEventListener("change", (event) => {
    if (event.matches) {
      finishProductTransition();
      if (productDisclosures.get("flow")?.open) revealFlowConnections();
    }
  });
  confirmationForm?.addEventListener("change", () => {
    confirmedDemoChoice = null;
    updateConfirmationDemo();
  });
  confirmationForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    const selected = confirmationForm.querySelector('input[name="font-rule"]:checked');
    if (!selected) return;
    confirmedDemoChoice = selected.value;
    updateConfirmationDemo();
  });
  confirmationForm?.addEventListener("reset", () => {
    confirmedDemoChoice = null;
    requestAnimationFrame(updateConfirmationDemo);
  });
  menuToggle.addEventListener("click", () => setMenu(header.dataset.menuOpen !== "true"));
  navigation.addEventListener("click", (event) => {
    if (event.target.closest("a")) setMenu(false);
  });
  document.querySelector(".wordmark").addEventListener("click", () => setMenu(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && header.dataset.menuOpen === "true") setMenu(false, true);
  });
  document.addEventListener("click", (event) => {
    if (header.dataset.menuOpen === "true" && !header.contains(event.target)) setMenu(false);
  });
  document.addEventListener("focusin", (event) => {
    if (header.dataset.menuOpen === "true" && !header.contains(event.target)) setMenu(false);
  });
  compactLayout.addEventListener("change", () => setMenu(false));
  window.addEventListener("scroll", queuePositionUpdate, { passive: true });
  window.addEventListener("resize", queuePositionUpdate, { passive: true });
  window.addEventListener("pageshow", queuePositionUpdate);

  let storedLanguage;
  try {
    storedLanguage = localStorage.getItem(storageKey);
    if (storedLanguage === null) {
      const legacyLanguage = localStorage.getItem("easyformat-site-language");
      if (Object.hasOwn(messages, legacyLanguage)) {
        storedLanguage = legacyLanguage;
        localStorage.setItem(storageKey, legacyLanguage);
      }
    }
  } catch { /* Default to Chinese when storage is unavailable. */ }
  setLanguage(Object.hasOwn(messages, storedLanguage) ? storedLanguage : "zh-CN", false);
  updatePosition();

  if (typeof IntersectionObserver === "function" && !reducedMotion.matches) {
    function observeOnce(selector, options) {
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        });
      }, options);
      document.querySelectorAll(selector).forEach((element) => observer.observe(element));
    }
    observeOnce(".reveal", { threshold: 0.08, rootMargin: "0px 0px -20px 0px" });
    observeOnce(".flow-steps", { threshold: 0.15, rootMargin: "0px 0px -64px 0px" });
    observeOnce(".workflow-graph", { threshold: 0.1, rootMargin: "0px 0px -32px 0px" });
    document.documentElement.classList.add("motion-ready");
    reducedMotion.addEventListener("change", (event) => {
      if (event.matches) document.documentElement.classList.remove("motion-ready");
    });
  }
})();
